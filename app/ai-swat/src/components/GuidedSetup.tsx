import { useEffect, useState } from 'react';
import { MapContainer } from 'react-leaflet';
import type { LatLngExpression } from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { data, gis, type FieldSetupOptions } from '@/lib/api';
import { MapBasemap } from '@/components/MapBasemap';
import { MapDrawHandler, MapInitialBounds } from '@/components/MapDrawHandler';
import { MapFlyTo, type MapFlyTarget } from '@/components/MapFlyTo';
import {
  Search, Trash2, Undo2, Check, Loader2, ArrowRight, ArrowLeft, MapPin, Sprout,
  Droplets, FlaskConical, Calendar, Sparkles, AlertTriangle, Plus, Minus,
} from 'lucide-react';
import clsx from 'clsx';

type Step = 'location' | 'rotation' | 'manure' | 'irrigation' | 'simulation' | 'building' | 'done';
const FLOW: { key: Step; label: string }[] = [
  { key: 'location', label: 'Location' },
  { key: 'rotation', label: 'Crops' },
  { key: 'manure', label: 'Manure' },
  { key: 'irrigation', label: 'Water' },
  { key: 'simulation', label: 'Time' },
];

// SWAT+ plant codes the model understands, with farmer-friendly labels.
const CROPS = [
  { code: 'csil', label: 'Corn silage' },
  { code: 'corn', label: 'Corn (grain)' },
  { code: 'soyb', label: 'Soybeans' },
  { code: 'wwht', label: 'Winter wheat' },
  { code: 'alfa', label: 'Alfalfa' },
  { code: 'barl', label: 'Barley' },
];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const IRR_TIERS = [
  { id: 'high', label: 'High efficiency', desc: 'Modern pivot/drip — frequent light applications, least leaching' },
  { id: 'medium', label: 'Medium efficiency', desc: 'Standard center pivot (Galen’s default)' },
  { id: 'low', label: 'Low efficiency', desc: 'Furrow/flood — large infrequent sets, most leaching' },
] as const;

// Deterministic, step-by-step setup that ASKS the field-specific choices (rotation,
// manure, irrigation, simulation length) with Galen's values pre-filled, then builds.
export default function GuidedSetup({ farmId, farmName, onComplete }: {
  farmId: string;
  farmName: string;
  onComplete: () => void;
}) {
  const [step, setStep] = useState<Step>('location');
  const [busy, setBusy] = useState(false);

  // location
  const [drawPoints, setDrawPoints] = useState<LatLngExpression[]>([]);
  const [mapQuery, setMapQuery] = useState('');
  const [searching, setSearching] = useState(false);
  const [flyTarget, setFlyTarget] = useState<MapFlyTarget | null>(null);
  const [status, setStatus] = useState('');

  // collected field parameters (Galen defaults pre-filled)
  const [rotYears, setRotYears] = useState(1);
  const [crops, setCrops] = useState<string[]>(['csil']);
  const [manureOn, setManureOn] = useState(false);
  const [manure, setManure] = useState<{ month: number; amount: number }[]>([{ month: 5, amount: 20000 }]);
  const [irrTier, setIrrTier] = useState<'high' | 'medium' | 'low'>('medium');
  const [simYears, setSimYears] = useState(2);

  // build
  const [buildMsg, setBuildMsg] = useState('');
  const [buildError, setBuildError] = useState('');

  // keep crops/manure arrays sized to the rotation length
  useEffect(() => {
    setCrops(c => Array.from({ length: rotYears }, (_, i) => c[i] || 'csil'));
    setManure(m => Array.from({ length: rotYears }, (_, i) => m[i] || { month: 5, amount: 20000 }));
  }, [rotYears]);

  const runSearch = async (q: string) => {
    if (!q.trim()) return;
    setSearching(true); setStatus('');
    try {
      const res = await gis.geocode(q.trim());
      const r = res.results?.[0];
      if (r) { setFlyTarget({ lat: r.lat, lng: r.lon, zoom: 15, label: r.label }); setStatus(`Centered on ${r.label} — click the corners of your field.`); }
      else setStatus(res.error || 'No place found. Try a town, address, or "lat, lon".');
    } catch { setStatus('Search failed — check your connection.'); }
    finally { setSearching(false); }
  };

  // Save the boundary, then go wherever the caller wants — 'building' to create the
  // field immediately with Galen defaults (boundary is all that's required), or
  // 'rotation' to walk the optional setup steps.
  const saveLocation = async (next: Step = 'rotation') => {
    if (drawPoints.length < 3) { setStatus('Click at least 3 corners of your field on the map.'); return; }
    setBusy(true); setStatus('Saving field boundary…');
    try {
      const ring = drawPoints.map(pt => { const c = pt as [number, number]; return [c[1], c[0]]; });
      ring.push(ring[0]);
      const geojson: GeoJSON.FeatureCollection = {
        type: 'FeatureCollection',
        features: [{ type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [ring] } }],
      };
      await data.saveBoundary(farmId, geojson);
      setStep(next);
    } catch (e) { setStatus('Could not save: ' + (e instanceof Error ? e.message : 'unknown error')); }
    finally { setBusy(false); }
  };

  // Build once all questions are answered.
  useEffect(() => {
    if (step !== 'building') return;
    let alive = true;
    setBuildError(''); setBuildMsg('Pulling the dominant gSSURGO soil, weather, and building your field model…');
    const options: FieldSetupOptions = {
      rotation: { years: rotYears, crops },
      manure: manureOn ? manure.map((m, i) => ({ year: i + 1, month: m.month, amount_kg_ha: m.amount })) : [],
      irrigation_tier: irrTier,
      sim_years: simYears,
    };
    data.fetchAndBuild(farmId, options)
      .then(() => { if (alive) setStep('done'); })
      .catch(e => { if (alive) setBuildError(e instanceof Error ? e.message : 'Could not build the field model.'); });
    return () => { alive = false; };
  }, [step]); // eslint-disable-line react-hooks/exhaustive-deps

  const activeIdx = FLOW.findIndex(s => s.key === step);
  const label = 'text-xs font-medium text-[var(--se-text-mut)]';
  const sel = 'mt-1 w-full bg-white border border-[var(--se-border)] rounded-lg px-3 py-2 text-sm text-[var(--se-text)] focus:outline-none focus:border-[var(--se-accent)]';
  const primaryBtn = 'ml-auto flex items-center gap-1.5 bg-[var(--se-accent)] hover:bg-[var(--se-accent-h)] text-white disabled:opacity-40 rounded-lg px-5 py-2 text-sm font-medium';
  const backBtn = 'flex items-center gap-1 text-sm px-3 py-2 rounded-lg border border-[var(--se-border)] text-[var(--se-text-mut)] hover:text-[var(--se-text)]';
  const go = (s: Step) => () => setStep(s);

  return (
    <div className="bg-[var(--se-card)] border border-[var(--se-border)] rounded-2xl shadow-sm overflow-hidden">
      {/* Header + progress */}
      <div className="px-6 pt-5 pb-4 border-b border-[var(--se-border-lt)]">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-[var(--se-accent)] flex items-center justify-center shrink-0"><Sparkles className="w-4 h-4 text-white" /></div>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold truncate">Set up {farmName || 'your field'}</h2>
            <p className="text-[11px] text-[var(--se-text-fnt)]">A few questions about your field — defaults are filled in, change what you like.</p>
          </div>
        </div>
        {step !== 'done' && (
          <div className="flex items-center gap-1.5 mt-4 flex-wrap">
            {FLOW.map((s, i) => {
              const done = activeIdx > i, active = activeIdx === i;
              return (
                <div key={s.key} className="flex items-center gap-1.5">
                  <span className={clsx('flex items-center gap-1.5 text-[11px] font-medium rounded-full px-2.5 py-1 border whitespace-nowrap',
                    active && 'bg-[var(--se-accent-sf)] text-[var(--se-accent)] border-[var(--se-accent-bd)]',
                    done && 'text-[var(--se-ok)] border-[color:var(--se-ok-bd)] bg-[var(--se-ok-sf)]',
                    !active && !done && 'text-[var(--se-text-fnt)] border-[var(--se-border)]')}>
                    <span className={clsx('w-4 h-4 rounded-full flex items-center justify-center text-[9px]', active ? 'bg-[var(--se-accent)] text-white' : done ? 'bg-[var(--se-ok)] text-white' : 'bg-[var(--se-border)] text-white')}>
                      {done ? <Check className="w-2.5 h-2.5" /> : i + 1}
                    </span>{s.label}
                  </span>
                  {i < FLOW.length - 1 && <span className={clsx('h-px w-3', done ? 'bg-[var(--se-ok)]' : 'bg-[var(--se-border)]')} />}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="p-6">
        {/* STEP 1 — LOCATION */}
        {step === 'location' && (
          <div className="space-y-3">
            <div className="flex items-center gap-2"><MapPin className="w-4 h-4 text-[var(--se-accent)]" /><h3 className="text-base font-semibold">Where is your field?</h3></div>
            <p className="text-sm text-[var(--se-text-mut)]">Search for the nearest town, then click the corners of your field. I’ll pull its soil, weather, and topography from there.</p>
            <div className="flex gap-2">
              <div className="flex-1 flex items-center gap-1.5 bg-white border border-[var(--se-border)] rounded-lg px-2.5 focus-within:border-[var(--se-accent)]">
                <Search className="w-3.5 h-3.5 text-[var(--se-text-fnt)] shrink-0" />
                <input type="text" className="flex-1 min-w-0 bg-transparent py-2 text-sm text-[var(--se-text)] placeholder:text-[var(--se-text-fnt)] focus:outline-none"
                  placeholder="Town, address, or lat, lon" value={mapQuery} onChange={e => setMapQuery(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') runSearch(mapQuery); }} />
              </div>
              <button onClick={() => runSearch(mapQuery)} disabled={searching || !mapQuery.trim()} className="shrink-0 px-4 rounded-lg bg-[var(--se-rail)] hover:bg-[var(--se-border-lt)] border border-[var(--se-border)] text-[var(--se-text)] disabled:opacity-40 text-sm">
                {searching ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Search'}
              </button>
            </div>
            <div className="rounded-lg overflow-hidden border border-[var(--se-border)] shadow-sm" style={{ height: 'clamp(340px, 44vh, 520px)' }}>
              <MapContainer center={[39.8, -98.5]} zoom={4} maxZoom={19} style={{ height: '100%', width: '100%' }}>
                <MapBasemap defaultLayer="satellite" />
                <MapInitialBounds bounds={null} />
                <MapDrawHandler drawing points={drawPoints} onAddPoint={(la, lo) => setDrawPoints(p => [...p, [la, lo]])} />
                <MapFlyTo target={flyTarget} />
              </MapContainer>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button onClick={() => setDrawPoints(p => p.slice(0, -1))} disabled={!drawPoints.length} className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg border border-[var(--se-border)] text-[var(--se-text-mut)] hover:bg-[var(--se-rail)] disabled:opacity-40"><Undo2 className="w-3 h-3" /> Undo</button>
              <button onClick={() => setDrawPoints([])} disabled={!drawPoints.length} className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg border border-[var(--se-border)] text-[var(--se-text-mut)] hover:bg-[var(--se-rail)] disabled:opacity-40"><Trash2 className="w-3 h-3" /> Clear</button>
              <span className="text-[11px] text-[var(--se-text-fnt)]">{drawPoints.length} corner(s)</span>
              <button onClick={() => saveLocation('rotation')} disabled={busy || drawPoints.length < 3}
                className="ml-auto flex items-center gap-1 text-sm px-3 py-2 rounded-lg border border-[var(--se-border)] text-[var(--se-text-mut)] hover:text-[var(--se-text)] hover:bg-[var(--se-rail)] disabled:opacity-40">
                Customize setup <ArrowRight className="w-4 h-4" />
              </button>
              <button onClick={() => saveLocation('building')} disabled={busy || drawPoints.length < 3} className={primaryBtn.replace('ml-auto ', '')}>
                {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <><Check className="w-4 h-4" /> Create field</>}
              </button>
            </div>
            <p className="text-[11px] text-[var(--se-text-fnt)]">The boundary is all that&apos;s required — “Create field” builds it now with sensible defaults (corn silage, gSSURGO soil, gridMET weather). Everything else is optional.</p>
            {status && <p className="text-xs text-[var(--se-text-mut)]">{status}</p>}
          </div>
        )}

        {/* STEP 2 — CROP ROTATION */}
        {step === 'rotation' && (
          <div className="space-y-4">
            <div className="flex items-center gap-2"><Sprout className="w-4 h-4 text-[var(--se-accent)]" /><h3 className="text-base font-semibold">What do you grow?</h3></div>
            <p className="text-sm text-[var(--se-text-mut)]">Choose your rotation length and the crop for each year. Planting &amp; harvest dates are set automatically.</p>
            <label className={label}>Rotation length (years)
              <div className="mt-1 flex items-center gap-2">
                <button onClick={() => setRotYears(y => Math.max(1, y - 1))} className="p-2 rounded-lg border border-[var(--se-border)] hover:bg-[var(--se-rail)]"><Minus className="w-3.5 h-3.5" /></button>
                <span className="w-10 text-center text-sm font-semibold tabular-nums">{rotYears}</span>
                <button onClick={() => setRotYears(y => Math.min(6, y + 1))} className="p-2 rounded-lg border border-[var(--se-border)] hover:bg-[var(--se-rail)]"><Plus className="w-3.5 h-3.5" /></button>
              </div>
            </label>
            <div className="grid gap-3 sm:grid-cols-2">
              {Array.from({ length: rotYears }).map((_, i) => (
                <label key={i} className={label}>Year {i + 1} crop
                  <select className={sel} value={crops[i] || 'csil'} onChange={e => setCrops(c => c.map((x, j) => j === i ? e.target.value : x))}>
                    {CROPS.map(c => <option key={c.code} value={c.code}>{c.label}</option>)}
                  </select>
                </label>
              ))}
            </div>
            <div className="flex items-center gap-2 pt-1"><button onClick={go('location')} className={backBtn}><ArrowLeft className="w-4 h-4" /> Back</button><button onClick={go('manure')} className={primaryBtn}>Next <ArrowRight className="w-4 h-4" /></button></div>
          </div>
        )}

        {/* STEP 3 — MANURE */}
        {step === 'manure' && (
          <div className="space-y-4">
            <div className="flex items-center gap-2"><FlaskConical className="w-4 h-4 text-[var(--se-accent)]" /><h3 className="text-base font-semibold">Do you apply manure?</h3></div>
            <p className="text-sm text-[var(--se-text-mut)]">If so, set the month and amount for each year. The model adds synthetic N &amp; P as the crop needs it.</p>
            <label className="flex items-center gap-2.5 text-sm text-[var(--se-text)] cursor-pointer">
              <input type="checkbox" className="w-4 h-4 accent-[var(--se-accent)]" checked={manureOn} onChange={e => setManureOn(e.target.checked)} />
              I apply manure on this field
            </label>
            {manureOn && (
              <div className="space-y-2">
                {Array.from({ length: rotYears }).map((_, i) => (
                  <div key={i} className="grid grid-cols-[auto,1fr,1fr] items-end gap-2">
                    <span className="text-xs text-[var(--se-text-mut)] pb-2">Year {i + 1}</span>
                    <label className={label}>Month
                      <select className={sel} value={manure[i]?.month || 5} onChange={e => setManure(m => m.map((x, j) => j === i ? { ...x, month: Number(e.target.value) } : x))}>
                        {MONTHS.map((mo, mi) => <option key={mo} value={mi + 1}>{mo}</option>)}
                      </select>
                    </label>
                    <label className={label}>Amount (kg/ha)
                      <input type="number" min={0} className={sel} value={manure[i]?.amount ?? 0} onChange={e => setManure(m => m.map((x, j) => j === i ? { ...x, amount: Number(e.target.value) || 0 } : x))} />
                    </label>
                  </div>
                ))}
                <p className="text-[11px] text-[var(--se-text-fnt)]">Assumed beef manure nutrient content for now. Typical rate ≈ 20,000–40,000 kg/ha wet.</p>
              </div>
            )}
            <div className="flex items-center gap-2 pt-1"><button onClick={go('rotation')} className={backBtn}><ArrowLeft className="w-4 h-4" /> Back</button><button onClick={go('irrigation')} className={primaryBtn}>Next <ArrowRight className="w-4 h-4" /></button></div>
          </div>
        )}

        {/* STEP 4 — IRRIGATION */}
        {step === 'irrigation' && (
          <div className="space-y-4">
            <div className="flex items-center gap-2"><Droplets className="w-4 h-4 text-[var(--se-accent)]" /><h3 className="text-base font-semibold">Irrigation efficiency?</h3></div>
            <p className="text-sm text-[var(--se-text-mut)]">Automatic irrigation waters the crop when the soil dries out. Pick your system’s efficiency.</p>
            <div className="space-y-2">
              {IRR_TIERS.map(t => (
                <button key={t.id} onClick={() => setIrrTier(t.id)} className={clsx('w-full text-left px-4 py-3 rounded-lg border flex items-start gap-3 transition-colors',
                  irrTier === t.id ? 'border-[var(--se-accent)] bg-[var(--se-accent-sf)]' : 'border-[var(--se-border)] bg-white hover:bg-[var(--se-rail)]')}>
                  <span className={clsx('mt-0.5 w-4 h-4 rounded-full border-2 shrink-0', irrTier === t.id ? 'border-[var(--se-accent)] bg-[var(--se-accent)]' : 'border-[var(--se-border)]')} />
                  <span><span className="text-sm font-medium text-[var(--se-text)]">{t.label}</span><span className="block text-xs text-[var(--se-text-mut)] mt-0.5">{t.desc}</span></span>
                </button>
              ))}
            </div>
            <div className="flex items-center gap-2 pt-1"><button onClick={go('manure')} className={backBtn}><ArrowLeft className="w-4 h-4" /> Back</button><button onClick={go('simulation')} className={primaryBtn}>Next <ArrowRight className="w-4 h-4" /></button></div>
          </div>
        )}

        {/* STEP 5 — SIMULATION */}
        {step === 'simulation' && (
          <div className="space-y-4">
            <div className="flex items-center gap-2"><Calendar className="w-4 h-4 text-[var(--se-accent)]" /><h3 className="text-base font-semibold">How many years to simulate?</h3></div>
            <p className="text-sm text-[var(--se-text-mut)]">More years give a better long-term average and a longer timeline to scroll. (Up to 10 — the base SWAT+ model has numerical crashes on longer continuous runs.)</p>
            <label className={label}>Simulation length (years)
              <div className="mt-1 flex items-center gap-2">
                <button onClick={() => setSimYears(y => Math.max(1, y - 1))} className="p-2 rounded-lg border border-[var(--se-border)] hover:bg-[var(--se-rail)]"><Minus className="w-3.5 h-3.5" /></button>
                <span className="w-10 text-center text-sm font-semibold tabular-nums">{simYears}</span>
                <button onClick={() => setSimYears(y => Math.min(10, y + 1))} className="p-2 rounded-lg border border-[var(--se-border)] hover:bg-[var(--se-rail)]"><Plus className="w-3.5 h-3.5" /></button>
              </div>
            </label>
            <div className="flex items-center gap-2 pt-1"><button onClick={go('irrigation')} className={backBtn}><ArrowLeft className="w-4 h-4" /> Back</button>
              <button onClick={go('building')} className={primaryBtn}>Build my field <Check className="w-4 h-4" /></button></div>
          </div>
        )}

        {/* BUILDING */}
        {step === 'building' && (
          <div className="py-8 text-center space-y-4">
            {buildError ? (
              <>
                <div className="w-12 h-12 rounded-2xl bg-[var(--se-error-sf)] flex items-center justify-center mx-auto"><AlertTriangle className="w-6 h-6 text-[var(--se-error)]" /></div>
                <div><p className="text-sm font-semibold">Couldn’t build the field model</p><p className="text-xs text-[var(--se-error)] mt-1 max-w-md mx-auto">{buildError}</p></div>
                <button onClick={go('simulation')} className="text-sm px-4 py-2 rounded-lg border border-[var(--se-border)] text-[var(--se-text-mut)] hover:text-[var(--se-text)]">Back</button>
              </>
            ) : (
              <>
                <Loader2 className="w-10 h-10 animate-spin text-[var(--se-accent)] mx-auto" />
                <div><p className="text-base font-semibold">Building your field model</p><p className="text-sm text-[var(--se-text-mut)] mt-1 max-w-md mx-auto">{buildMsg}</p><p className="text-[11px] text-[var(--se-text-fnt)] mt-2">Downloading gSSURGO soil + assembling the SWAT+ project…</p></div>
              </>
            )}
          </div>
        )}

        {/* DONE */}
        {step === 'done' && (
          <div className="py-8 text-center space-y-4">
            <div className="w-12 h-12 rounded-2xl bg-[var(--se-ok-sf)] flex items-center justify-center mx-auto"><Check className="w-6 h-6 text-[var(--se-ok)]" /></div>
            <div><p className="text-base font-semibold">{farmName || 'Your field'} is ready!</p>
              <p className="text-sm text-[var(--se-text-mut)] mt-1 max-w-md mx-auto">Built from your field’s real soil and your crop, manure, and irrigation choices. Ask me about water quality or yield — or run an analysis.</p></div>
            <button onClick={onComplete} className="bg-[var(--se-accent)] hover:bg-[var(--se-accent-h)] text-white rounded-lg px-5 py-2 text-sm font-medium">Start using {farmName || 'my field'}</button>
          </div>
        )}
      </div>
    </div>
  );
}
