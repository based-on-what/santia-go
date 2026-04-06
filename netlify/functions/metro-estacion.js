/**
 * Netlify Function: /api/metro/estacion?nombre=Baquedano
 *
 * Fuentes:
 *   - https://www.metro.cl/api/estadoRedDetalle.php   (estado de la red)
 *   - https://www.metro.cl/api/horariosEstacion.php   (horarios por estación)
 */

const HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
  'Accept-Language': 'es-CL,es;q=0.9',
};

const STATUS_API   = 'https://www.metro.cl/api/estadoRedDetalle.php';
const SCHEDULE_API = 'https://www.metro.cl/api/horariosEstacion.php';

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
    return { statusCode: 400, body: JSON.stringify({ error: 'Parámetro "nombre" requerido' }) };
  }

  try {
    // 1. Estado de la red
    const networkRes = await fetch(STATUS_API, { headers: HEADERS });
    if (!networkRes.ok) throw new Error(`estadoRedDetalle: ${networkRes.status}`);
    const networkData = await networkRes.json();

    // 2. Buscar estación por nombre
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
      return { statusCode: 404, body: JSON.stringify({ error: `Estación '${nombre}' no encontrada` }) };
    }

    // 3. Horarios de la estación
    const schedRes = await fetch(`${SCHEDULE_API}?cod=${found.codigo}`, { headers: HEADERS });
    const schedData = schedRes.ok ? await schedRes.json() : {};

    const est   = schedData.estacion || {};
    const tren  = schedData.tren     || {};
    const schedule = {
      open:  daySchedule(est.abrir  || {}),
      close: daySchedule(est.cerrar || {}),
    };

    // 4. Transfers
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

    return {
      statusCode: 200,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
      body: JSON.stringify(result),
    };

  } catch (err) {
    console.error('metro-estacion error:', err);
    return {
      statusCode: 502,
      body: JSON.stringify({ error: `Error obteniendo datos de metro: ${err.message}` }),
    };
  }
};
