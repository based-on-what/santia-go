/**
 * Cloudflare Worker — proxy para red.cl (basado en muZk/red-api)
 *
 * Deploy rápido (sin instalar nada):
 *   1. Entra a dash.cloudflare.com → Workers & Pages → Create Worker
 *   2. Pega este archivo completo en el editor web y haz Deploy
 *   3. Copia la URL resultante (ej: https://red-proxy.TU_USUARIO.workers.dev)
 *   4. En Railway → Variables: RED_API_URL=https://red-proxy.TU_USUARIO.workers.dev
 *
 * Deploy con Wrangler CLI:
 *   wrangler deploy red-worker.js --name red-proxy --compatibility-date 2024-01-01
 *
 * Endpoint expuesto:
 *   GET /stops/:stopId/next_arrivals
 */

// ── Serialización (lógica de muZk/red-api) ────────────────────────────────────

function getRouteInfo(data, key) {
  return {
    bus_distance:      data[`distanciabus${key}`],
    arrival_estimation: data[`horaprediccionbus${key}`],
    bus_plate_number:  data[`ppubus${key}`],
    route_id:          data['servicio'],
    code:              data['codigorespuesta'],
    message:           data['respuestaServicio'],
  }
}

function singleRouteInfo(data)   { return [getRouteInfo(data, '1')] }
function multipleRouteInfo(data) { return [getRouteInfo(data, '1'), getRouteInfo(data, '2')] }

function routeFrequencyInfo(data) {
  return [{
    bus_distance:      null,
    arrival_estimation: data['respuestaServicio'],
    bus_plate_number:  null,
    route_id:          data['servicio'],
    code:              data['codigorespuesta'],
    message:           data['respuestaServicio'],
  }]
}

function withoutInfo(data, message) {
  return [{
    bus_distance:      null,
    arrival_estimation: null,
    bus_plate_number:  null,
    route_id:          data['servicio'],
    code:              data['codigorespuesta'],
    message,
  }]
}

function noRoutesInfo(data)        { return withoutInfo(data, 'No hay buses que se dirijan al paradero') }
function closedStopInfo(data)      { return withoutInfo(data, 'Servicio fuera de horario de operacion para ese paradero') }
function notAvailableService(data) { return withoutInfo(data, 'Servicio no disponible') }

const SERIALIZER_MAP = {
  '00': multipleRouteInfo,
  '01': singleRouteInfo,
  '9':  routeFrequencyInfo,
  '10': noRoutesInfo,
  '11': closedStopInfo,
  '12': notAvailableService,
}

const RESPONSE_PRIORITY = ['00', '01', '9', '10', '11', '12']

function serialize(inputData) {
  const calculatedAt = `${inputData['fechaprediccion']} ${inputData['horaprediccion']}`

  let items = inputData['servicios']['item']
  if (!Array.isArray(items)) items = [items]

  const responseItems = {}
  items.forEach(serviceItem => {
    const code = serviceItem['codigorespuesta']
    if (SERIALIZER_MAP[code]) {
      if (!responseItems[code]) responseItems[code] = []
      responseItems[code].push(...SERIALIZER_MAP[code](serviceItem))
    }
  })

  const results = []
  RESPONSE_PRIORITY.forEach(code => {
    const bucket = responseItems[code]
    if (!bucket) return
    bucket.forEach(item => {
      item['calculated_at'] = calculatedAt
      item['arrival_estimation'] = item['arrival_estimation'] || item['message']
      item['is_live'] = ['00', '01', '9', '09', '10', '11', '12'].includes(item['code'])
    })
    results.push(...bucket.filter(item => item['is_live']))
  })

  return { results }
}

// ── red.cl helpers ────────────────────────────────────────────────────────────

const BROWSER_HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
  'Accept-Language': 'es-CL,es;q=0.9',
}

async function getTokenAndCookies() {
  const response = await fetch('https://www.red.cl/planifica-tu-viaje/cuando-llega/', {
    headers: {
      ...BROWSER_HEADERS,
      'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    }
  })

  if (!response.ok) {
    throw new Error(`red.cl devolvió ${response.status} al obtener la página del token`)
  }

  // Extraer cookies de sesión para reenviarlas al predictor
  const cookies = []
  for (const [key, value] of response.headers.entries()) {
    if (key.toLowerCase() === 'set-cookie') {
      cookies.push(value.split(';')[0]) // solo name=value
    }
  }

  const text = await response.text()
  const regex = /\$jwt\s=\s'([^']+)'/
  const match = regex.exec(text)
  if (!match) {
    throw new Error('Token JWT no encontrado en red.cl')
  }

  const token = atob(match[1])
  return { token, cookieHeader: cookies.join('; ') }
}

async function getArrivalData(token, cookieHeader, stopId) {
  const headers = {
    ...BROWSER_HEADERS,
    'Accept': 'application/json, text/plain, */*',
    'Referer': 'https://www.red.cl/planifica-tu-viaje/cuando-llega/',
  }
  if (cookieHeader) headers['Cookie'] = cookieHeader

  const response = await fetch(
    `https://www.red.cl/predictor/prediccion?t=${token}&codsimt=${stopId}&codser=`,
    { headers }
  )

  if (!response.ok) {
    const body = await response.text()
    throw new Error(`Predictor red.cl devolvió ${response.status}: ${body.slice(0, 150)}`)
  }

  const data = await response.json()
  return serialize(data)
}

// ── Router ────────────────────────────────────────────────────────────────────

function corsHeaders() {
  return {
    'Access-Control-Allow-Origin':  '*',
    'Access-Control-Allow-Methods': 'GET, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  }
}

addEventListener('fetch', event => {
  event.respondWith(handleRequest(event.request))
})

async function handleRequest(request) {
  const url = new URL(request.url)
  const { pathname } = url

  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: corsHeaders() })
  }

  if (pathname === '/') {
    return new Response('red-proxy ok', { status: 200, headers: corsHeaders() })
  }

  // GET /stops/:stopId/next_arrivals
  const match = pathname.match(/^\/stops\/([^/]+)\/next_arrivals$/)
  if (request.method === 'GET' && match) {
    try {
      const stopId = match[1].toUpperCase()
      const { token, cookieHeader } = await getTokenAndCookies()
      const data = await getArrivalData(token, cookieHeader, stopId)
      return new Response(JSON.stringify(data), {
        status: 200,
        headers: { ...corsHeaders(), 'Content-Type': 'application/json' },
      })
    } catch (err) {
      return new Response(
        JSON.stringify({ error: 'Error al consultar red.cl', detail: err.message }),
        { status: 502, headers: { ...corsHeaders(), 'Content-Type': 'application/json' } }
      )
    }
  }

  return new Response('404 Not Found', { status: 404, headers: corsHeaders() })
}
