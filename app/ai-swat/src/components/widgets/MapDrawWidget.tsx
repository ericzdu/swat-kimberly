import { useEffect, useState } from 'react';
import { MapContainer } from 'react-leaflet';
import type { LatLngExpression } from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { data, gis } from '@/lib/api';
import { MapBasemap } from '@/components/MapBasemap';
import { MapDrawHandler, MapInitialBounds } from '@/components/MapDrawHandler';
import { MapFlyTo, type MapFlyTarget } from '@/components/MapFlyTo';
import { Search, Pencil, Trash2, Save, Loader2 } from 'lucide-react';
import clsx from 'clsx';
import type { Widget } from '@/lib/widgets';

interface MapDrawPayload {
  mode?: string;
  searchHint?: string;
  allowDownload?: boolean;
}

// Reuses the exact map/draw/geocode/saveBoundary flow from the GIS page, packaged
// as a canvas widget. On save it persists the boundary, then hands control back to
// the agent (which downloads data + builds the model) via /api/interact.
export default function MapDrawWidget({ widget, onSubmit, disabled, farmId }: {
  widget: Widget;
  onSubmit: (w: Widget, data: Record<string, unknown>) => void;
  disabled?: boolean;
  farmId: string;
}) {
  const p = widget.payload as MapDrawPayload;
  const [drawing, setDrawing] = useState(true);
  const [drawPoints, setDrawPoints] = useState<LatLngExpression[]>([]);
  const [mapQuery, setMapQuery] = useState(p.searchHint || '');
  const [searching, setSearching] = useState(false);
  const [flyTarget, setFlyTarget] = useState<MapFlyTarget | null>(null);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState('');

  const runSearch = async (q: string) => {
    if (!q.trim()) return;
    setSearching(true);
    setStatus('');
    try {
      const res = await gis.geocode(q.trim());
      const r = res.results?.[0];
      if (r) {
        setFlyTarget({ lat: r.lat, lng: r.lon, zoom: 15, label: r.label });
        setStatus(`Centered on ${r.label}`);
      } else {
        setStatus(res.error || 'No place found. Try a city or "lat, lon".');
      }
    } catch {
      setStatus('Search failed.');
    } finally {
      setSearching(false);
    }
  };

  // Auto-center on the AI's suggested location.
  useEffect(() => {
    if (p.searchHint) runSearch(p.searchHint);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const save = async () => {
    if (drawPoints.length < 3) {
      setStatus('Click at least 3 corners of your field on the map.');
      return;
    }
    if (!farmId) {
      setStatus('No field selected.');
      return;
    }
    setSaving(true);
    setStatus('Saving boundary…');
    try {
      const ring = drawPoints.map(pt => {
        const c = pt as [number, number];
        return [c[1], c[0]];
      });
      ring.push(ring[0]);
      const geojson: GeoJSON.FeatureCollection = {
        type: 'FeatureCollection',
        features: [{ type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [ring] } }],
      };
      const res = await data.saveBoundary(farmId, geojson);
      onSubmit(widget, { saved: true, area_ha: res.area_ha ?? null });
    } catch (e) {
      setStatus('Could not save: ' + (e instanceof Error ? e.message : 'unknown error'));
      setSaving(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <div className="flex-1 flex items-center gap-1.5 bg-white border border-[var(--se-border)] rounded-lg px-2.5 focus-within:border-[var(--se-accent)]">
          <Search className="w-3.5 h-3.5 text-[var(--se-text-fnt)] shrink-0" />
          <input
            type="text"
            className="flex-1 min-w-0 bg-transparent py-2 text-xs text-[var(--se-text)] placeholder:text-[var(--se-text-fnt)] focus:outline-none"
            placeholder="City, address, or lat, lon"
            value={mapQuery}
            onChange={e => setMapQuery(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') runSearch(mapQuery); }}
          />
        </div>
        <button
          onClick={() => runSearch(mapQuery)}
          disabled={searching || !mapQuery.trim()}
          className="shrink-0 px-3 rounded-lg bg-[var(--se-rail)] hover:bg-[var(--se-border-lt)] border border-[var(--se-border)] text-[var(--se-text)] disabled:opacity-40 text-xs"
        >
          {searching ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Go'}
        </button>
      </div>

      <div className="rounded-lg overflow-hidden border border-[var(--se-border)] shadow-sm" style={{ height: 'clamp(400px, 60vh, 700px)' }}>
        <MapContainer center={[39.8, -98.5]} zoom={4} maxZoom={19} style={{ height: '100%', width: '100%' }}>
          <MapBasemap defaultLayer="satellite" />
          <MapInitialBounds bounds={null} />
          <MapDrawHandler drawing={drawing} points={drawPoints} onAddPoint={(lat, lng) => setDrawPoints(pts => [...pts, [lat, lng]])} />
          <MapFlyTo target={flyTarget} />
        </MapContainer>
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => setDrawing(d => !d)}
          className={clsx('flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg border',
            drawing
              ? 'border-[var(--se-accent-bd)] text-[var(--se-accent)] bg-[var(--se-accent-sf)]'
              : 'border-[var(--se-border)] text-[var(--se-text-mut)] hover:bg-[var(--se-rail)]')}
        >
          <Pencil className="w-3 h-3" /> {drawing ? 'Drawing…' : 'Draw'}
        </button>
        <button
          onClick={() => setDrawPoints(pts => pts.slice(0, -1))}
          disabled={!drawPoints.length}
          className="text-xs px-3 py-1.5 rounded-lg border border-[var(--se-border)] text-[var(--se-text-mut)] hover:bg-[var(--se-rail)] disabled:opacity-40"
        >
          Undo
        </button>
        <button
          onClick={() => setDrawPoints([])}
          className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg border border-[var(--se-border)] text-[var(--se-text-mut)] hover:bg-[var(--se-rail)]"
        >
          <Trash2 className="w-3 h-3" /> Clear
        </button>
        <span className="text-[11px] text-[var(--se-text-fnt)] self-center ml-auto">{drawPoints.length} corner(s)</span>
      </div>

      <button
        onClick={save}
        disabled={disabled || saving || drawPoints.length < 3}
        className="w-full flex items-center justify-center gap-2 bg-[var(--se-accent)] hover:bg-[var(--se-accent-h)] text-white disabled:opacity-40 rounded-lg py-2.5 text-sm font-medium shadow-sm"
      >
        {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
        {widget.submit?.label || 'Save boundary'}
      </button>

      {status && <p className="text-[11px] text-[var(--se-text-mut)]">{status}</p>}
    </div>
  );
}
