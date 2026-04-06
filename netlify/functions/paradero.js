/**
 * Netlify Function: /api/paradero/PA467
 *
 * Fuente: scraping de m.ibus.cl
 * Usa node-fetch v2 + agente HTTPS con rejectUnauthorized:false
 * (equivalente a requests verify=False en Python — m.ibus.cl tiene cert inválido)
 */

const fetch    = require('node-fetch');
const http     = require('http');
const https    = require('https');
const { load } = require('cheerio');

const httpAgent  = new http.Agent();
const httpsAgent = new https.Agent({ rejectUnauthorized: false });

// Selecciona el agente correcto según el protocolo de la URL
const agent = (url) => url.startsWith('https:') ? httpsAgent : httpAgent;

// Reintentos con exponential backoff
async function fetchWithRetry(url, options, maxRetries = 3) {
  for (let i = 0; i < maxRetries; i++) {
    let timeout;
    try {
      const controller = new AbortController();
      timeout = setTimeout(() => controller.abort(), 8000); // 8 segundos timeout
      
      const res = await fetch(url, { ...options, signal: controller.signal });
      clearTimeout(timeout);
      return res;
    } catch (err) {
      if (timeout) clearTimeout(timeout);
      if (i === maxRetries - 1) throw err; // último intento
      
      // Exponential backoff: 1s, 2s, 4s
      await new Promise(resolve => setTimeout(resolve, Math.pow(2, i) * 1000));
    }
  }
}

const BASE_URL = 'http://m.ibus.cl';
const HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/29.0 Chrome/136.0.0.0 Mobile Safari/537.36',
  'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
  'Accept-Language': 'es-US,es-419;q=0.9,es;q=0.8',
  'Referer': `${BASE_URL}/index.jsp`,
  'Upgrade-Insecure-Requests': '1',
  'Connection': 'keep-alive',
};

exports.handler = async (event) => {
  // Obtener id: query param (del redirect) o desde la URL original
  let paradero = event.queryStringParameters?.id || '';
  if (!paradero && event.rawUrl) {
    try {
      paradero = new URL(event.rawUrl).pathname.split('/').filter(Boolean).pop() || '';
    } catch (_) {}
  }
  paradero = paradero.toUpperCase().trim();

  if (!paradero) {
    return { statusCode: 400, body: JSON.stringify({ error: 'Código de paradero requerido (ej: PA443)' }) };
  }

  try {
    // 1. Iniciar sesión — obtener cookie de sesión
    const initUrl = `${BASE_URL}/index.jsp`;
    const initRes = await fetchWithRetry(initUrl, {
      headers: HEADERS,
      agent: agent(initUrl),
      redirect: 'follow',
    });
    const cookie = initRes.headers.get('set-cookie') || '';

    // 2. Consultar paradero
    const params   = new URLSearchParams({ paradero, servicio: '', button: 'Consulta Paradero' });
    const mainUrl  = `${BASE_URL}/Servlet?${params}`;
    const mainRes  = await fetchWithRetry(mainUrl, {
      headers: { ...HEADERS, Cookie: cookie },
      agent: agent(mainUrl),
      redirect: 'follow',
    });

    if (!mainRes.ok) {
      return { statusCode: 502, body: JSON.stringify({ error: `iBUS respondió ${mainRes.status}` }) };
    }

    const html = await mainRes.text();
    if (html.length < 100) {
      return { statusCode: 502, body: JSON.stringify({ error: 'Respuesta de iBUS vacía o inválida' }) };
    }

    const $ = load(html);

    // 3. Cabecera (paradero, nombre, hora)
    const datos = {};
    $('table.cabecera4 tr').each((_, row) => {
      const celdas = $(row).find('td');
      if (celdas.length === 3) {
        datos[$(celdas[0]).text().trim()] = $(celdas[2]).text().trim().replace(/\s+/g, ' ');
      }
    });

    // 4. Servicios (recorridos y buses)
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

    return {
      statusCode: 200,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
      body: JSON.stringify({
        paradero:      (datos['Paradero'] || paradero).trim(),
        nombre:        (datos['Nombre']   || '').trim(),
        hora_consulta: (datos['Hora']     || '').trim(),
        servicios,
      }),
    };

  } catch (err) {
    console.error('paradero error:', err);
    
    // Distinguir entre timeout y otros errores
    const isTimeout = err.name === 'AbortError' || err.code === 'ETIMEDOUT' || err.message?.includes('abort');
    const errorMsg = isTimeout 
      ? 'iBUS no responde (timeout después de 3 intentos)'
      : `Error al consultar iBUS: ${err.message}`;
    
    return {
      statusCode: 502,
      body: JSON.stringify({ 
        error: errorMsg,
        detail: err.cause?.message,
        retryable: true // cliente puede reintentar
      }),
    };
  }
};
