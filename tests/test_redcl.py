import base64
import json
import unittest
from pathlib import Path
from unittest import mock

import requests
from fastapi import HTTPException

from metro.infrastructure import redcl
from metro.infrastructure.redcl import RedClClient, RedClError, to_stop_payload
from routes import ibus as ibus_route

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "redcl_pa443.json").read_text(encoding="utf-8"))
NOW = 1_800_000_000.0


def make_jwt(exp: float) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJIUzI1NiJ9.{payload}.signature"


def page_with(jwt: str) -> str:
    return f"<script> $jwt = '{base64.b64encode(jwt.encode()).decode()}'; $codsimt = ''; </script>"


def response(status: int, body: str | dict, content_type: str = "application/json") -> requests.Response:
    resp = requests.Response()
    resp.status_code = status
    resp._content = (json.dumps(body) if isinstance(body, dict) else body).encode("utf-8")
    resp.encoding = "utf-8"
    resp.headers["Content-Type"] = content_type
    return resp


class FakeSession:
    def __init__(self, routes: dict[str, list]):
        self.headers: dict = {}
        self.routes = {url: list(outcomes) for url, outcomes in routes.items()}
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        outcome = self.routes[url].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def count(self, url: str) -> int:
        return sum(1 for called, _ in self.calls if called == url)


def client_with(predictions: list, pages: list | None = None, clock=lambda: NOW) -> tuple[RedClClient, FakeSession]:
    session = FakeSession({
        redcl.PAGE_URL: pages if pages is not None else [response(200, page_with(make_jwt(NOW + 3600)), "text/html")],
        redcl.PREDICTOR_URL: predictions,
    })
    return RedClClient(session=session, clock=clock), session


class PayloadMappingTest(unittest.TestCase):
    def test_real_pa443_response_maps_to_the_frontend_contract(self):
        payload = to_stop_payload(FIXTURE)

        self.assertEqual(payload["paradero"], "PA443")
        self.assertEqual(payload["nombre"], FIXTURE["nomett"])
        self.assertEqual(payload["hora_consulta"], FIXTURE["horaprediccion"])
        self.assertEqual(len(payload["servicios"]), 9)  # 4 services x 2 buses + 1 service without buses
        self.assertEqual(payload["servicios"][0], {"servicio": "506", "bus": "VZVV-63", "tiempo": "Llegando", "distancia_metros": 599})
        self.assertEqual(payload["servicios"][-1]["servicio"], "507c")
        self.assertIsNone(payload["servicios"][-1]["bus"])
        self.assertEqual(payload["servicios"][-1]["tiempo"], "No hay buses que se dirijan al paradero")

    def test_single_item_dict_with_one_bus(self):
        data = {"paradero": "PA1", "nomett": "X", "servicios": {"item": {"servicio": "101", "ppubus1": "AB-12", "horaprediccionbus1": "Llegando", "distanciabus1": "n/d", "ppubus2": ""}}}

        servicios = to_stop_payload(data)["servicios"]

        self.assertEqual(servicios, [{"servicio": "101", "bus": "AB-12", "tiempo": "Llegando", "distancia_metros": None}])

    def test_missing_service_list_is_an_error_not_an_empty_stop(self):
        for servicios in (None, {}, {"item": None}, "texto"):
            with self.subTest(servicios=servicios), self.assertRaises(RedClError) as ctx:
                to_stop_payload({"paradero": "PA1", "nomett": "X", "servicios": servicios})
            self.assertEqual(ctx.exception.status_code, 502)


class TokenLifecycleTest(unittest.TestCase):
    def test_reuses_the_token_until_it_is_close_to_expiry(self):
        now = [NOW]
        pages = [response(200, page_with(make_jwt(NOW + 3600)), "text/html"), response(200, page_with(make_jwt(NOW + 7200)), "text/html")]
        client, session = client_with([response(200, FIXTURE)] * 3, pages=pages, clock=lambda: now[0])

        client.query_stop("PA443")
        client.query_stop("PA443")
        self.assertEqual(session.count(redcl.PAGE_URL), 1)

        now[0] = NOW + 3600 - redcl.TOKEN_REFRESH_MARGIN_S
        client.query_stop("PA443")
        self.assertEqual(session.count(redcl.PAGE_URL), 2)

    def test_rejected_token_is_refreshed_once_and_the_query_succeeds(self):
        first, second = make_jwt(NOW + 3600), make_jwt(NOW + 3601)
        pages = [response(200, page_with(first), "text/html"), response(200, page_with(second), "text/html")]
        rejected = response(500, "Token inválido", "text/plain")
        client, session = client_with([rejected, response(200, FIXTURE)], pages=pages)

        payload = client.query_stop("PA443")

        self.assertEqual(len(payload["servicios"]), 9)
        tokens_sent = [kwargs["params"]["t"] for url, kwargs in session.calls if url == redcl.PREDICTOR_URL]
        self.assertEqual(tokens_sent, [first, second])

    def test_gives_up_after_one_retry(self):
        rejected = response(500, "Token inválido", "text/plain")
        pages = [response(200, page_with(make_jwt(NOW + 3600)), "text/html")] * 2
        client, session = client_with([rejected, rejected], pages=pages)

        with self.assertRaises(RedClError) as ctx:
            client.query_stop("PA443")

        self.assertEqual(ctx.exception.status_code, 502)
        self.assertEqual(session.count(redcl.PREDICTOR_URL), 2)

    def test_page_without_jwt_is_a_502(self):
        client, _ = client_with([], pages=[response(200, "<html>sin token</html>", "text/html")])

        with self.assertRaises(RedClError) as ctx:
            client.query_stop("PA443")

        self.assertEqual(ctx.exception.status_code, 502)


class ErrorMappingTest(unittest.TestCase):
    def test_unknown_stop_is_a_404(self):
        client, _ = client_with([response(200, {"nomett": "", "paradero": "", "respuestaParadero": "23 - Paradero Invalido", "servicios": {}})])

        with self.assertRaises(RedClError) as ctx:
            client.query_stop("PZ9999")

        self.assertEqual(ctx.exception.status_code, 404)

    def test_network_errors_map_to_fixed_messages_without_the_token(self):
        jwt = make_jwt(NOW + 3600)
        cases = [
            (requests.exceptions.ConnectTimeout(f"url: /predictorPlus/prediccion?t={jwt}"), 504),
            (requests.exceptions.ConnectionError(f"url: /predictorPlus/prediccion?t={jwt}"), 502),
        ]
        for exc, expected_status in cases:
            with self.subTest(exc=type(exc).__name__):
                pages = [response(200, page_with(jwt), "text/html")]
                client, _ = client_with([exc], pages=pages)
                with self.assertLogs(redcl.logger, level="WARNING") as logs, self.assertRaises(RedClError) as ctx:
                    client.query_stop("PA443")
                self.assertEqual(ctx.exception.status_code, expected_status)
                self.assertNotIn(jwt, str(ctx.exception))
                self.assertNotIn(jwt, "\n".join(logs.output))

    def test_requests_use_timeouts_and_the_stop_code(self):
        client, session = client_with([response(200, FIXTURE)])

        client.query_stop("PA443")

        url, kwargs = session.calls[-1]
        self.assertEqual(url, redcl.PREDICTOR_URL)
        self.assertEqual(kwargs["params"]["codsimt"], "PA443")
        self.assertEqual(kwargs["timeout"], redcl.TIMEOUT_S)


class RouteTest(unittest.TestCase):
    def test_invalid_codes_are_rejected_before_any_request(self):
        for code in ("", "PA", "123", "PA443X", "PA-443", "../x", "P" * 20):
            with self.subTest(code=code), mock.patch.object(ibus_route._redcl_client, "query_stop") as query:
                with self.assertRaises(HTTPException) as ctx:
                    ibus_route.consultar_paradero(code)
                self.assertEqual(ctx.exception.status_code, 422)
                query.assert_not_called()

    def test_valid_code_is_normalized_and_client_errors_keep_their_status(self):
        with mock.patch.object(ibus_route._redcl_client, "query_stop", return_value={"ok": True}) as query:
            self.assertEqual(ibus_route.consultar_paradero(" pa443 "), {"ok": True})
            query.assert_called_once_with("PA443")
        with mock.patch.object(ibus_route._redcl_client, "query_stop", side_effect=RedClError("red.cl no respondio a tiempo", 504)):
            with self.assertRaises(HTTPException) as ctx:
                ibus_route.consultar_paradero("PA443")
        self.assertEqual((ctx.exception.status_code, ctx.exception.detail), (504, "red.cl no respondio a tiempo"))


if __name__ == "__main__":
    unittest.main()
