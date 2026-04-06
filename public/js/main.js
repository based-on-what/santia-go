/* ============================================================
   main.js — Explorador de Transporte Santiago
   ============================================================ */

/* ---------- CONFIG ---------- */
// Token inyectado desde index.html como window.MAPBOX_TOKEN
mapboxgl.accessToken = window.MAPBOX_TOKEN;

// URL base de la API local Python.
// Desarrollo local: levantar con `uvicorn api:app --reload` desde tools/python/
// Producción: cambiar a la URL de tu API desplegada
const API_BASE = 'http://localhost:8000';

const ROUTE_COLORS  = ['#FF0000', '#008000', '#0000FF'];
const MAP_CENTER    = [-70.65, -33.45];
const CANDIDATE_POOL = 50; // candidatos pre-filtrados antes de haversine preciso

/* ---------- SINGLETON APP ---------- */
const App = (() => {

  /* ---- Estado global ---- */
  const state = {
    map: null,
    allMetroStations: [],
    allBusStops: [],
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

  /* ---- Marcadores ---- */

  function createMarker({ coords, color }) {
    return new mapboxgl.Marker({ color }).setLngLat(coords).addTo(state.map);
  }

  /* ---- Popup ---- */

  const popupEl       = document.getElementById('custom-popup');
  const popupTitleEl  = document.getElementById('popup-title');
  const popupContentEl = document.getElementById('popup-content');
  const popupCloseBtn  = document.getElementById('popup-close');

  popupCloseBtn.addEventListener('click', (ev) => { ev.stopPropagation(); closeCustomPopup(); });

  function closeCustomPopup() {
    popupEl.style.display = 'none';
    if (state.popupMoveHandlerKey) {
      state.map.off('move', state.popupMoveHandlerKey);
      state.map.off('zoom', state.popupMoveHandlerKey);
      state.popupMoveHandlerKey = null;
    }
    state.activeMarker = null;
    events.emit('popup:closed');
  }

  function repositionPopup(marker) {
    if (!marker || state.activeMarker !== marker) return;
    try {
      const markerRect  = marker.getElement().getBoundingClientRect();
      const markerTipX  = markerRect.left + markerRect.width / 2;
      const markerTipY  = markerRect.bottom;
      popupEl.offsetHeight; // force reflow
      const popupRect   = popupEl.getBoundingClientRect();
      const mapContainer = document.getElementById('map-container');
      let left = markerTipX - popupRect.width / 2;
      let top  = markerTipY - popupRect.height;
      left = Math.max(10, Math.min(mapContainer.clientWidth - popupRect.width - 10, left));
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

  function showCustomPopup(markerCoordinates, title, contentHtml, marker) {
    popupTitleEl.textContent  = title;
    popupContentEl.innerHTML  = contentHtml;
    popupEl.style.display     = 'block';
    state.activeMarker        = marker;
    repositionPopup(marker);
    setTimeout(() => repositionPopup(marker), 60);

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
      setTimeout(() => repositionPopup(marker), 0);
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

  // Formato local: { paradero, nombre, hora_consulta, servicios: [{servicio, bus, tiempo, distancia_metros}] }
  function createBusStopPopupContent(stopData) {
    let html = `<div style="margin-bottom:10px"><strong>${stopData.nombre || 'Nombre no disponible'}</strong></div>`;
    if (stopData.hora_consulta) {
      html += `<div style="font-size:0.8em;color:#999;margin-bottom:8px">🕐 Consulta: ${stopData.hora_consulta}</div>`;
    }
    if (stopData.servicios?.length) {
      for (const svc of stopData.servicios) {
        const hasBus  = svc.bus != null;
        const color   = hasBus ? '#28a745' : '#dc3545';
        html += `<div style="margin-bottom:8px;padding:8px;background:#f8f8f8;border-radius:4px">
          <div style="color:${color};font-weight:600">Recorrido ${svc.servicio}</div>`;
        if (hasBus) {
          html += `<div style="font-size:0.85em;margin-top:4px">
            🚌 <strong>${svc.bus}</strong><br>
            ⏱ ${svc.tiempo}${svc.distancia_metros ? ` — ${svc.distancia_metros}m` : ''}
          </div>`;
        } else {
          html += `<div style="font-size:0.85em;color:#666;margin-top:4px">${svc.tiempo}</div>`;
        }
        html += '</div>';
      }
    } else {
      html += '<div>No hay información de servicios disponible</div>';
    }
    return html;
  }

  // Formato local: { code, name, line_id, line_name, enabled, status_description, message,
  //                   transfers, schedule: {open,close: {weekdays,saturday,holidays}},
  //                   terminal_a, terminal_b: {name, first_train, last_train: {weekdays,...}} }
  function createMetroPopupContent(station) {
    if (!station) return '<div>No hay información disponible</div>';

    const statusColor = station.enabled ? '#28a745' : '#dc3545';
    const statusText  = station.status_description || (station.enabled ? 'Operativa' : 'No habilitada');
    const allLines    = [station.line_id, ...(station.transfers || [])].join(', ');
    const sched       = station.schedule;

    const fmt = (val) => (val && val !== '-') ? val : '—';

    let html = `
      <div>
        <div style="color:${statusColor};font-weight:bold;margin-bottom:4px">
          Líneas: ${allLines || '—'}
        </div>
        <div style="color:${statusColor};margin-bottom:4px">${statusText}</div>
        ${station.message ? `<div style="font-size:0.82em;color:#888;margin-bottom:6px">${station.message}</div>` : ''}`;

    if (sched) {
      html += `
        <div style="margin-top:6px;font-size:0.85em;border-top:1px solid #eee;padding-top:6px">
          <strong>Horario de apertura</strong><br>
          <span style="color:#555">L-V:</span> ${fmt(sched.open?.weekdays)} → ${fmt(sched.close?.weekdays)}<br>
          <span style="color:#555">Sáb:</span> ${fmt(sched.open?.saturday)} → ${fmt(sched.close?.saturday)}<br>
          <span style="color:#555">Dom/Fest:</span> ${fmt(sched.open?.holidays)} → ${fmt(sched.close?.holidays)}
        </div>`;
    }

    const renderTerminal = (t) => {
      if (!t) return '';
      return `
        <div style="margin-top:6px;font-size:0.82em;border-top:1px solid #eee;padding-top:6px">
          <strong>→ ${t.name}</strong><br>
          Primer tren (L-V): ${fmt(t.first_train?.weekdays)}<br>
          Último tren (L-V): ${fmt(t.last_train?.weekdays)}
        </div>`;
    };
    html += renderTerminal(station.terminal_a);
    html += renderTerminal(station.terminal_b);
    html += '</div>';
    return html;
  }

  /* ---- Marcadores + rutas desde referencia ---- */

  function placeMarkersAndRoutes(refCoords) {
    clearPreviousElements();
    if (!state.allMetroStations.length || !state.allBusStops.length) return;

    const [nearestMetro]  = findNearestPoints(state.allMetroStations, refCoords, 1);
    const nearestStops    = findNearestPoints(state.allBusStops, refCoords, 3);

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
        showCustomPopup(
          [lng, lat],
          `🚇 ${markerData.properties.name}`,
          '<div class="loading-content"><div class="loading-spinner"></div><p>Cargando información de la estación...</p></div>',
          marker
        );
        try {
          const nombre = encodeURIComponent(markerData.properties.name);
          const res = await fetch(`${API_BASE}/metro/estacion?nombre=${nombre}`);
          if (res.ok) {
            const data = await res.json();
            updatePopupContent(createMetroPopupContent(data), marker);
          } else {
            updatePopupContent(`<div>Error al obtener información de metro (${res.status})</div>`, marker);
          }
        } catch (err) {
          console.error('metro fetch error', err);
          updatePopupContent('<div>Error: ¿está corriendo el servidor Python?</div>', marker);
        }
      } else {
        showCustomPopup(
          [lng, lat],
          `🚌 ${markerData.properties.stop_id}`,
          '<div class="loading-content"><div class="loading-spinner"></div><p>Cargando datos en tiempo real...</p></div>',
          marker
        );
        try {
          const res = await fetch(`${API_BASE}/paradero/${markerData.properties.stop_id}`);
          if (res.ok) {
            const data = await res.json();
            updatePopupContent(createBusStopPopupContent(data), marker);
          } else {
            updatePopupContent(`<div>Error al obtener datos de paradero (${res.status})</div>`, marker);
          }
        } catch (err) {
          console.error('bus fetch error', err);
          updatePopupContent('<div>Error: ¿está corriendo el servidor Python? (uvicorn api:app)</div>', marker);
        }
      }
    });
  }

  /* ---- Líneas de conexión + tooltip (throttled con rAF) ---- */

  const _priv = { lastPoint: null };

  function updateConnectionsAndTooltip(cursorLngLat, point) {
    if (!cursorLngLat) return;

    const [nearestMetro] = findNearestPoints(state.allMetroStations, [cursorLngLat.lng, cursorLngLat.lat], 1);
    const nearestStops   = findNearestPoints(state.allBusStops,      [cursorLngLat.lng, cursorLngLat.lat], 3);

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
    const ttW = tooltip.offsetWidth  || 120;
    const ttH = tooltip.offsetHeight || 20;
    let left  = point.x + 10;
    let top   = point.y + 10;
    if (left + ttW > mapRect.width)  left = point.x - ttW - 10;
    if (top  + ttH > mapRect.height) top  = point.y - ttH - 10;
    left = Math.max(0, Math.min(left, mapRect.width  - ttW));
    top  = Math.max(0, Math.min(top,  mapRect.height - ttH));
    tooltip.style.left    = `${left + mapRect.left}px`;
    tooltip.style.top     = `${top  + mapRect.top}px`;
    tooltip.style.display = 'block';
    tooltip.textContent   = nearestMetro ? `Cerca: ${nearestMetro.properties.name}` : 'Cerca: —';
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
