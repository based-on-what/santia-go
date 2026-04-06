/**
 * Cloudflare Worker — proxy para m.ibus.cl
 *
 * Deploy: wrangler deploy (o pegar en el editor de workers.cloudflare.com)
 * Una vez deployado, copiar la URL (ej: https://ibus-proxy.TU_USUARIO.workers.dev)
 * y setearla como variable de entorno IBUS_PROXY_URL en Railway.
 */

const TARGET = "http://m.ibus.cl";

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const targetUrl = TARGET + url.pathname + url.search;

    try {
      const response = await fetch(targetUrl, {
        method: request.method,
        headers: {
          "User-Agent":
            "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/29.0 Chrome/136.0.0.0 Mobile Safari/537.36",
          Accept:
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
          "Accept-Language": "es-CL,es-419;q=0.9,es;q=0.8",
          "Upgrade-Insecure-Requests": "1",
        },
        // No seguir redirecciones automáticamente para retornar la respuesta tal cual
        redirect: "follow",
      });

      // Copiar headers relevantes de la respuesta original
      const headers = new Headers();
      for (const [key, value] of response.headers.entries()) {
        if (
          ["content-type", "content-encoding", "transfer-encoding"].includes(
            key.toLowerCase()
          )
        ) {
          headers.set(key, value);
        }
      }

      return new Response(response.body, {
        status: response.status,
        headers,
      });
    } catch (err) {
      return new Response(
        JSON.stringify({ error: "Error al contactar iBUS", detail: err.message }),
        { status: 502, headers: { "Content-Type": "application/json" } }
      );
    }
  },
};
