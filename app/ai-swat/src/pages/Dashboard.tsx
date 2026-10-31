import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { farms, type Farm, type FarmInsights } from '@/lib/api';
import InsightCard from '@/components/InsightCard';
import { Droplets, Sprout, MapPin, Wheat, FlaskConical, ArrowRight, PlusCircle } from 'lucide-react';

export default function Dashboard() {
  const [farmsList, setFarmsList] = useState<Farm[]>([]);
  const [selectedFarmId, setSelectedFarmId] = useState('');
  const [insights, setInsights] = useState<FarmInsights | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    farms.list().then(list => {
      setFarmsList(list);
      if (list.length && !selectedFarmId) setSelectedFarmId(list[0].id);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!selectedFarmId) { setInsights(null); return; }
    setLoading(true);
    farms.insights(selectedFarmId)
      .then(setInsights)
      .catch(() => setInsights(null))
      .finally(() => setLoading(false));
  }, [selectedFarmId]);

  const selectedFarm = farmsList.find(f => f.id === selectedFarmId);
  const needsSetup = !selectedFarm?.setup_complete && !insights?.has_data;

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-white">Home</h1>
          <p className="text-white/40 text-sm mt-1">Your farm at a glance</p>
        </div>
        <select
          className="bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white/80"
          value={selectedFarmId}
          onChange={e => setSelectedFarmId(e.target.value)}
        >
          <option value="">Select farm...</option>
          {farmsList.map(f => (
            <option key={f.id} value={f.id}>{f.name}</option>
          ))}
        </select>
      </div>

      {farmsList.length === 0 && (
        <div className="border border-moss-500/30 bg-moss-500/5 rounded-xl p-8 text-center mb-8">
          <h2 className="text-lg font-semibold text-white mb-2">Welcome to AI-SWAT+</h2>
          <p className="text-white/50 text-sm mb-4">Set up your first farm in a few guided steps.</p>
          <Link to="/setup" className="inline-flex items-center gap-2 bg-moss-600 hover:bg-moss-700 rounded-lg px-5 py-2.5 text-sm font-medium">
            <PlusCircle className="w-4 h-4" /> Set up your farm
          </Link>
        </div>
      )}

      {needsSetup && selectedFarmId && (
        <div className="border border-earth-400/30 bg-earth-400/5 rounded-xl p-5 mb-8 flex items-center justify-between">
          <div>
            <p className="font-medium text-white">Complete farm setup</p>
            <p className="text-sm text-white/40">Add field data and run your first simulation.</p>
          </div>
          <Link to={`/setup?farm=${selectedFarmId}`} className="text-moss-400 text-sm font-medium hover:text-moss-300 flex items-center gap-1">
            Continue setup <ArrowRight className="w-4 h-4" />
          </Link>
        </div>
      )}

      {loading ? (
        <p className="text-white/40 text-sm">Loading insights...</p>
      ) : insights?.has_data ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-5 mb-8">
          <InsightCard icon={Droplets} label="Irrigation" insight={insights.irrigation} />
          <InsightCard icon={Sprout} label="Fertilizer" insight={insights.fertilizer} />
          {insights.nitrate && <InsightCard icon={FlaskConical} label="Water Quality" insight={insights.nitrate} />}
          <InsightCard icon={MapPin} label="Drought Risk" insight={insights.drought_risk} />
          <InsightCard icon={Wheat} label="Yield" insight={insights.yield} />
        </div>
      ) : selectedFarmId && !needsSetup ? (
        <p className="text-white/40 text-sm mb-8">Run a simulation from Results to see insights here.</p>
      ) : null}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        <div className="border border-white/10 rounded-xl p-6">
          <h3 className="font-semibold text-white mb-1">Farm Advisor</h3>
          <p className="text-white/40 text-sm mb-4">Ask about irrigation, fertilizer, water quality, and crop decisions</p>
          <Link to="/chat" className="inline-flex items-center gap-2 text-moss-400 text-sm font-medium hover:text-moss-300">
            Open Advisor <ArrowRight className="w-4 h-4" />
          </Link>
        </div>
        <div className="border border-white/10 rounded-xl p-6">
          <h3 className="font-semibold text-white mb-1">Results</h3>
          <p className="text-white/40 text-sm mb-4">Water balance, nutrients, nitrate, and yield charts</p>
          <Link to="/visualizations" className="inline-flex items-center gap-2 text-moss-400 text-sm font-medium hover:text-moss-300">
            View Results <ArrowRight className="w-4 h-4" />
          </Link>
        </div>
        <div className="border border-white/10 rounded-xl p-6">
          <h3 className="font-semibold text-white mb-1">My Farms</h3>
          <p className="text-white/40 text-sm mb-4">Manage farms and field data</p>
          <Link to="/farms" className="inline-flex items-center gap-2 text-moss-400 text-sm font-medium hover:text-moss-300">
            Manage Farms <ArrowRight className="w-4 h-4" />
          </Link>
        </div>
        <div className="border border-white/10 rounded-xl p-6">
          <h3 className="font-semibold text-white mb-1">Farm Data</h3>
          <p className="text-white/40 text-sm mb-4">Setup progress, files, and what's missing</p>
          <Link to={selectedFarmId ? `/data?farm=${selectedFarmId}` : '/data'} className="inline-flex items-center gap-2 text-moss-400 text-sm font-medium hover:text-moss-300">
            Open Farm Data <ArrowRight className="w-4 h-4" />
          </Link>
        </div>
        <div className="border border-white/10 rounded-xl p-6">
          <h3 className="font-semibold text-white mb-1">Maps</h3>
          <p className="text-white/40 text-sm mb-4">Upload maps and set up field zones</p>
          <Link to="/gis" className="inline-flex items-center gap-2 text-moss-400 text-sm font-medium hover:text-moss-300">
            Open Maps <ArrowRight className="w-4 h-4" />
          </Link>
        </div>
      </div>
    </div>
  );
}
