import { useEffect, useState } from 'react';
import { farms, type CropSettings as CropSettingsType } from '@/lib/api';
import { Loader2, Sprout } from 'lucide-react';

interface Props {
  farmId: string;
  onSaved?: () => void;
}

export default function CropSettings({ farmId, onSaved }: Props) {
  const [settings, setSettings] = useState<CropSettingsType | null>(null);
  const [cropType, setCropType] = useState('');
  const [plantingDate, setPlantingDate] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    setLoading(true);
    farms
      .getCropSettings(farmId)
      .then(s => {
        setSettings(s);
        setCropType(s.crop_type || '');
        setPlantingDate(s.planting_date || '');
      })
      .catch(() => setError('Could not load crop settings'))
      .finally(() => setLoading(false));
  }, [farmId]);

  const save = async () => {
    setSaving(true);
    setError('');
    setMessage('');
    try {
      const res = await farms.saveCropSettings(farmId, cropType, plantingDate);
      setSettings(res);
      setMessage(res.message || 'Crop details saved.');
      onSaved?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-[var(--se-text-mut)] py-4">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading crop settings...
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-[var(--se-border)] bg-[var(--se-card)] p-4 space-y-3 shadow-sm">
      <div className="flex items-center gap-2">
        <Sprout className="w-4 h-4 text-[var(--se-accent)]" />
        <h3 className="text-sm font-medium text-[var(--se-text)]">Crop details</h3>
        {settings?.configured && (
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-[var(--se-ok-sf)] text-[var(--se-ok)] border border-[var(--se-ok-bd)]">
            Saved
          </span>
        )}
      </div>
      <p className="text-xs text-[var(--se-text-mut)]">
        Set your crop here in AI-SWAT+ — no QSWAT+ or external software needed. Required for yield estimates.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-xs text-[var(--se-text-mut)]">
          Crop type
          <select
            className="mt-1 w-full bg-white border border-[var(--se-border)] rounded-lg px-3 py-2 text-sm text-[var(--se-text)] focus:outline-none focus:border-[var(--se-accent)]"
            value={cropType}
            onChange={e => setCropType(e.target.value)}
          >
            <option value="">Select crop...</option>
            {(settings?.options || []).map(o => (
              <option key={o.id} value={o.id}>{o.label}</option>
            ))}
          </select>
        </label>
        <label className="block text-xs text-[var(--se-text-mut)]">
          Planting date
          <input
            type="date"
            className="mt-1 w-full bg-white border border-[var(--se-border)] rounded-lg px-3 py-2 text-sm text-[var(--se-text)] focus:outline-none focus:border-[var(--se-accent)]"
            value={plantingDate}
            onChange={e => setPlantingDate(e.target.value)}
          />
        </label>
      </div>
      {error && <p className="text-xs text-[var(--se-error)]">{error}</p>}
      {message && <p className="text-xs text-[var(--se-ok)]">{message}</p>}
      <button
        type="button"
        onClick={save}
        disabled={saving || !cropType || !plantingDate}
        className="text-sm px-4 py-2 rounded-lg bg-[var(--se-accent)] hover:bg-[var(--se-accent-h)] text-white disabled:opacity-40"
      >
        {saving ? 'Saving...' : 'Save crop details'}
      </button>
    </div>
  );
}
