/**
 * Netlify Function: /api/paradero/PA467 (con caching)
 *
 * Mismo que paradero.js pero con caching en memoria
 * - Cache expira cada 5 minutos
 * - Reduce carga en iBUS
 */

const fetch    = require('node-fetch');
const http     = require('http');
const https    = require('https');
const { load } = require('cheerio');

const httpAgent  = new http.Agent();
const httpsAgent = new https.Agent({ rejectUnauthorized: false });

const agent = (url) => url.startsWith('https:') ? httpsAgent : httpAgent;

const BASE_URL = 'http://m.ibus.cl';
const HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/29.0 Chrome/136.0.0.0 Mobile Safari/537.36',
  'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
  'Accept-Language': 'es-US,es-419;q=0.9,es;q=0.8',
  'Referer': `${BASE_URL}/index.jsp`,
  'Upgrade-Insecure-Requests': '1',
  'Connection': 'keep-alive',
};

// Cache en memoria (se reinicia con cada deploy)
const CACHE = new Map();
const CACHE_TTL = 5 * 60 * 1000; // 5 minutos

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
      if (i === maxRetries - 1) throw err;
      
      // Exponential backoff: 1s, 2s, 4s
      await new Promise(resolve => setTimeout(resolve, Math.pow(2, i) * 1000));
    }
  }
}

function getCacheKey(paradero) {
  return `paradero:${paradero.toUpperCase()}`;
}

function getCached(paradero) {
  const key = getCacheKey(paradero);
  const cached = CACHE.get(key);
  
  if (!cached) return null;
  if (Date.now() - cached.timestamp > CACHE_TTL) {
    CACHE.delete(key);
    return null;
  }
  
  return cached.data;
}

function setCached(paradero, data) {
  const key = getCacheKey(paradero);
  CACHE.set(key, { data, timestamp: Date.now() });
}

async function consultarParadero(paradero) {
  // 1. Iniciar sesión
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
    throw new Error(`iBUS respondió ${mainRes.status}`);
  }

  const html = await mainRes.text();
  if (html.length < 100) {
    throw new Error('Respuesta de iBUS vacía o inválida');
  }

  const $ = load(html);

  // 3. Cabecera
  const datos = {};
  $('table.cabecera4 tr').each((_, row) => {
    const celdas = $(row).find('td');
    if (celdas.length === 3) {
      datos[$(celdas[0]).text().trim()] = $(celdas[2]).text().trim().replace(/\s+/g, ' ');
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

  return {
    paradero:      (datos['Paradero'] || paradero).trim(),
    nombre:        (datos['Nombre']   || '').trim(),
    hora_consulta: (datos['Hora']     || '').trim(),
    servicios,
  };
}

exports.handler = async (event) => {
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
    // Intentar obtener del cache
    const cached = getCached(paradero);
    if (cached) {
      cached.cached = true; // marcar como cached
      return {
        statusCode: 200,
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*', 'Cache-Control': 'max-age=300' },
        body: JSON.stringify(cached),
      };
    }

    // Consultar iBUS
    const resultado = await consultarParadero(paradero);
    
    // Guardar en cache
    setCached(paradero, resultado);

    return {
      statusCode: 200,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*', 'Cache-Control': 'max-age=300' },
      body: JSON.stringify(resultado),
    };

  } catch (err) {
    console.error('paradero error:', err);
    
    const isTimeout = err.name === 'AbortError' || err.code === 'ETIMEDOUT' || err.message?.includes('abort');
    const errorMsg = isTimeout 
      ? 'iBUS no responde (timeout después de 3 intentos)'
      : `Error al consultar iBUS: ${err.message}`;
    
    return {
      statusCode: 502,
      body: JSON.stringify({ 
        error: errorMsg,
        retryable: true
      }),
    };
  }
};
