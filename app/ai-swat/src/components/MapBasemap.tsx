import { useEffect, useRef, useState } from 'react';
import { TileLayer, useMap } from 'react-leaflet';
import L from 'leaflet';

export type BasemapLayer = 'satellite' | 'map';

// Street (OpenStreetMap) vs Satellite (Esri World Imagery). Both are free and need
// no API key. On satellite we overlay Esri place/road labels so towns & roads still
// read on top of the imagery (a "hybrid" view — the most useful for spotting fields).
const OSM_URL = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
const OSM_ATTR = '&copy; OpenStreetMap contributors';
const SAT_URL = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
const SAT_ATTR = 'Imagery &copy; Esri, Maxar, Earthstar Geographics';
const LABELS_URL = 'https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}';

// A basemap with a built-in Map/Satellite toggle. Drop-in replacement for a plain
// <TileLayer/> inside any <MapContainer>. Renders a small Leaflet control (top-right)
// so no parent state or wrapper markup is needed.
export function MapBasemap({ defaultLayer = 'satellite' }: { defaultLayer?: BasemapLayer }) {
  const [layer, setLayer] = useState<BasemapLayer>(defaultLayer);
  const map = useMap();
  const wrapRef = useRef<HTMLElement | null>(null);

  // Build the toggle control once and attach it to this map instance.
  useEffect(() => {
    const Ctl = L.Control.extend({
      options: { position: 'topright' as L.ControlPosition },
      onAdd() {
        const wrap = L.DomUtil.create('div', 'leaflet-bar map-basemap-toggle');
        wrap.style.cssText = 'display:flex;overflow:hidden;border-radius:6px;box-shadow:0 1px 4px rgba(0,0,0,.3);';
        const mk = (key: BasemapLayer, label: string) => {
          const b = L.DomUtil.create('a', '', wrap) as HTMLAnchorElement;
          b.href = '#';
          b.textContent = label;
          b.dataset.k = key;
          b.style.cssText = 'width:auto;height:auto;padding:4px 10px;line-height:16px;font:600 11px/16px system-ui,sans-serif;text-decoration:none;';
          L.DomEvent.on(b, 'click', (e: Event) => { L.DomEvent.stop(e); setLayer(key); });
          return b;
        };
        mk('map', 'Map');
        mk('satellite', 'Satellite');
        // keep clicks on the toggle from reaching the map (which would drop a draw point)
        L.DomEvent.disableClickPropagation(wrap);
        wrapRef.current = wrap;
        return wrap;
      },
    });
    const ctl = new Ctl();
    ctl.addTo(map);
    return () => { ctl.remove(); wrapRef.current = null; };
  }, [map]);

  // Reflect the active layer on the toggle buttons.
  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    wrap.querySelectorAll<HTMLElement>('a').forEach(a => {
      const active = a.dataset.k === layer;
      a.style.background = active ? '#0068C1' : '#fff';
      a.style.color = active ? '#fff' : '#333';
    });
  }, [layer]);

  if (layer === 'satellite') {
    return (
      <>
        <TileLayer url={SAT_URL} attribution={SAT_ATTR} maxNativeZoom={19} maxZoom={22} />
        <TileLayer url={LABELS_URL} maxNativeZoom={19} maxZoom={22} />
      </>
    );
  }
  return <TileLayer url={OSM_URL} attribution={OSM_ATTR} maxZoom={22} />;
}
