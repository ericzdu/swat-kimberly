import { useCallback, useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { MapContainer, GeoJSON } from 'react-leaflet';
import type { LatLngExpression } from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { data, farms, gis, type Farm } from '@/lib/api';
import { MapBasemap } from '@/components/MapBasemap';
import { MapDrawHandler, MapInitialBounds } from '@/components/MapDrawHandler';
import { MapFlyTo, type MapFlyTarget } from '@/components/MapFlyTo';
import {
  Upload, Loader2, MapPin, Layers, Download, Settings2, Pencil, Trash2, CloudDownload, Save, Search,
} from 'lucide-react';
import clsx from 'clsx';

export default function GIS() {
  const [searchParams] = useSearchParams();
  const farmId = searchParams.get('farm') || '';
  const [farm, setFarm] = useState<Farm | null>(null);
  const [mode, setMode] = useState<'simple' | 'advanced'>('simple');
  const [demFile, setDemFile] = useState<File | null>(null);
  const [soilFile, setSoilFile] = useState<File | null>(null);
  const [luFile, setLuFile] = useState<File | null>(null);
  const [watershedFile, setWatershedFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState('');
  const [geoJsonData, setGeoJsonData] = useState<unknown>(null);
  const [hruCount, setHruCount] = useState(0);
  const [luThreshold, setLuThreshold] = useState(1.0);
  const [soilThreshold, setSoilThreshold] = useState(1.0);
  const [slopeClasses, setSlopeClasses] = useState('0,2,1\n2,5,2\n5,10,3\n10,999,4');
  const [outputPath, setOutputPath] = useState('');
  const [mapCenter] = useState<[number, number]>([39.8, -98.5]);
  const [drawing, setDrawing] = useState(false);
  const [drawPoints, setDrawPoints] = useState<LatLngExpression[]>([]);
  const [hasBoundary, setHasBoundary] = useState(false);
  const [mapQuery, setMapQuery] = useState('');
  const [searching, setSearching] = useState(false);
  const [searchResults, setSearchResults] = useState<{ lat: number; lon: number; label: string }[]>([]);
  const [flyTarget, setFlyTarget] = useState<MapFlyTarget | null>(null);
  const [loadedBoundaryBounds, setLoadedBoundaryBounds] = useState<LatLngExpression[] | null>(null);
  const [downloadState, setDownloadState] = useState<'idle' | 'success' | 'error'>('idle');

  const loadFarmBoundary = useCallback(async () => {
    if (!farmId) return;
    try {
      const res = await data.getBoundary(farmId);
      setHasBoundary(res.has_boundary);
      if (res.geojson) {
        setGeoJsonData(res.geojson);
        const feat = res.geojson.features?.[0];
        const coords = feat?.geometry?.type === 'Polygon'
          ? (feat.geometry.coordinates[0] as number[][]).map(c => [c[1], c[0]] as LatLngExpression)
          : [];
        if (coords.length) {
          setDrawPoints(coords.slice(0, -1));
          setLoadedBoundaryBounds(coords);
        }
      }
    } catch {
      setHasBoundary(false);
    }
  }, [farmId]);

  useEffect(() => {
    if (!farmId) return;
    farms.list().then(list => {
      const f = list.find(x => x.id === farmId) || null;
      setFarm(f);
      if (f?.location) setMapQuery(prev => prev || f.location || '');
    }).catch(() => {});
    loadFarmBoundary();
  }, [farmId, loadFarmBoundary]);

  const goToPlace = (lat: number, lon: number, label: string) => {
    setFlyTarget({ lat, lng: lon, zoom: 14, label });
    setSearchResults([]);
    setStatus(`Map centered on ${label}`);
  };

  const runMapSearch = async () => {
    const q = mapQuery.trim();
    if (!q) return;
    setSearching(true);
    setSearchResults([]);
    setStatus('');
    try {
      const res = await gis.geocode(q);
      if (res.error && !res.results?.length) {
        setStatus(res.error);
        return;
      }
      if (!res.results?.length) {
        setStatus('No places found. Try a city name or lat, lon (e.g. 39.8, -98.5).');
        return;
      }
      if (res.results.length === 1) {
        const r = res.results[0];
        goToPlace(r.lat, r.lon, r.label);
      } else {
        setSearchResults(res.results);
        setStatus(`${res.results.length} places found - pick one below.`);
      }
    } catch (e: unknown) {
      setStatus('Search failed: ' + (e instanceof Error ? e.message : String(e)));
    } finally {
      setSearching(false);
    }
  };

  const addPoint = (lat: number, lng: number) => {
    setDrawPoints(p => [...p, [lat, lng]]);
  };

  const saveBoundary = async () => {
    if (!farmId || drawPoints.length < 3) {
      setStatus('Click at least 3 corners of your field on the map.');
      return;
    }
    setLoading(true);
    setStatus('Saving boundary...');
    try {
      const ring = drawPoints.map(p => {
        const pt = p as [number, number];
        return [pt[1], pt[0]];
      });
      ring.push(ring[0]);
      const geojson: GeoJSON.FeatureCollection = {
        type: 'FeatureCollection',
        features: [{
          type: 'Feature',
          properties: { name: farm?.name || 'Farm boundary' },
          geometry: { type: 'Polygon', coordinates: [ring] },
        }],
      };
      const res = await data.saveBoundary(farmId, geojson);
      setGeoJsonData(geojson);
      setHasBoundary(true);
      setDrawing(false);
      setStatus(`Boundary saved (${res.area_ha?.toFixed(1) || '?'} ha). You can download map data next.`);
    } catch (e: unknown) {
      setStatus('Error: ' + (e instanceof Error ? e.message : String(e)));
    } finally {
      setLoading(false);
    }
  };

  const fetchOnline = async () => {
    if (!farmId) {
      setStatus('Select a farm first (open Maps from My Farms or Setup).');
      setDownloadState('error');
      return;
    }
    if (!hasBoundary) {
      setStatus('Draw and save your farm boundary first.');
      setDownloadState('error');
      return;
    }
    setLoading(true);
    setDownloadState('idle');
    setStatus('Downloading elevation, soil, and weather, then building your field model. This can take up to a minute...');
    try {
      const res = await data.fetchAndBuild(farmId);
      if (!res.ok) {
        throw new Error(res.error || 'Download or build failed.');
      }
      setHruCount(res.hru_count || 0);
      const src = res.sources?.length ? ` Sources: ${res.sources.join(', ')}.` : '';
      const ready = res.readiness?.ready_to_simulate;
      setDownloadState('success');
      setStatus(
        `Success! Built ${res.hru_count || 0} field zone(s).${src} ` +
        (ready ? 'Your farm is ready to simulate.' : 'Open Setup to finish and run your first simulation.')
      );
    } catch (e: unknown) {
      setDownloadState('error');
      const msg = e instanceof Error ? e.message : String(e);
      setStatus(
        msg.includes('boundary')
          ? msg
          : `Download failed: ${msg}. Check your internet connection and try again, or upload a QSWAT+ zip in Setup.`
      );
    } finally {
      setLoading(false);
    }
  };

  const loadData = async () => {
    if (!demFile && !soilFile && !luFile && !watershedFile) return;
    setLoading(true);
    setStatus('Loading GIS data...');
    try {
      const fd = new FormData();
      if (demFile) fd.append('dem', demFile);
      if (soilFile) fd.append('soil', soilFile);
      if (luFile) fd.append('landuse', luFile);
      if (watershedFile) fd.append('watershed', watershedFile);
      const res = await gis.loadData(fd);
      setStatus(res.message || 'Data loaded');
      if (res.geojson) setGeoJsonData(res.geojson);
    } catch (e: unknown) {
      setStatus('Error: ' + (e instanceof Error ? e.message : String(e)));
    } finally {
      setLoading(false);
    }
  };

  const generateHrus = async () => {
    setLoading(true);
    setStatus('Generating field zones...');
    try {
      const params = mode === 'simple'
        ? { lu_threshold: 1.0, soil_threshold: 1.0, slope_classes: '0,2,1\n2,5,2\n5,10,3\n10,999,4' }
        : { lu_threshold: luThreshold, soil_threshold: soilThreshold, slope_classes: slopeClasses };
      const res = await gis.generateHrus(params);
      if (res.success) {
        setHruCount(res.hru_count);
        setStatus(`Generated ${res.hru_count} HRUs`);
        if (farmId) {
          await data.buildModel(farmId).catch(() => {});
        }
      } else {
        setStatus('Error: ' + res.error);
      }
    } catch (e: unknown) {
      setStatus('Error: ' + (e instanceof Error ? e.message : String(e)));
    } finally {
      setLoading(false);
    }
  };

  const exportTxt = async () => {
    if (!outputPath) { setStatus('Error: specify output path'); return; }
    setLoading(true);
    try {
      await gis.exportTxtinout(outputPath);
      setStatus('Exported to ' + outputPath);
    } catch (e: unknown) {
      setStatus('Error: ' + (e instanceof Error ? e.message : String(e)));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-full">
      <div className="w-80 border-r border-[var(--se-border)] bg-[var(--se-card)] flex flex-col overflow-y-auto">
        <div className="p-5 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-[var(--se-text)] flex items-center gap-2">
              <Layers className="w-4 h-4" /> Maps
            </h2>
            <div className="flex rounded-lg border border-[var(--se-border)] overflow-hidden text-xs">
              <button
                onClick={() => setMode('simple')}
                className={clsx('px-2 py-1', mode === 'simple' ? 'bg-[var(--se-accent-sf)] text-[var(--se-accent)]' : 'text-[var(--se-text-mut)] hover:bg-[var(--se-rail)]')}
              >
                Simple
              </button>
              <button
                onClick={() => setMode('advanced')}
                className={clsx('px-2 py-1 flex items-center gap-1', mode === 'advanced' ? 'bg-[var(--se-accent-sf)] text-[var(--se-accent)]' : 'text-[var(--se-text-mut)] hover:bg-[var(--se-rail)]')}
              >
                <Settings2 className="w-3 h-3" /> Advanced
              </button>
            </div>
          </div>

          {farm ? (
            <div className="rounded-lg border border-[var(--se-accent-bd)] bg-[var(--se-accent-sf)] px-3 py-2 text-xs">
              <p className="text-[var(--se-text)] font-medium">{farm.name}</p>
              <p className="text-[var(--se-text-mut)]">{farm.location || 'Setting up this farm'}</p>
              {farmId && (
                <Link to={`/setup?farm=${farmId}`} className="text-[var(--se-accent)] hover:underline mt-1 inline-block">
                  Back to Setup
                </Link>
              )}
            </div>
          ) : (
            <p className="text-xs text-[var(--se-warn)]">
              Tip: open Maps from <Link to="/farms" className="text-[var(--se-accent)] underline">My Farms</Link> so your boundary links to a farm.
            </p>
          )}

          <div className="rounded-xl border border-[var(--se-border)] p-3 space-y-2">
            <label className="text-xs font-medium text-[var(--se-text)] flex items-center gap-1.5">
              <Search className="w-3.5 h-3.5" /> Find on map
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                className="flex-1 min-w-0 bg-[var(--se-bg)] border border-[var(--se-border)] rounded-lg px-3 py-2 text-xs text-[var(--se-text)] placeholder:text-[var(--se-text-fnt)] focus:outline-none focus:border-[var(--se-accent)]"
                placeholder="City, address, or lat, lon"
                value={mapQuery}
                onChange={e => setMapQuery(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') runMapSearch(); }}
              />
              <button
                type="button"
                onClick={runMapSearch}
                disabled={searching || !mapQuery.trim()}
                className="shrink-0 px-3 py-2 rounded-lg bg-[var(--se-rail)] hover:bg-[var(--se-border-lt)] border border-[var(--se-border)] text-[var(--se-text)] disabled:opacity-40 text-xs"
              >
                {searching ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Go'}
              </button>
            </div>
            <p className="text-[10px] text-[var(--se-text-fnt)]">Examples: Kansas City, USA or 39.0997, -94.5786</p>
            {searchResults.length > 0 && (
              <ul className="max-h-36 overflow-y-auto space-y-1 border-t border-[var(--se-border)] pt-2">
                {searchResults.map((r, i) => (
                  <li key={i}>
                    <button
                      type="button"
                      onClick={() => goToPlace(r.lat, r.lon, r.label)}
                      className="w-full text-left text-[11px] text-[var(--se-text-mut)] hover:text-[var(--se-accent)] hover:bg-[var(--se-rail)] rounded px-2 py-1.5 line-clamp-2"
                    >
                      {r.label}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="rounded-xl border border-[var(--se-border)] p-4 space-y-3">
            <p className="text-xs font-medium text-[var(--se-text)]">1. Draw farm boundary</p>
            <p className="text-[11px] text-[var(--se-text-mut)]">Click corners of your field. Map pan is locked while drawing; click Draw again to pan.</p>
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => setDrawing(d => !d)}
                className={clsx(
                  'flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg border',
                  drawing ? 'border-[var(--se-accent-bd)] text-[var(--se-accent)] bg-[var(--se-accent-sf)]' : 'border-[var(--se-border)] text-[var(--se-text-mut)] hover:bg-[var(--se-rail)]'
                )}
              >
                <Pencil className="w-3 h-3" /> {drawing ? 'Drawing...' : 'Draw'}
              </button>
              <button
                onClick={() => setDrawPoints(p => p.slice(0, -1))}
                disabled={!drawPoints.length}
                className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg border border-[var(--se-border)] text-[var(--se-text-mut)] hover:bg-[var(--se-rail)] disabled:opacity-40"
              >
                Undo
              </button>
              <button
                onClick={() => { setDrawPoints([]); setLoadedBoundaryBounds(null); setDrawing(true); }}
                className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg border border-[var(--se-border)] text-[var(--se-text-mut)] hover:bg-[var(--se-rail)]"
              >
                <Trash2 className="w-3 h-3" /> Clear
              </button>
            </div>
            <button
              onClick={saveBoundary}
              disabled={loading || !farmId || drawPoints.length < 3}
              className="w-full flex items-center justify-center gap-2 bg-[var(--se-accent)] hover:bg-[var(--se-accent-h)] text-white disabled:opacity-40 rounded-lg py-2 text-xs font-medium"
            >
              <Save className="w-3.5 h-3.5" /> Save boundary
            </button>
          </div>

          <div className="rounded-xl border border-[var(--se-border)] p-4 space-y-3">
            <p className="text-xs font-medium text-[var(--se-text)]">2. Download map data</p>
            <p className="text-[11px] text-[var(--se-text-mut)]">
              Fetches elevation (Open-Elevation), soil (SoilGrids), and weather (Open-Meteo) for your boundary.
            </p>
            <button
              onClick={fetchOnline}
              disabled={loading || !farmId || !hasBoundary}
              className="w-full flex items-center justify-center gap-2 bg-[var(--se-accent)] hover:bg-[var(--se-accent-h)] text-white disabled:opacity-40 rounded-lg py-2 text-xs font-medium"
            >
              {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CloudDownload className="w-3.5 h-3.5" />}
              {loading ? 'Downloading...' : 'Download data for my area'}
            </button>
            {!hasBoundary && farmId && (
              <p className="text-[10px] text-[var(--se-warn)]">Save your boundary above before downloading.</p>
            )}
            {downloadState === 'success' && farmId && (
              <Link
                to={`/setup?farm=${farmId}`}
                className="block text-center text-xs text-[var(--se-accent)] hover:underline pt-1"
              >
                Continue to Setup and run simulation
              </Link>
            )}
          </div>

          {mode === 'simple' && (
            <p className="text-xs text-[var(--se-text-mut)]">Or upload your own map files below (optional).</p>
          )}

          {[
            { label: 'DEM (GeoTIFF)', file: demFile, set: setDemFile },
            { label: 'Soil (Shapefile)', file: soilFile, set: setSoilFile },
            { label: 'Land Use (GeoTIFF/SHP)', file: luFile, set: setLuFile },
            { label: 'Watershed (SHP/KML)', file: watershedFile, set: setWatershedFile },
          ].map(({ label, file, set }) => (
            <div key={label}>
              <label className="text-xs text-[var(--se-text-mut)] block mb-1">{label}</label>
              <div className="flex items-center gap-2">
                <input type="file" className="text-xs text-[var(--se-text-mut)] file:mr-2 file:rounded file:border-0 file:bg-[var(--se-rail)] file:px-2 file:py-1 file:text-[var(--se-text)]" onChange={e => set(e.target.files?.[0] || null)} />
                {file && <span className="text-xs text-[var(--se-accent)] truncate max-w-[120px]">{file.name}</span>}
              </div>
            </div>
          ))}

          <button
            onClick={loadData}
            disabled={loading}
            className="w-full flex items-center justify-center gap-2 bg-[var(--se-rail)] hover:bg-[var(--se-border-lt)] border border-[var(--se-border)] text-[var(--se-text)] disabled:opacity-50 rounded-lg py-2 text-sm"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
            Load uploaded files
          </button>

          {status && (
            <p
              className={clsx(
                'text-xs rounded-lg px-3 py-2 border',
                downloadState === 'success' && 'text-[var(--se-ok)] bg-[var(--se-ok-sf)] border-[var(--se-ok-bd)]',
                downloadState === 'error' && 'text-[var(--se-error)] bg-[var(--se-error-sf)] border-[var(--se-error-bd)]',
                downloadState === 'idle' && 'text-[var(--se-text-mut)] bg-[var(--se-rail)] border-[var(--se-border)]'
              )}
            >
              {status}
            </p>
          )}

          <hr className="border-[var(--se-border)]" />

          {mode === 'advanced' && (
            <>
              <h2 className="text-sm font-semibold text-[var(--se-text)]">HRU Settings</h2>
              <div>
                <label className="text-xs text-[var(--se-text-mut)] block mb-1">Land Use Threshold (%)</label>
                <input type="range" min={0} max={20} step={0.5} value={luThreshold} onChange={e => setLuThreshold(parseFloat(e.target.value))} className="w-full accent-[var(--se-accent)]" />
              </div>
              <div>
                <label className="text-xs text-[var(--se-text-mut)] block mb-1">Soil Threshold (%)</label>
                <input type="range" min={0} max={20} step={0.5} value={soilThreshold} onChange={e => setSoilThreshold(parseFloat(e.target.value))} className="w-full accent-[var(--se-accent)]" />
              </div>
            </>
          )}

          <button
            onClick={generateHrus}
            disabled={loading}
            className="w-full flex items-center justify-center gap-2 bg-[var(--se-accent)] hover:bg-[var(--se-accent-h)] text-white disabled:opacity-50 rounded-lg py-2 text-sm font-medium"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
            Generate field zones
          </button>

          {hruCount > 0 && (
            <p className="text-xs text-[var(--se-accent)]">{hruCount} field zones ready</p>
          )}

          {mode === 'advanced' && (
            <>
              <input type="text" className="w-full bg-[var(--se-bg)] border border-[var(--se-border)] rounded-lg px-3 py-2 text-xs text-[var(--se-text)] placeholder:text-[var(--se-text-fnt)] focus:outline-none focus:border-[var(--se-accent)]" placeholder="/path/to/TxtInOut" value={outputPath} onChange={e => setOutputPath(e.target.value)} />
              <button onClick={exportTxt} disabled={loading || !hruCount} className="w-full flex items-center justify-center gap-2 bg-[var(--se-rail)] hover:bg-[var(--se-border-lt)] border border-[var(--se-border)] text-[var(--se-text)] disabled:opacity-50 rounded-lg py-2 text-sm">
                <Download className="w-4 h-4" /> Export
              </button>
            </>
          )}
        </div>
      </div>

      <div className="flex-1 relative">
        <MapContainer center={mapCenter} zoom={5} maxZoom={19} style={{ height: '100%', width: '100%' }}>
          <MapBasemap defaultLayer="satellite" />
          <MapInitialBounds bounds={drawing ? null : loadedBoundaryBounds} />
          <MapDrawHandler drawing={drawing} points={drawPoints} onAddPoint={addPoint} />
          <MapFlyTo target={flyTarget} />
          {geoJsonData !== null && drawPoints.length < 3 ? (
            <GeoJSON
              data={geoJsonData as GeoJSON.GeoJsonObject}
              style={() => ({ color: '#22c55e', weight: 2, fillOpacity: 0.3 })}
            />
          ) : null}
        </MapContainer>
        {!geoJsonData && !drawPoints.length && (
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <div className="text-center bg-[var(--se-card)]/95 backdrop-blur-sm rounded-xl px-4 py-3 shadow-md border border-[var(--se-border)]">
              <MapPin className="w-8 h-8 text-[var(--se-accent)] mx-auto mb-2" />
              <p className="text-[var(--se-text-mut)] text-sm">Click Draw, then click your field corners on the map</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
