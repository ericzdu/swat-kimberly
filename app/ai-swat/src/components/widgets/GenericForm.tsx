import { useMemo, useState } from 'react';
import clsx from 'clsx';
import type { Widget } from '@/lib/widgets';

type FieldType = 'number' | 'text' | 'select' | 'date' | 'toggle';

interface FieldOption {
  value: string;
  label: string;
}

interface FormField {
  id: string;
  type: FieldType;
  label: string;
  unit?: string;
  min?: number;
  max?: number;
  step?: number;
  options?: FieldOption[];
  required: boolean;
  suggested?: unknown;
  help?: string;
}

interface GenericFormPayload {
  submit_action: string;
  fields: FormField[];
}

type FormValue = string | number | boolean | null;

// Initialize a field's value from its `suggested` seed, coercing to the shape the
// control expects (checkbox → boolean, everything else → string for the input).
function initValue(field: FormField): FormValue {
  if (field.type === 'toggle') {
    return field.suggested === true;
  }
  if (field.suggested === undefined || field.suggested === null) {
    return '';
  }
  if (typeof field.suggested === 'number' || typeof field.suggested === 'boolean') {
    return String(field.suggested);
  }
  if (typeof field.suggested === 'string') {
    return field.suggested;
  }
  return '';
}

// Returns an error string for the field, or null when the value is acceptable.
function validateField(field: FormField, value: FormValue): string | null {
  if (field.type === 'toggle') {
    return null;
  }
  const raw = value == null ? '' : String(value);
  if (field.required && raw.trim() === '') {
    return 'Required';
  }
  if (field.type === 'number' && raw.trim() !== '') {
    const n = Number(raw);
    if (!Number.isFinite(n)) {
      return 'Enter a number';
    }
    if (field.min !== undefined && n < field.min) {
      return `Min ${field.min}`;
    }
    if (field.max !== undefined && n > field.max) {
      return `Max ${field.max}`;
    }
  }
  return null;
}

const inputClass =
  'mt-1 w-full bg-white border border-[var(--se-border)] rounded-lg px-3 py-2 text-sm text-[var(--se-text)] focus:outline-none focus:border-[var(--se-accent)]';

export default function GenericForm({ widget, onSubmit, disabled }: {
  widget: Widget;
  onSubmit: (w: Widget, data: Record<string, unknown>) => void;
  disabled?: boolean;
}) {
  const p = widget.payload as GenericFormPayload;
  const fields = p.fields || [];

  const [values, setValues] = useState<Record<string, FormValue>>(() => {
    const init: Record<string, FormValue> = {};
    for (const f of fields) {
      init[f.id] = initValue(f);
    }
    return init;
  });

  const setValue = (id: string, v: FormValue) => {
    setValues(prev => ({ ...prev, [id]: v }));
  };

  const errors = useMemo(() => {
    const e: Record<string, string | null> = {};
    for (const f of fields) {
      e[f.id] = validateField(f, values[f.id]);
    }
    return e;
  }, [fields, values]);

  const hasErrors = fields.some(f => errors[f.id] !== null);

  // Coerce each value to its final typed form before handing it back to the agent.
  const collect = (): Record<string, unknown> => {
    const out: Record<string, unknown> = {};
    for (const f of fields) {
      const v = values[f.id];
      if (f.type === 'toggle') {
        out[f.id] = v === true;
      } else if (f.type === 'number') {
        const raw = v == null ? '' : String(v);
        out[f.id] = raw.trim() === '' ? null : Number(raw);
      } else {
        out[f.id] = v == null ? '' : String(v);
      }
    }
    return out;
  };

  const submit = () => {
    if (disabled || hasErrors) return;
    onSubmit(widget, { values: collect(), submit_action: p.submit_action });
  };

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        {fields.map(field => {
          const err = errors[field.id];
          const value = values[field.id];

          if (field.type === 'toggle') {
            return (
              <label
                key={field.id}
                className="sm:col-span-2 flex items-center gap-2.5 text-xs text-[var(--se-text-mut)] cursor-pointer"
              >
                <input
                  type="checkbox"
                  className="w-4 h-4 rounded border-[var(--se-border)] bg-white accent-[var(--se-accent)]"
                  checked={value === true}
                  disabled={disabled}
                  onChange={e => setValue(field.id, e.target.checked)}
                />
                <span>
                  {field.label}
                  {field.help && (
                    <span className="block text-[11px] text-[var(--se-text-fnt)] mt-0.5">{field.help}</span>
                  )}
                </span>
              </label>
            );
          }

          return (
            <label key={field.id} className="block text-xs text-[var(--se-text-mut)]">
              <span className="flex items-center gap-1">
                {field.label}
                {field.unit && <span className="text-[var(--se-text-fnt)]">({field.unit})</span>}
                {field.required && <span className="text-[var(--se-warn)]">*</span>}
              </span>

              {field.type === 'select' ? (
                <select
                  className={inputClass}
                  value={value == null ? '' : String(value)}
                  disabled={disabled}
                  onChange={e => setValue(field.id, e.target.value)}
                >
                  <option value="">Select...</option>
                  {(field.options || []).map(o => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
              ) : (
                <input
                  type={field.type === 'number' ? 'number' : field.type === 'date' ? 'date' : 'text'}
                  className={clsx(inputClass, err && 'border-[var(--se-error)]')}
                  value={value == null ? '' : String(value)}
                  min={field.type === 'number' ? field.min : undefined}
                  max={field.type === 'number' ? field.max : undefined}
                  step={field.type === 'number' ? field.step : undefined}
                  disabled={disabled}
                  onChange={e => setValue(field.id, e.target.value)}
                />
              )}

              {field.help && (
                <span className="block text-[11px] text-[var(--se-text-fnt)] mt-1">{field.help}</span>
              )}
              {err && err !== 'Required' && (
                <span className="block text-[11px] text-[var(--se-error)] mt-1">{err}</span>
              )}
            </label>
          );
        })}
      </div>

      <button
        type="button"
        onClick={submit}
        disabled={disabled || hasErrors}
        className="w-full rounded-lg bg-[var(--se-accent)] hover:bg-[var(--se-accent-h)] text-white disabled:opacity-40 py-2.5 text-sm font-medium"
      >
        {widget.submit?.label || 'Save'}
      </button>
    </div>
  );
}
