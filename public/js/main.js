/* ============================================================
   main.js — Explorador de Transporte Santiago
   ============================================================ */

/* ---------- CONFIG ---------- */
// Token inyectado desde index.html como window.MAPBOX_TOKEN
mapboxgl.accessToken = window.MAPBOX_TOKEN;

// Producción (Railway): rutas relativas /api/... → backend Python
// Desarrollo local: servidor Python en localhost:8000 (python -m uvicorn api:app --reload)
const API_BASE = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
  ? 'http://localhost:8000'
  : '/api';

const ROUTE_COLORS  = ['#FF0000', '#008000', '#0000FF'];

/* ── Metro line color palette (matches official Transantiago branding) ── */
const METRO_LINE_COLORS = {
  L1:  { bg: 'oklch(97% 0.035 25)',  fg: 'oklch(49% 0.24 25)'  },
  L2:  { bg: 'oklch(98% 0.055 82)',  fg: 'oklch(54% 0.22 75)'  },
  L3:  { bg: 'oklch(97% 0.035 52)',  fg: 'oklch(46% 0.18 52)'  },
  L4:  { bg: 'oklch(96% 0.035 230)', fg: 'oklch(41% 0.20 230)' },
  L4A: { bg: 'oklch(96% 0.030 245)', fg: 'oklch(38% 0.18 245)' },
  L5:  { bg: 'oklch(96% 0.035 145)', fg: 'oklch(43% 0.20 145)' },
  L6:  { bg: 'oklch(96% 0.035 305)', fg: 'oklch(42% 0.19 305)' },
};

/* ── Popup HTML constants ────────────────────────────────────────────── */
const LOADING_BUS_HTML = `
  <div class="popup-skeleton" aria-label="Cargando datos del paradero">
    <div class="skel skel--wide"></div>
    <div class="skel skel--short skel--sm"></div>
    <div class="skel skel--lg"></div>
    <div class="skel skel--lg"></div>
    <div class="skel skel--lg"></div>
  </div>`;

const LOADING_METRO_HTML = `
  <div class="popup-skeleton" aria-label="Cargando información de la estación">
    <div class="skel skel--mid"></div>
    <div class="skel skel--lg"></div>
    <div class="skel skel--wide"></div>
    <div class="skel skel--mid"></div>
    <div class="skel skel--short"></div>
  </div>`;

/* ── Shared utility (needs module scope for createErrorHtml) ── */
function escapeHtml(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function createErrorHtml(msg, detail = '') {
  return `<div class="popup-error">
    <span class="popup-error__icon" aria-hidden="true">!</span>
    <p class="popup-error__msg">${escapeHtml(msg)}</p>
    ${detail ? `<code class="popup-error__detail">${escapeHtml(detail)}</code>` : ''}
  </div>`;
}
const MAP_CENTER    = [-70.65, -33.45];
const CANDIDATE_POOL = 50; // candidatos pre-filtrados antes de haversine preciso

/* ---------- SINGLETON APP ---------- */
const App = (() => {

  /* ---- Estado global ---- */
  const state = {
    map: null,
    allMetroStations: [],
    allBusStops: [],
    metroGridIdx: null,
    busGridIdx: null,
    currentMarkers: [],
    currentRouteIds: [],
    referenceMarker: null,
    activeMarker: null,
    popupMoveHandlerKey: null,
    metroCoords: [],
    busCoords: []
  };

  /* ---- PubSub mínimo ---- */
  const events = {
    list: {},
    on(k, h)  { (this.list[k] = this.list[k] || []).push(h); },
    off(k, h) { if (!this.list[k]) return; this.list[k] = this.list[k].filter(fn => fn !== h); },
    emit(k, ...a) { (this.list[k] || []).forEach(fn => fn(...a)); }
  };

  /* ---- Utilidades de distancia ---- */

  function haversineDistance([lon1, lat1], [lon2, lat2]) {
    if (lon1 == null || lat1 == null || lon2 == null || lat2 == null) return Infinity;
    const R  = 6371e3;
    const φ1 = lat1 * Math.PI / 180;
    const φ2 = lat2 * Math.PI / 180;
    const Δφ = (lat2 - lat1) * Math.PI / 180;
    const Δλ = (lon2 - lon1) * Math.PI / 180;
    const a  = Math.sin(Δφ / 2) ** 2 + Math.cos(φ1) * Math.cos(φ2) * Math.sin(Δλ / 2) ** 2;
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  }

  // Aproximación rápida en grados (no usar para resultado final)
  function approxSqDist([lon1, lat1], [lon2, lat2]) {
    const dx = lon1 - lon2, dy = lat1 - lat2;
    return dx * dx + dy * dy;
  }

  // Encuentra los k más cercanos: pre-filtro por aprox → haversine en candidatos
  function findNearestPoints(points, coords, limit = 1) {
    if (!points || points.length === 0) return [];
    const approx = points
      .map((p, i) => ({ i, d: approxSqDist(coords, p.geometry.coordinates) }))
      .sort((a, b) => a.d - b.d)
      .slice(0, Math.min(CANDIDATE_POOL, points.length))
      .map(a => points[a.i]);
    return approx
      .map(p => ({ ...p, distance: haversineDistance(coords, p.geometry.coordinates) }))
      .sort((a, b) => a.distance - b.distance)
      .slice(0, limit);
  }

  // ---- Spatial grid index — O(1) nearest-neighbor on hot paths ----
  // cellSize 0.01° ≈ 1 km; radius 2 checks 5×5 cells (~25 km²) — always finds nearest stop.
  function buildSpatialGrid(points, cellSize = 0.01) {
    const grid = new Map();
    for (let i = 0; i < points.length; i++) {
      const [lon, lat] = points[i].geometry.coordinates;
      const key = `${Math.floor(lon / cellSize)},${Math.floor(lat / cellSize)}`;
      if (!grid.has(key)) grid.set(key, []);
      grid.get(key).push(i);
    }
    return { grid, cellSize, points };
  }

  function findNearestInGrid(gidx, coords, limit = 1, radius = 2) {
    const [lon, lat] = coords;
    const cx = Math.floor(lon / gidx.cellSize);
    const cy = Math.floor(lat / gidx.cellSize);
    const candidates = [];
    for (let dx = -radius; dx <= radius; dx++) {
      for (let dy = -radius; dy <= radius; dy++) {
        const bucket = gidx.grid.get(`${cx + dx},${cy + dy}`);
        if (bucket) for (const i of bucket) candidates.push(gidx.points[i]);
      }
    }
    if (!candidates.length) return [];
    return candidates
      .map(p => ({ ...p, distance: approxSqDist(coords, p.geometry.coordinates) }))
      .sort((a, b) => a.distance - b.distance)
      .slice(0, limit);
  }

  /* ---- Marcadores ---- */

  function createMarker({ coords, color }) {
    return new mapboxgl.Marker({ color }).setLngLat(coords).addTo(state.map);
  }

  /* ---- Popup ---- */

  const popupEl        = document.getElementById('custom-popup');
  const popupTitleEl   = document.getElementById('popup-title');
  const popupBadgeEl   = document.getElementById('popup-badge');
  const popupContentEl = document.getElementById('popup-content');
  const popupCloseBtn  = document.getElementById('popup-close');

  let _prevFocusEl = null;

  // Cached popup dimensions — avoid forced reflow on every map move/zoom
  let _cachedPopupSize = null; // { w, h }
  // Cached tooltip width — updated lazily, avoids reflow on every mousemove frame
  let _lastTooltipW = 120;
  // Per-station API cache — prevents duplicate fetches for the same station
  const _stationCache = new Map(); // name.toLowerCase() → { data, ts }
  const _STATION_TTL_MS = 300_000;

  popupCloseBtn.addEventListener('click', (ev) => { ev.stopPropagation(); closeCustomPopup(); });

  function closeCustomPopup() {
    popupEl.style.display = 'none';
    popupEl.removeAttribute('data-visible');
    _cachedPopupSize = null;
    if (state.popupMoveHandlerKey) {
      state.map.off('move', state.popupMoveHandlerKey);
      state.map.off('zoom', state.popupMoveHandlerKey);
      state.popupMoveHandlerKey = null;
    }
    state.activeMarker = null;
    if (_prevFocusEl) { try { _prevFocusEl.focus(); } catch (_) {} _prevFocusEl = null; }
    events.emit('popup:closed');
  }

  function repositionPopup(marker) {
    if (!marker || state.activeMarker !== marker || !_cachedPopupSize) return;
    try {
      const markerRect  = marker.getElement().getBoundingClientRect();
      const markerTipX  = markerRect.left + markerRect.width / 2;
      const markerTipY  = markerRect.bottom;
      const { w: popW, h: popH } = _cachedPopupSize;
      const mapContainer = document.getElementById('map-container');
      let left = markerTipX - popW / 2;
      let top  = markerTipY - popH;
      left = Math.max(10, Math.min(mapContainer.clientWidth - popW - 10, left));
      if (top < 10) {
        top = markerTipY + 15;
        popupEl.classList.add('popup-below');
      } else {
        popupEl.classList.remove('popup-below');
      }
      popupEl.style.left = `${left}px`;
      popupEl.style.top  = `${top}px`;
    } catch (err) {
      console.warn('repositionPopup error', err);
    }
  }

  function showCustomPopup(markerCoordinates, title, contentHtml, marker, type = 'bus') {
    _prevFocusEl              = document.activeElement;
    popupTitleEl.textContent  = title;
    popupContentEl.innerHTML  = contentHtml;
    popupBadgeEl.textContent  = type === 'metro' ? 'M' : 'P';
    popupBadgeEl.className    = `map-popup__type-badge map-popup__type-badge--${type}`;
    popupEl.style.display     = 'block';
    popupEl.setAttribute('data-visible', 'true');
    state.activeMarker        = marker;
    requestAnimationFrame(() => {
      const r = popupEl.getBoundingClientRect();
      _cachedPopupSize = { w: r.width, h: r.height };
      repositionPopup(marker);
      popupCloseBtn.focus();
    });

    const onMapMove = () => repositionPopup(marker);
    if (state.popupMoveHandlerKey) {
      state.map.off('move', state.popupMoveHandlerKey);
      state.map.off('zoom', state.popupMoveHandlerKey);
    }
    state.popupMoveHandlerKey = onMapMove;
    state.map.on('move', onMapMove);
    state.map.on('zoom', onMapMove);
  }

  function updatePopupContent(contentHtml, marker) {
    if (state.activeMarker === marker) {
      popupContentEl.innerHTML = contentHtml;
      requestAnimationFrame(() => {
        const r = popupEl.getBoundingClientRect();
        _cachedPopupSize = { w: r.width, h: r.height };
        repositionPopup(marker);
      });
    }
  }

  /* ---- Rutas caminando ---- */

  async function drawWalkingRoute(start, end, color) {
    if (!start || !end) return;
    const id = `route-${end[0].toFixed(5)}-${end[1].toFixed(5)}`.replace(/\./g, '-');
    try {
      if (state.map.getSource(id)) return; // ya existe
      const url = `https://api.mapbox.com/directions/v5/mapbox/walking/${start.join(',')};${end.join(',')}?geometries=geojson&access_token=${mapboxgl.accessToken}`;
      const res = await fetch(url);
      if (!res.ok) return;
      const data = await res.json();
      if (!data?.routes?.length) return;
      const geo = {
        type: 'FeatureCollection',
        features: [{ type: 'Feature', geometry: data.routes[0].geometry, properties: {} }]
      };
      state.map.addSource(id, { type: 'geojson', data: geo });
      state.map.addLayer({ id, type: 'line', source: id, paint: { 'line-color': color, 'line-width': 4, 'line-opacity': 0.7 } });
      state.currentRouteIds.push(id);
    } catch (err) {
      console.error('drawWalkingRoute', err);
    }
  }

  /* ---- Limpieza ---- */

  function clearPreviousElements() {
    state.currentMarkers.forEach(m => { try { m.remove(); } catch (e) {} });
    state.currentMarkers = [];

    state.currentRouteIds.forEach(id => {
      if (state.map.getLayer(id))  state.map.removeLayer(id);
      if (state.map.getSource(id)) state.map.removeSource(id);
    });
    state.currentRouteIds = [];

    if (state.map.getSource('connections')) {
      if (state.map.getLayer('connections')) state.map.removeLayer('connections');
      state.map.removeSource('connections');
    }

    if (state.referenceMarker) { try { state.referenceMarker.remove(); } catch (e) {} }
    state.referenceMarker = null;
    closeCustomPopup();
  }

  /* ---- Contenido de popups ---- */

  // Formato: { paradero, nombre, hora_consulta, servicios: [{servicio, bus, tiempo, distancia_metros}] }
  function createBusStopPopupContent(stopData) {
    const nombre = escapeHtml(stopData.nombre) || 'Nombre no disponible';
    let html = `<div class="stop-header">
      <div class="stop-header__name">${nombre}</div>
      ${stopData.hora_consulta ? `<div class="stop-header__ts">Actualizado: ${escapeHtml(stopData.hora_consulta)}</div>` : ''}
    </div>`;

    if (!stopData.servicios?.length) {
      return html + `<div class="popup-empty">
        <span class="popup-empty__icon" aria-hidden="true">—</span>
        <p class="popup-empty__msg">Sin información de servicios disponible</p>
      </div>`;
    }

    html += '<div class="service-list">';
    for (const svc of stopData.servicios) {
      const hasBus    = svc.bus != null;
      const distancia = svc.distancia_metros ?? svc.distancia ?? null;
      html += `<div class="service-card">
        <div class="service-card__head">
          <span class="route-badge">${escapeHtml(svc.servicio)}</span>
        </div>
        <div class="service-card__body">`;

      if (hasBus) {
        html += `<span class="bus-chip">${escapeHtml(svc.bus)}</span>
          <div class="service-metrics">
            <div class="service-metric">
              <span class="service-metric__val">${escapeHtml(svc.tiempo)}</span>
              <span class="service-metric__lbl">llegada</span>
            </div>
            ${distancia != null ? `<div class="service-metric">
              <span class="service-metric__val">${escapeHtml(String(distancia))}m</span>
              <span class="service-metric__lbl">distancia</span>
            </div>` : ''}
          </div>`;
      } else {
        html += `<span class="service-card__no-service">${escapeHtml(svc.tiempo)}</span>`;
      }

      html += '</div></div>';
    }
    html += '</div>';
    return html;
  }

  // Formato: { code, name, line_id, enabled, status_description, message,
  //            transfers, schedule: {open,close: {weekdays,saturday,holidays}},
  //            terminal_a, terminal_b: {name, first_train, last_train: {weekdays,...}} }
  function createMetroPopupContent(station) {
    if (!station) {
      return `<div class="popup-empty">
        <span class="popup-empty__icon" aria-hidden="true">—</span>
        <p class="popup-empty__msg">Sin información disponible</p>
      </div>`;
    }

    const fmt       = (v) => escapeHtml((v && v !== '-') ? v : '—');
    const statusOk  = !!station.enabled;
    const statusTxt = escapeHtml(station.status_description || (statusOk ? 'Operativa' : 'No habilitada'));
    const lines     = [station.line_id, ...(station.transfers || [])].filter(Boolean);

    const lineBadges = lines.map(l => {
      const c = METRO_LINE_COLORS[l] || { bg: 'var(--metro-bg)', fg: 'var(--metro-fg)' };
      return `<span class="line-badge" style="background:${c.bg};color:${c.fg}">${escapeHtml(l)}</span>`;
    }).join('');

    let html = `<div class="station-meta">
      ${lineBadges || '<span class="line-badge">—</span>'}
      <span class="status-badge status-badge--${statusOk ? 'ok' : 'err'}">${statusTxt}</span>
    </div>`;

    if (station.message) {
      html += `<div class="station-alert">${escapeHtml(station.message)}</div>`;
    }

    const sched = station.schedule;
    if (sched) {
      html += `<div class="schedule-block">
        <span class="schedule-block__title">Horario de apertura</span>
        <div class="schedule-row">
          <span class="schedule-row__day">L - V</span>
          <span class="schedule-row__range">
            ${fmt(sched.open?.weekdays)}<span class="schedule-row__dash">→</span>${fmt(sched.close?.weekdays)}
          </span>
        </div>
        <div class="schedule-row">
          <span class="schedule-row__day">Sábado</span>
          <span class="schedule-row__range">
            ${fmt(sched.open?.saturday)}<span class="schedule-row__dash">→</span>${fmt(sched.close?.saturday)}
          </span>
        </div>
        <div class="schedule-row">
          <span class="schedule-row__day">Dom / Fest</span>
          <span class="schedule-row__range">
            ${fmt(sched.open?.holidays)}<span class="schedule-row__dash">→</span>${fmt(sched.close?.holidays)}
          </span>
        </div>
      </div>`;
    }

    const renderTerminal = (t) => {
      if (!t) return '';
      return `<div class="terminal-block">
        <div class="terminal-block__name">${escapeHtml(t.name)}</div>
        <div class="terminal-row">
          <span class="terminal-row__label">Primer tren L-V</span>
          <span class="terminal-row__value">${fmt(t.first_train?.weekdays)}</span>
        </div>
        <div class="terminal-row">
          <span class="terminal-row__label">Último tren L-V</span>
          <span class="terminal-row__value">${fmt(t.last_train?.weekdays)}</span>
        </div>
      </div>`;
    };

    html += renderTerminal(station.terminal_a);
    html += renderTerminal(station.terminal_b);
    return html;
  }

  /* ---- Marcadores + rutas desde referencia ---- */

  function placeMarkersAndRoutes(refCoords) {
    clearPreviousElements();
    if (!state.allMetroStations.length || !state.allBusStops.length) return;

    const [nearestMetro]  = state.metroGridIdx ? findNearestInGrid(state.metroGridIdx, refCoords, 1) : findNearestPoints(state.allMetroStations, refCoords, 1);
    const nearestStops    = state.busGridIdx   ? findNearestInGrid(state.busGridIdx,   refCoords, 3) : findNearestPoints(state.allBusStops,      refCoords, 3);

    if (nearestMetro) {
      const marker = createMarker({ coords: nearestMetro.geometry.coordinates, color: '#8a2be2' });
      addMarkerClickHandler(marker, nearestMetro, true);
      state.currentMarkers.push(marker);
      drawWalkingRoute(refCoords, nearestMetro.geometry.coordinates, '#8a2be2');
    }

    nearestStops.forEach((stop, i) => {
      const marker = createMarker({ coords: stop.geometry.coordinates, color: ROUTE_COLORS[i] });
      addMarkerClickHandler(marker, stop, false);
      state.currentMarkers.push(marker);
      drawWalkingRoute(refCoords, stop.geometry.coordinates, ROUTE_COLORS[i]);
    });
  }

  function addMarkerClickHandler(marker, markerData, isMetro) {
    const el = marker.getElement();
    if (!el || el.__hasClick) return;
    el.__hasClick = true;
    el.addEventListener('click', async (e) => {
      e.stopPropagation();
      closeCustomPopup();
      const { lng, lat } = marker.getLngLat();

      if (isMetro) {
        const stationName = markerData.properties.name;
        const cacheKey    = stationName.toLowerCase();
        const hit         = _stationCache.get(cacheKey);
        if (hit && Date.now() - hit.ts < _STATION_TTL_MS) {
          showCustomPopup([lng, lat], stationName, createMetroPopupContent(hit.data), marker, 'metro');
        } else {
          showCustomPopup([lng, lat], stationName, LOADING_METRO_HTML, marker, 'metro');
          try {
            const nombre = encodeURIComponent(stationName);
            const res = await fetch(`${API_BASE}/metro/estacion?nombre=${nombre}`);
            if (res.ok) {
              const data = await res.json();
              _stationCache.set(cacheKey, { data, ts: Date.now() });
              updatePopupContent(createMetroPopupContent(data), marker);
            } else {
              updatePopupContent(createErrorHtml(`Error al obtener información de la estación (${res.status})`), marker);
            }
          } catch (err) {
            console.error('metro fetch error', err);
            updatePopupContent(createErrorHtml('No se pudo conectar al servidor.', 'uvicorn api:app --reload'), marker);
          }
        }
      } else {
        const stopId = markerData.properties.stop_id;
        showCustomPopup([lng, lat], `Paradero ${stopId}`, LOADING_BUS_HTML, marker, 'bus');
        try {
          const res = await fetch(`${API_BASE}/paradero/${stopId}`);
          if (res.ok) {
            const data = await res.json();
            updatePopupContent(createBusStopPopupContent(data), marker);
          } else if (res.status === 502) {
            const errBody = await res.json().catch(() => ({}));
            const isIbus  = ['ibus', 'iBUS', 'm.ibus.cl'].some(s => (errBody.detail || '').includes(s));
            const msg     = isIbus ? 'Servicio iBUS no disponible en este momento.' : `Error al obtener datos del paradero (${res.status})`;
            updatePopupContent(createErrorHtml(msg), marker);
          } else {
            updatePopupContent(createErrorHtml(`Error al obtener datos del paradero (${res.status})`), marker);
          }
        } catch (err) {
          console.error('bus fetch error', err);
          updatePopupContent(createErrorHtml('No se pudo conectar al servidor.', 'uvicorn api:app --reload'), marker);
        }
      }
    });
  }

  /* ---- Líneas de conexión + tooltip (throttled con rAF) ---- */

  const _priv = { lastPoint: null };

  function updateConnectionsAndTooltip(cursorLngLat, point) {
    if (!cursorLngLat) return;

    const loc = [cursorLngLat.lng, cursorLngLat.lat];
    const [nearestMetro] = state.metroGridIdx ? findNearestInGrid(state.metroGridIdx, loc, 1) : findNearestPoints(state.allMetroStations, loc, 1);
    const nearestStops   = state.busGridIdx   ? findNearestInGrid(state.busGridIdx,   loc, 3) : findNearestPoints(state.allBusStops,      loc, 3);

    const nearest = [];
    if (nearestMetro) nearest.push({ coord: nearestMetro.geometry.coordinates, color: '#8a2be2' });
    nearestStops.forEach((p, i) => nearest.push({ coord: p.geometry.coordinates, color: ROUTE_COLORS[i] }));

    const features = nearest.map(n => ({
      type: 'Feature',
      properties: { color: n.color },
      geometry: { type: 'LineString', coordinates: [[cursorLngLat.lng, cursorLngLat.lat], n.coord] }
    }));

    const geoData = { type: 'FeatureCollection', features };
    if (state.map.getSource('connections')) {
      state.map.getSource('connections').setData(geoData);
      if (!state.map.getLayer('connections')) {
        state.map.addLayer({ id: 'connections', type: 'line', source: 'connections', paint: { 'line-color': ['get', 'color'], 'line-width': 2, 'line-opacity': 0.8 } });
      }
    } else {
      state.map.addSource('connections', { type: 'geojson', data: geoData });
      state.map.addLayer({ id: 'connections', type: 'line', source: 'connections', paint: { 'line-color': ['get', 'color'], 'line-width': 2, 'line-opacity': 0.8 } });
    }

    const tooltip     = document.getElementById('tooltip');
    const mapContainer = document.getElementById('map-container');
    const mapRect     = mapContainer.getBoundingClientRect();
    // Set text before positioning; use cached width to avoid forced reflow on hot path
    tooltip.textContent = nearestMetro ? `Cerca: ${nearestMetro.properties.name}` : 'Cerca: —';
    const ttW = _lastTooltipW;
    const ttH = 20;
    let left  = point.x + 10;
    let top   = point.y + 10;
    if (left + ttW > mapRect.width)  left = point.x - ttW - 10;
    if (top  + ttH > mapRect.height) top  = point.y - ttH - 10;
    left = Math.max(0, Math.min(left, mapRect.width  - ttW));
    top  = Math.max(0, Math.min(top,  mapRect.height - ttH));
    tooltip.style.left    = `${left + mapRect.left}px`;
    tooltip.style.top     = `${top  + mapRect.top}px`;
    tooltip.style.display = 'block';
    // Refresh cached width lazily — no blocking reflow this frame
    requestAnimationFrame(() => { _lastTooltipW = tooltip.offsetWidth || _lastTooltipW; });
  }

  let rafPending = false;
  const MIN_MOVE_PX = 5;

  function onMouseMoveThrottled(e) {
    _priv.lastPoint = e.point;
    if (rafPending) return;
    rafPending = true;
    requestAnimationFrame(() => {
      rafPending = false;
      if (_priv.lastProcessed) {
        const dx = _priv.lastPoint.x - _priv.lastProcessed.x;
        const dy = _priv.lastPoint.y - _priv.lastProcessed.y;
        if (dx * dx + dy * dy < MIN_MOVE_PX * MIN_MOVE_PX) return;
      }
      _priv.lastProcessed = _priv.lastPoint;
      updateConnectionsAndTooltip(e.lngLat, _priv.lastPoint);
    });
  }

  /* ---- Inicialización ---- */

  async function initMap() {
    state.map = new mapboxgl.Map({
      container: 'map',
      style: 'mapbox://styles/mapbox/streets-v12',
      center: MAP_CENTER,
      zoom: 13
    });

    const loadingEl = document.getElementById('loading');

    state.map.on('load', async () => {
      try {
        const [mRes, pRes] = await Promise.all([
          fetch('./data/estaciones_with_lines.geojson'),
          fetch('./data/paraderos_santiago.geojson')
        ]);

        if (!mRes.ok) throw new Error(`No se pudo cargar estaciones (${mRes.status})`);
        if (!pRes.ok) throw new Error(`No se pudo cargar paraderos (${pRes.status})`);

        const metrosJson    = await mRes.json();
        const paraderosJson = await pRes.json();

        state.allMetroStations = metrosJson.features    || [];
        state.allBusStops      = paraderosJson.features || [];
        state.metroGridIdx     = buildSpatialGrid(state.allMetroStations);
        state.busGridIdx       = buildSpatialGrid(state.allBusStops);

        if (!state.allMetroStations.length) console.warn('estaciones_with_lines.geojson: sin features');
        if (!state.allBusStops.length)      console.warn('paraderos_santiago.geojson: sin features');

        loadingEl.style.display = 'none';

        state.map.on('mousemove', onMouseMoveThrottled);

        state.map.on('click', (e) => {
          if (state.referenceMarker) {
            clearPreviousElements();
          } else {
            const coords = [e.lngLat.lng, e.lngLat.lat];
            state.referenceMarker = new mapboxgl.Marker({ color: 'black', scale: 1.2 })
              .setLngLat(coords)
              .addTo(state.map);
            placeMarkersAndRoutes(coords);
          }
        });

        state.map.getCanvasContainer().addEventListener('click', () => closeCustomPopup());

      } catch (err) {
        console.error('Error cargando datos:', err);
        loadingEl.innerHTML = `<div style="padding:20px"><p>Error al cargar datos de transporte.</p><p style="font-size:0.85em;opacity:0.8">${err.message}</p></div>`;
      }
    });
  }

  return {
    init: initMap,
    _events: events,
    _state: state
  };
})();

App.init();

/* Escape closes popup; Tab keeps focus inside while open */
document.addEventListener('keydown', (e) => {
  const popup = document.getElementById('custom-popup');
  if (!popup.dataset.visible) return;
  if (e.key === 'Escape') {
    e.preventDefault();
    App._events.emit('popup:close-requested');
    document.getElementById('popup-close').click();
    return;
  }
  if (e.key === 'Tab') {
    const focusable = Array.from(
      popup.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')
    ).filter(el => !el.disabled && el.offsetParent !== null);
    if (!focusable.length) return;
    const first = focusable[0];
    const last  = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault(); last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault(); first.focus();
    }
  }
});
