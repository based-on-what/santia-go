/**
 * Netlify Function: /api/paradero/PA467
 *
 * Fuente: scraping de http://m.ibus.cl
 */

const { load } = require('cheerio');

const BASE_URL = 'http://m.ibus.cl';
const HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/29.0 Chrome/136.0.0.0 Mobile Safari/537.36',
  'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
  'Accept-Language': 'es-US,es-419;q=0.9,es;q=0.8',
  'Referer': `${BASE_URL}/index.jsp`,
  'Upgrade-Insecure-Requests': '1',
};

exports.handler = async (event) => {
  // El id llega por query string desde el redirect: /api/paradero/:id → ?id=:id
  const paradero = (event.queryStringParameters?.id || '').toUpperCase().trim();
  if (!paradero) {
    return { statusCode: 400, body: JSON.stringify({ error: 'Código de paradero requerido (ej: PA443)' }) };
  }

  try {
    // 1. Iniciar sesión (obtener cookie)
    const initRes = await fetch(`${BASE_URL}/index.jsp`, { headers: HEADERS });
    const cookie  = initRes.headers.get('set-cookie') || '';

    // 2. Consultar paradero
    const params  = new URLSearchParams({ paradero, servicio: '', button: 'Consulta Paradero' });
    const mainRes = await fetch(`${BASE_URL}/Servlet?${params}`, {
      headers: { ...HEADERS, Cookie: cookie },
    });

    if (!mainRes.ok) {
      return { statusCode: 502, body: JSON.stringify({ error: `iBUS respondió ${mainRes.status}` }) };
    }

    const html = await mainRes.text();
    if (html.length < 100) {
      return { statusCode: 502, body: JSON.stringify({ error: 'Respuesta de iBUS demasiado corta' }) };
    }

    const $ = load(html);

    // 3. Cabecera
    const datos = {};
    $('table.cabecera4 tr').each((_, row) => {
      const celdas = $(row).find('td');
      if (celdas.length === 3) {
        const clave = $(celdas[0]).text().trim();
        const valor = $(celdas[2]).text().trim().replace(/\s+/g, ' ');
        datos[clave] = valor;
      }
    });

    // 4. Servicios
    const servicios = [];
    $('tr').each((_, row) => {
      const celdas = $(row).find('td.menu_respuesta');
      if (!celdas.length) return;

      const nombre = $(celdas[0]).text().trim();

      if (celdas.length === 2) {
        servicios.push({ servicio: nombre, bus: null, tiempo: $(celdas[1]).text().trim(), distancia_metros: null });
      } else if (celdas.length === 4) {
        const dist = $(celdas[3]).text().trim();
        servicios.push({
          servicio:         nombre,
          bus:              $(celdas[1]).text().trim(),
          tiempo:           $(celdas[2]).text().trim(),
          distancia_metros: /^\d+$/.test(dist) ? parseInt(dist, 10) : null,
        });
      }
    });

    const result = {
      paradero:      (datos['Paradero'] || paradero).trim(),
      nombre:        (datos['Nombre']   || '').trim(),
      hora_consulta: (datos['Hora']     || '').trim(),
      servicios,
    };

    return {
      statusCode: 200,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
      body: JSON.stringify(result),
    };

  } catch (err) {
    console.error('paradero error:', err);
    return {
      statusCode: 502,
      body: JSON.stringify({ error: `Error al consultar iBUS: ${err.message}` }),
    };
  }
};
