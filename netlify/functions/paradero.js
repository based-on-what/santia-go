/**
 * Netlify Function: /api/paradero/PA467
 *
 * Equivalente JavaScript del backend Python (tools/python/ibus.py)
 * - Mismo comportamiento que requests.Session() de Python
 * - Mismo parsing que BeautifulSoup
 * - 100% funcional en Netlify
 */

const fetch = require('node-fetch');
const http = require('http');
const https = require('https');
const { load } = require('cheerio');

const httpAgent = new http.Agent();
const httpsAgent = new https.Agent({ rejectUnauthorized: false });

const agent = (url) => url.startsWith('https:') ? httpsAgent : httpAgent;

const BASE_URL = 'http://m.ibus.cl';
const HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/29.0 Chrome/136.0.0.0 Mobile Safari/537.36',
  'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
  'Accept-Language': 'es-US,es-419;q=0.9,es;q=0.8',
  'Referer': `${BASE_URL}/index.jsp`,
  'Upgrade-Insecure-Requests': '1',
  'Connection': 'keep-alive',
};

// Cache en memoria (5 minutos)
const CACHE = new Map();
const CACHE_TTL = 5 * 60 * 1000;

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

/**
 * consultar_paradero(paradero) - Equivalente Python
 * Obtiene HTML desde iBUS manteniendo sesión con cookies
 */
async function consultarParadero(paradero, servicio = '') {
  // 1. Iniciar sesión - obtener cookie
  const initUrl = `${BASE_URL}/index.jsp`;
  const initRes = await fetch(initUrl, {
    headers: HEADERS,
    agent: agent(initUrl),
    redirect: 'follow',
  });
  
  const cookie = initRes.headers.get('set-cookie') || '';

  // 2. Consultar paradero con cookie de sesión
  const params = new URLSearchParams({
    paradero: paradero,
    servicio: servicio,
    button: 'Consulta Paradero'
  });
  
  const mainUrl = `${BASE_URL}/Servlet?${params}`;
  const mainRes = await fetch(mainUrl, {
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

  return html;
}

/**
 * parsear_resultado(html) - Equivalente Python
 * Parsea HTML con cheerio (equivalente a BeautifulSoup)
 */
function parsearResultado(html) {
  const $ = load(html);

  // Cabecera
  const datos = {};
  $('table.cabecera4 tr').each((_, row) => {
    const celdas = $(row).find('td');
    if (celdas.length === 3) {
      const clave = $(celdas[0]).text().trim();
      const valor = $(celdas[2]).text().trim();
      datos[clave] = valor;
    }
  });

  // Servicios
  const servicios = [];
  $('tr').each((_, row) => {
    const celdas = $(row).find('td.menu_respuesta');
    if (!celdas.length) return;

    const nombreServicio = $(celdas[0]).text().trim();
    
    if (celdas.length === 2) {
      servicios.push({
        servicio: nombreServicio,
        bus: null,
        tiempo: $(celdas[1]).text().trim(),
        distancia: null
      });
    } else if (celdas.length === 4) {
      servicios.push({
        servicio: nombreServicio,
        bus: $(celdas[1]).text().trim(),
        tiempo: $(celdas[2]).text().trim(),
        distancia: $(celdas[3]).text().trim()
      });
    }
  });

  return {
    ...datos,
    servicios: servicios
  };
}

exports.handler = async (event) => {
  // Obtener ID del paradero
  let paradero = event.queryStringParameters?.id || '';
  if (!paradero && event.rawUrl) {
    try {
      paradero = new URL(event.rawUrl).pathname.split('/').filter(Boolean).pop() || '';
    } catch (_) {}
  }
  paradero = paradero.toUpperCase().trim();

  if (!paradero) {
    return {
      statusCode: 400,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ error: 'Código de paradero requerido (ej: PA443)' })
    };
  }

  try {
    // 1. Intentar obtener del cache
    const cached = getCached(paradero);
    if (cached) {
      console.log(`✓ Paradero ${paradero} obtenido del cache`);
      return {
        statusCode: 200,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*',
          'Cache-Control': 'max-age=60'
        },
        body: JSON.stringify({ ...cached, cached: true })
      };
    }

    // 2. Consultar iBUS
    console.log(`→ Consultando iBUS para paradero ${paradero}`);
    const html = await consultarParadero(paradero);
    
    // 3. Parsear resultado
    const resultado = parsearResultado(html);
    
    // 4. Guardar en cache
    setCached(paradero, resultado);

    console.log(`✓ Paradero ${paradero} consultado exitosamente`);
    return {
      statusCode: 200,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Cache-Control': 'max-age=300' // 5 minutos
      },
      body: JSON.stringify(resultado)
    };

  } catch (err) {
    console.error(`✗ Error consultando ${paradero}:`, err.message);
    
    return {
      statusCode: 502,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
      body: JSON.stringify({
        error: `Error al consultar iBUS: ${err.message}`,
        retryable: true
      })
    };
  }
};
