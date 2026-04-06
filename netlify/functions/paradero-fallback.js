/**
 * Netlify Function: /api/paradero/PA467 (con fallback a CORS proxy)
 *
 * Estrategia:
 * 1. Intenta conexión directa a m.ibus.cl (rápido)
 * 2. Si falla, usa proxy CORS como fallback
 * 3. Caching para reducir dependencia de iBUS
 */

const fetch    = require('node-fetch');
const http     = require('http');
const https    = require('https');
const { load } = require('cheerio');

const httpAgent  = new http.Agent();
const httpsAgent = new https.Agent({ rejectUnauthorized: false });

const agent = (url) => url.startsWith('https:') ? httpsAgent : httpAgent;

const BASE_URL = 'http://m.ibus.cl';
// Proxy CORS: https://corsproxy.io/?url=URL
const PROXY_URL = 'https://corsproxy.io/?url=';

const HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/29.0 Chrome/136.0.0.0 Mobile Safari/537.36',
  'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
  'Accept-Language': 'es-US,es-419;q=0.9,es;q=0.8',
  'Referer': `${BASE_URL}/index.jsp`,
  'Upgrade-Insecure-Requests': '1',
};

// Cache en memoria
const CACHE = new Map();
const CACHE_TTL = 5 * 60 * 1000; // 5 minutos

async function fetchWithRetry(url, options, maxRetries = 2, useProxy = false) {
  const fetchUrl = useProxy ? PROXY_URL + encodeURIComponent(url) : url;
  
  for (let i = 0; i < maxRetries; i++) {
    let timeout;
    try {
      const controller = new AbortController();
      timeout = setTimeout(() => controller.abort(), 5000); // 5 segundos
      
      const res = await fetch(fetchUrl, { 
        ...options, 
        signal: controller.signal,
        agent: useProxy ? undefined : agent(url), // proxy no usa agent
      });
      clearTimeout(timeout);
      return res;
    } catch (err) {
      if (timeout) clearTimeout(timeout);
      if (i === maxRetries - 1) throw err;
      
      // Backoff rápido: 300ms, 600ms
      await new Promise(resolve => setTimeout(resolve, 300 * Math.pow(2, i)));
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

async function consultarParadero(paradero, useProxy = false) {
  // 1. Iniciar sesión
  const initUrl = `${BASE_URL}/index.jsp`;
  const initRes = await fetchWithRetry(initUrl, {
    headers: HEADERS,
    redirect: 'follow',
  }, 2, useProxy);
  
  const cookie = initRes.headers.get('set-cookie') || '';

  // 2. Consultar paradero
  const params   = new URLSearchParams({ paradero, servicio: '', button: 'Consulta Paradero' });
  const mainUrl  = `${BASE_URL}/Servlet?${params}`;
  const mainRes  = await fetchWithRetry(mainUrl, {
    headers: { ...HEADERS, Cookie: cookie },
    redirect: 'follow',
  }, 2, useProxy);

  if (!mainRes.ok) {
    throw new Error(`iBUS respondió ${mainRes.status}`);
  }

  const html = await mainRes.text();
  if (html.length < 100) {
    throw new Error('Respuesta de iBUS vacía');
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
    return { statusCode: 400, body: JSON.stringify({ error: 'Código de paradero requerido' }) };
  }

  try {
    // Intentar obtener del cache
    const cached = getCached(paradero);
    if (cached) {
      console.log(`✓ Paradero ${paradero} del cache`);
      return {
        statusCode: 200,
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
        body: JSON.stringify({ ...cached, cached: true }),
      };
    }

    // Intentar conexión DIRECTA primero
    try {
      console.log(`→ Intentando conexión directa a iBUS para ${paradero}`);
      const resultado = await consultarParadero(paradero, false);
      setCached(paradero, resultado);
      
      return {
        statusCode: 200,
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
        body: JSON.stringify(resultado),
      };
    } catch (directErr) {
      console.warn(`✗ Conexión directa falló: ${directErr.message}`);
      
      // FALLBACK: Intentar con PROXY
      console.log(`→ Intentando fallback con proxy CORS para ${paradero}`);
      const resultado = await consultarParadero(paradero, true);
      setCached(paradero, resultado);
      
      return {
        statusCode: 200,
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
        body: JSON.stringify({ ...resultado, via_proxy: true }),
      };
    }

  } catch (err) {
    console.error(`✗ Error final para ${paradero}: ${err.message}`);
    
    const isTimeout = err.name === 'AbortError' || err.code === 'ETIMEDOUT';
    const errorMsg = isTimeout 
      ? 'iBUS no alcanzable (timeout)'
      : `Error: ${err.message}`;
    
    return {
      statusCode: 502,
      body: JSON.stringify({ 
        error: errorMsg,
        retryable: true,
        suggestion: 'El servidor iBUS no responde actualmente. Intenta de nuevo en unos momentos.'
      }),
    };
  }
};
