/**
 * Netlify Function: /api/metro/estacion?nombre=Baquedano
 *
 * Fuentes:
 *   - https://www.metro.cl/api/estadoRedDetalle.php   (estado de la red)
 *   - https://www.metro.cl/api/horariosEstacion.php   (horarios por estación)
 *
 * Con caching y manejo de errores robusto
 */

const fetch = require('node-fetch');

const HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
  'Accept-Language': 'es-CL,es;q=0.9',
};

const STATUS_API   = 'https://www.metro.cl/api/estadoRedDetalle.php';
const SCHEDULE_API = 'https://www.metro.cl/api/horariosEstacion.php';

// Cache en memoria (10 minutos para metro, cambios son lentos)
const CACHE = new Map();
const CACHE_TTL = 10 * 60 * 1000;

function getCacheKey(nombre) {
  return `estacion:${nombre.toLowerCase()}`;
}

function getCached(nombre) {
  const key = getCacheKey(nombre);
  const cached = CACHE.get(key);
  
  if (!cached) return null;
  if (Date.now() - cached.timestamp > CACHE_TTL) {
    CACHE.delete(key);
    return null;
  }
  
  return cached.data;
}

function setCached(nombre, data) {
  const key = getCacheKey(nombre);
  CACHE.set(key, { data, timestamp: Date.now() });
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 8000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  
  try {
    const res = await fetch(url, { ...options, signal: controller.signal });
    clearTimeout(timeout);
    return res;
  } catch (err) {
    clearTimeout(timeout);
    throw err;
  }
}

function daySchedule(raw = {}) {
  return {
    weekdays: raw.lunes_viernes?.trim() || '-',
    saturday: raw.sabado?.trim()        || '-',
    holidays: raw.domingo?.trim()       || '-',
  };
}

function trainTimes(raw) {
  if (!raw) return null;
  return {
    name:        raw.nombre?.trim() || '',
    first_train: daySchedule(raw.primer_tren),
    last_train:  daySchedule(raw.ultimo_tren),
  };
}

exports.handler = async (event) => {
  const nombre = event.queryStringParameters?.nombre?.trim();
  if (!nombre) {
    return {
      statusCode: 400,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ error: 'Parámetro "nombre" requerido' })
    };
  }

  try {
    // 1. Intentar obtener del cache
    const cached = getCached(nombre);
    if (cached) {
      console.log(`✓ Estación ${nombre} obtenida del cache`);
      return {
        statusCode: 200,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*',
          'Cache-Control': 'max-age=120'
        },
        body: JSON.stringify({ ...cached, cached: true })
      };
    }

    console.log(`→ Consultando API de Metro para estación ${nombre}`);

    // 2. Estado de la red
    const networkRes = await fetchWithTimeout(STATUS_API, { headers: HEADERS });
    if (!networkRes.ok) throw new Error(`estadoRedDetalle: ${networkRes.status}`);
    const networkData = await networkRes.json();

    // 3. Buscar estación por nombre
    let found = null;
    let lineId = null;
    let lineName = null;

    for (const [key, lineData] of Object.entries(networkData)) {
      const id     = key.toUpperCase();          // "L1", "L4A", etc.
      const suffix = id.slice(1);                // "1", "4A", etc.
      for (const st of lineData.estaciones || []) {
        if (st.nombre?.toLowerCase() === nombre.toLowerCase()) {
          found    = st;
          lineId   = id;
          lineName = `Línea ${suffix}`;
          break;
        }
      }
      if (found) break;
    }

    if (!found) {
      return {
        statusCode: 404,
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
        body: JSON.stringify({ error: `Estación '${nombre}' no encontrada` })
      };
    }

    // 4. Horarios de la estación
    let schedData = {};
    try {
      const schedRes = await fetchWithTimeout(`${SCHEDULE_API}?cod=${found.codigo}`, { headers: HEADERS });
      if (schedRes.ok) {
        schedData = await schedRes.json();
      }
    } catch (err) {
      console.warn(`⚠ No pudieron obtener horarios: ${err.message}`);
      // Continuar sin horarios
    }

    const est   = schedData.estacion || {};
    const tren  = schedData.tren     || {};
    const schedule = {
      open:  daySchedule(est.abrir  || {}),
      close: daySchedule(est.cerrar || {}),
    };

    // 5. Transfers
    const transfers = (found.combinacion || '')
      .split(',').map(t => t.trim()).filter(Boolean);

    const result = {
      code:               found.codigo,
      name:               found.nombre,
      line_id:            lineId,
      line_name:          lineName,
      enabled:            String(found.estado) === '1',
      status_description: (found.descripcion || '').trim(),
      message:            (found.mensaje      || '').trim(),
      transfers,
      schedule,
      terminal_a: trainTimes(tren.estacion_a),
      terminal_b: trainTimes(tren.estacion_b),
    };

    // Guardar en cache
    setCached(nombre, result);

    console.log(`✓ Estación ${nombre} consultada exitosamente`);
    return {
      statusCode: 200,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Cache-Control': 'max-age=600' // 10 minutos
      },
      body: JSON.stringify(result),
    };

  } catch (err) {
    console.error(`✗ Error consultando ${nombre}:`, err.message);
    return {
      statusCode: 502,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
      body: JSON.stringify({
        error: `Error obteniendo datos de metro: ${err.message}`,
        retryable: true
      }),
    };
  }
};
