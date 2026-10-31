import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Sprout, Trash2, Loader2 } from 'lucide-react';
import { useField } from '@/context/FieldContext';

// App-wide field selector. Lives above every page so the Advisor and the SWAT+
// Editor always open on the same field.
export default function FieldBar() {
  const { farms, selectedFarmId, selectField, createField, deleteField, requestSetup } = useField();
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  const onChange = async (v: string) => {
    if (v === '__new__') {
      const name = window.prompt('Name for the new field:', 'My field');
      if (!name?.trim()) return;
      setBusy(true);
      try {
        const farm = await createField(name.trim());
        // Kick off guided setup on the Advisor for the brand-new field.
        requestSetup(farm.id);
        navigate('/');
      } catch {
        window.alert('Could not create the field.');
      } finally {
        setBusy(false);
      }
      return;
    }
    selectField(v);
  };

  const onDelete = async () => {
    const f = farms.find(x => x.id === selectedFarmId);
    if (!f) return;
    if (!window.confirm(`Delete field "${f.name}" and all of its data (model files, GIS, runs, chats)? This cannot be undone.`)) {
      return;
    }
    setBusy(true);
    try {
      await deleteField(f.id);
    } catch {
      window.alert('Could not delete the field.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="h-12 shrink-0 flex items-center gap-2.5 px-4 border-b border-[var(--se-border)] bg-[var(--se-card)]">
      <Sprout className="w-4 h-4 text-[var(--se-accent)] shrink-0" />
      <span className="text-xs font-semibold text-[var(--se-text-mut)] shrink-0">Field</span>
      <div className="relative">
        <select
          className="min-w-[13rem] max-w-xs bg-white border border-[var(--se-border)] rounded-lg pl-3 pr-8 py-1.5 text-sm text-[var(--se-text)] focus:outline-none focus:border-[var(--se-accent)] disabled:opacity-50 appearance-none"
          value={selectedFarmId}
          onChange={e => onChange(e.target.value)}
          disabled={busy}
        >
          {!farms.length && <option value="">No fields yet — create one</option>}
          {farms.map(f => (
            <option key={f.id} value={f.id}>{f.name}</option>
          ))}
          <option value="__new__">+ Create new field…</option>
        </select>
        {busy && <Loader2 className="w-3.5 h-3.5 animate-spin text-[var(--se-text-fnt)] absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />}
      </div>
      <button
        type="button"
        onClick={onDelete}
        disabled={busy || !selectedFarmId}
        title="Delete this field and all its data"
        className="p-1.5 rounded-lg text-[var(--se-text-mut)] hover:text-[var(--se-error)] hover:bg-[var(--se-error-sf)] disabled:opacity-30 shrink-0"
      >
        <Trash2 className="w-4 h-4" />
      </button>
    </div>
  );
}
