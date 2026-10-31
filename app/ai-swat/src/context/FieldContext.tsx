import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';
import { farms as farmsApi, type Farm } from '@/lib/api';

// One shared "currently selected field" for the whole app. Both the Advisor and
// the SWAT+ Editor read from here, so picking a field in the top bar drives both.
const STORAGE_KEY = 'aiswat.selectedFarm';

interface FieldContextValue {
  farms: Farm[];
  loading: boolean;
  selectedFarmId: string;
  selectedFarm: Farm | null;
  selectField: (id: string) => void;
  refreshFarms: () => Promise<Farm[]>;
  createField: (name: string, location?: string) => Promise<Farm>;
  deleteField: (id: string) => Promise<void>;
  // One-shot flag: a freshly-created field that should be onboarded (the Advisor
  // picks this up and kicks off the setup conversation).
  setupFieldId: string;
  requestSetup: (id: string) => void;
  clearSetup: () => void;
}

const FieldContext = createContext<FieldContextValue | null>(null);

export function useField(): FieldContextValue {
  const ctx = useContext(FieldContext);
  if (!ctx) throw new Error('useField must be used within <FieldProvider>');
  return ctx;
}

export function FieldProvider({ children }: { children: ReactNode }) {
  const [searchParams] = useSearchParams();
  const [farms, setFarms] = useState<Farm[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedFarmId, setSelectedFarmId] = useState<string>(
    () => searchParams.get('farm') || localStorage.getItem(STORAGE_KEY) || '',
  );
  const [setupFieldId, setSetupFieldId] = useState('');

  const requestSetup = useCallback((id: string) => setSetupFieldId(id), []);
  const clearSetup = useCallback(() => setSetupFieldId(''), []);

  const persist = (id: string) => {
    if (id) localStorage.setItem(STORAGE_KEY, id);
    else localStorage.removeItem(STORAGE_KEY);
  };

  const selectField = useCallback((id: string) => {
    setSelectedFarmId(id);
    persist(id);
  }, []);

  const refreshFarms = useCallback(async () => {
    const list = await farmsApi.list();
    setFarms(list);
    setSelectedFarmId(prev => {
      const valid = prev && list.some(f => f.id === prev) ? prev : list[0]?.id || '';
      persist(valid);
      return valid;
    });
    setLoading(false);
    return list;
  }, []);

  useEffect(() => {
    refreshFarms().catch(() => setLoading(false));
  }, [refreshFarms]);

  const createField = useCallback(
    async (name: string, location = '') => {
      const farm = await farmsApi.create({ name: name.trim(), location: location.trim() });
      await refreshFarms();
      selectField(farm.id);
      return farm;
    },
    [refreshFarms, selectField],
  );

  const deleteField = useCallback(async (id: string) => {
    await farmsApi.delete(id);
    const list = await farmsApi.list();
    setFarms(list);
    setSelectedFarmId(prev => {
      const next = prev === id ? list[0]?.id || '' : prev;
      persist(next);
      return next;
    });
  }, []);

  const selectedFarm = farms.find(f => f.id === selectedFarmId) || null;

  return (
    <FieldContext.Provider
      value={{ farms, loading, selectedFarmId, selectedFarm, selectField, refreshFarms, createField, deleteField, setupFieldId, requestSetup, clearSetup }}
    >
      {children}
    </FieldContext.Provider>
  );
}
