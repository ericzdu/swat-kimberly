import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { farms } from '@/lib/api';
import { Plus, Trash2, Loader2, Settings2 } from 'lucide-react';

interface Farm {
  id: string;
  name: string;
  location?: string;
  soil_type?: string;
  txtinout_path?: string;
  setup_complete?: number | boolean;
  data_source?: string;
  created_at: string;
}

export default function FarmManagement() {
  const [farmsList, setFarmsList] = useState<Farm[]>([]);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [form, setForm] = useState({ name: '', location: '', soil_type: '', txtinout_path: '' });

  const load = () => farms.list().then(setFarmsList).catch(() => {});
  useEffect(() => { load(); }, []);

  const create = async () => {
    if (!form.name.trim()) { setMsg('Name required'); return; }
    setLoading(true);
    try {
      await farms.create(form);
      setForm({ name: '', location: '', soil_type: '', txtinout_path: '' });
      setMsg('Farm added - open Setup to add field data');
      load();
    } catch { setMsg('Error creating farm'); }
    finally { setLoading(false); }
  };

  const remove = async (id: string) => {
    setLoading(true);
    try { await farms.delete(id); setMsg('Deleted'); load(); }
    catch { setMsg('Error deleting'); }
    finally { setLoading(false); }
  };

  return (
    <div className="p-6 space-y-6 max-w-3xl">
      <h1 className="text-xl font-bold text-white">My Farms</h1>

      <div className="border border-white/10 rounded-xl p-5 space-y-4">
        <h2 className="text-sm font-semibold text-white/80">Add New Farm</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <input
            className="bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm"
            placeholder="Farm name *"
            value={form.name}
            onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
          />
          <input
            className="bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm"
            placeholder="Location"
            value={form.location}
            onChange={e => setForm(f => ({ ...f, location: e.target.value }))}
          />
          <input
            className="bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm"
            placeholder="Soil type (e.g. Loam)"
            value={form.soil_type}
            onChange={e => setForm(f => ({ ...f, soil_type: e.target.value }))}
          />
        </div>
        <button
          type="button"
          onClick={() => setShowAdvanced(v => !v)}
          className="flex items-center gap-1 text-xs text-white/40 hover:text-white/60"
        >
          <Settings2 className="w-3 h-3" /> Advanced options
        </button>
        {showAdvanced && (
          <input
            className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm"
            placeholder="TxtInOut path (experts only)"
            value={form.txtinout_path}
            onChange={e => setForm(f => ({ ...f, txtinout_path: e.target.value }))}
          />
        )}
        <div className="flex gap-3">
          <button
            onClick={create}
            disabled={loading}
            className="flex items-center gap-2 bg-moss-600 hover:bg-moss-700 disabled:opacity-50 rounded-lg px-4 py-2 text-sm font-medium"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
            Add Farm
          </button>
          <Link to="/setup" className="text-sm text-moss-400 hover:text-moss-300 py-2">Use setup wizard instead</Link>
        </div>
        {msg && <p className="text-xs text-white/40">{msg}</p>}
      </div>

      <div className="space-y-3">
        {farmsList.map(f => (
          <div key={f.id} className="border border-white/10 rounded-xl p-4 flex items-center justify-between gap-4">
            <div>
              <p className="font-medium text-white">{f.name}</p>
              <p className="text-xs text-white/40">
                {f.location || 'No location'}
                {f.data_source && ` · ${f.data_source}`}
                {f.setup_complete ? ' · Ready' : ' · Setup incomplete'}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Link to={`/data?farm=${f.id}`} className="text-xs text-white/40 hover:text-moss-300 px-2 py-1">Data</Link>
              {!f.setup_complete && (
                <>
                  <Link to={`/setup?farm=${f.id}`} className="text-xs text-moss-400 hover:text-moss-300 px-2 py-1">Setup</Link>
                  <Link to={`/gis?farm=${f.id}`} className="text-xs text-blue-400 hover:text-blue-300 px-2 py-1">Maps</Link>
                </>
              )}
              <button
                onClick={() => remove(f.id)}
                disabled={loading}
                className="p-2 text-red-400/70 hover:text-red-400 disabled:opacity-50"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
