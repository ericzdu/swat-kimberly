import { useCallback, useEffect, useState, useRef } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  farms,
  chat,
  data,
  system,
  type FarmReadiness,
  type AiStatus,
  type ChatSession,
  type ChatMessage,
} from '@/lib/api';
import { Send, Bot, User, Loader2, AlertTriangle, Settings2, Plus, MessageSquare, Trash2, Paperclip, Sparkles, LayoutPanelLeft, Clock, Check } from 'lucide-react';
import clsx from 'clsx';
import AssistantMarkdown from '@/components/AssistantMarkdown';
import WidgetView from '@/components/widgets/WidgetView';
import GuidedSetup from '@/components/GuidedSetup';
import FieldReport from '@/components/FieldReport';
import { useField } from '@/context/FieldContext';
import type { ChatAnalysisCard as AnalysisCard } from '@/lib/api';
import type { Widget, CanvasPhase } from '@/lib/widgets';

/** INTERACTIVE widgets destined for the canvas pane (need the farmer's input).
 *  All of them render — so the AI can ask one question or several at once. */
function pickInteractiveWidgets(widgets?: Widget[]): Widget[] {
  return (widgets || []).filter(w => w.interactive);
}

/** Output-only widgets (charts, cards, checklists) shown stacked in the canvas. */
function pickOutputWidgets(widgets?: Widget[]): Widget[] {
  return (widgets || []).filter(w => !w.interactive);
}

/** Size the canvas column to the widgets it holds: maps want room, choices stay tight. */
function canvasMaxWidth(widgets: Widget[]): string {
  if (widgets.some(w => w.kind === 'map-draw' || w.kind === 'swat-editor-panel')) return 'max-w-5xl';
  if (widgets.some(w => w.kind === 'form' || w.kind === 'file-upload' || w.kind === 'field-picker')) return 'max-w-3xl';
  if (widgets.some(w => w.kind === 'choice' || w.kind === 'confirm')) return 'max-w-xl';
  return 'max-w-2xl';
}

interface Message {
  id?: string;
  role: 'user' | 'assistant';
  content: string;
  tools_used?: string[];
  cards?: AnalysisCard[];
}

const WELCOME: Message = {
  role: 'assistant',
  content: "Hi — I'm your farm advisor. Pick a field on the left, then ask me anything. I'll open maps, charts, and forms in the workspace as we go.",
};

function fieldNameFromFile(file: File): string {
  const base = file.name.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ').trim();
  return base.slice(0, 48) || 'New field';
}

const SETUP_ACTIONS = [
  {
    label: 'Set up this field',
    message: 'Set up this field completely for SWAT+. Use auto_setup_field_for_swat: find or use my boundary, download elevation soil and weather, build the field model, set crop if needed, and run the first simulation. Summarize what you populated.',
  },
  {
    label: 'Draw my field on a map',
    message: 'Show me a map so I can draw my field boundary, then download data and build the model.',
  },
  {
    label: 'Use my uploaded files',
    message: 'I uploaded field data to the inbox. Use inspect_uploaded_field_files, then setup_field_from_uploaded_files to classify, sort, populate SWAT+ datasets, and build the field model. Tell me what each file became.',
  },
  {
    label: "What's missing?",
    message: 'What datasets are ready for this field and what is still missing? Use request_dataset_status and explain in simple terms.',
  },
  {
    label: 'Create new field',
    message: 'I want to open a new field in AI-SWAT+. Ask me what to name it and where it is, then create it after I confirm.',
  },
];

const QUICK_ACTIONS = [
  { label: 'Should I irrigate today?', message: 'Should I irrigate today? Use run_irrigation_analysis and advise me.', needsReady: true },
  { label: 'When to fertilize?', message: 'When should I apply fertilizer? Use run_fertilizer_analysis.', needsReady: true },
  { label: 'Check my water quality', message: 'How is the nitrate / water quality on my field? Use run_nitrate_analysis. Tell me how much nitrogen is leaching to groundwater and the creek, and how to reduce it.', needsReady: true },
  { label: 'What yield can I expect?', message: 'What yield can I expect? Use run_yield_analysis.', needsReady: true },
  { label: 'Explain my last results', message: 'Explain my last simulation results in simple terms using the tools.', needsReady: true },
];

function formatSessionDate(iso: string) {
  if (!iso) return '';
  const d = new Date(iso);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  if (sameDay) {
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

function toUiMessages(rows: ChatMessage[]): Message[] {
  return rows
    .filter(m => m.role === 'user' || m.role === 'assistant')
    .map(m => ({
      id: m.id,
      role: m.role as 'user' | 'assistant',
      content: m.content,
      tools_used: m.tools_used,
      cards: m.cards,
    }));
}

const PHASE_STEPS: { key: CanvasPhase; label: string }[] = [
  { key: 'collecting', label: 'Collect' },
  { key: 'running', label: 'Run' },
  { key: 'results', label: 'Results' },
];

function PhaseStepper({ phase }: { phase: CanvasPhase }) {
  const activeIdx = PHASE_STEPS.findIndex(s => s.key === phase);
  return (
    <div className="flex items-center gap-1.5">
      {PHASE_STEPS.map((s, i) => {
        const done = activeIdx > i && activeIdx !== -1;
        const active = activeIdx === i;
        return (
          <div key={s.key} className="flex items-center gap-1.5">
            <span
              className={clsx(
                'flex items-center gap-1 text-[11px] font-medium rounded-full px-2 py-0.5 border transition-colors',
                active && 'bg-[var(--se-accent-sf)] text-[var(--se-accent)] border-[var(--se-accent-bd)]',
                done && 'text-[var(--se-ok)] border-transparent',
                !active && !done && 'text-[var(--se-text-fnt)] border-transparent',
              )}
            >
              {done ? <Check className="w-3 h-3" /> : <span className={clsx('w-1.5 h-1.5 rounded-full', active ? 'bg-[var(--se-accent)]' : 'bg-[var(--se-border)]')} />}
              {s.label}
            </span>
            {i < PHASE_STEPS.length - 1 && <span className={clsx('w-4 h-px', done ? 'bg-[var(--se-ok)]' : 'bg-[var(--se-border)]')} />}
          </div>
        );
      })}
    </div>
  );
}

export default function Chat() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { farms: farmsList, selectedFarmId: selectedFarm, selectField, createField, refreshFarms, setupFieldId, clearSetup } = useField();
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState(searchParams.get('session') || '');
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [readiness, setReadiness] = useState<FarmReadiness | null>(null);
  const [messages, setMessages] = useState<Message[]>([WELCOME]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [aiStatus, setAiStatus] = useState<AiStatus | null>(null);
  const [aiSettings, setAiSettings] = useState({ provider: '', model: '' });
  const bottomRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadHint, setUploadHint] = useState('');
  const [uploadTargetOpen, setUploadTargetOpen] = useState(false);
  const [pendingUploadFiles, setPendingUploadFiles] = useState<File[]>([]);
  const [uploadNewFieldName, setUploadNewFieldName] = useState('');
  const [uploadExistingFarmId, setUploadExistingFarmId] = useState('');
  const [canvasWidgets, setCanvasWidgets] = useState<Widget[]>([]);
  const [canvasBusy, setCanvasBusy] = useState(false);
  const [phase, setPhase] = useState<CanvasPhase>('idle');
  const [lastResultWidgets, setLastResultWidgets] = useState<Widget[]>([]);
  const [reportKey, setReportKey] = useState(0);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [pane, setPane] = useState<'chat' | 'canvas'>('canvas');

  const syncUrl = useCallback((farmId: string, sessionId: string) => {
    const next = new URLSearchParams();
    if (farmId) next.set('farm', farmId);
    if (sessionId) next.set('session', sessionId);
    setSearchParams(next, { replace: true });
  }, [setSearchParams]);

  useEffect(() => {
    chat.status().then(setAiStatus).catch(() => {});
    system.getSettings().then(setAiSettings).catch(() => {});
  }, []);

  const loadSessions = useCallback(async (farmId: string, preferSessionId?: string) => {
    if (!farmId) {
      setSessions([]);
      setActiveSessionId('');
      setMessages([WELCOME]);
      return;
    }
    setSessionsLoading(true);
    try {
      const list = await chat.listSessions(farmId);
      setSessions(list);
      const pick = preferSessionId && list.some(s => s.id === preferSessionId)
        ? preferSessionId
        : list[0]?.id || '';
      setActiveSessionId(pick);
      syncUrl(farmId, pick);
      if (!pick) {
        setMessages([WELCOME]);
      }
    } catch {
      setSessions([]);
      setMessages([WELCOME]);
    } finally {
      setSessionsLoading(false);
    }
  }, [syncUrl]);

  const loadSessionMessages = useCallback(async (sessionId: string) => {
    if (!sessionId) {
      setMessages([WELCOME]);
      return;
    }
    setMessagesLoading(true);
    try {
      const detail = await chat.getSession(sessionId);
      const ui = toUiMessages(detail.messages);
      setMessages(ui.length > 0 ? ui : [WELCOME]);
    } catch {
      setMessages([WELCOME]);
    } finally {
      setMessagesLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!selectedFarm) {
      setReadiness(null);
      setSessions([]);
      setActiveSessionId('');
      setMessages([WELCOME]);
      return;
    }
    farms.readiness(selectedFarm).then(setReadiness).catch(() => setReadiness(null));
    const sessionFromUrl = searchParams.get('session') || '';
    loadSessions(selectedFarm, sessionFromUrl || activeSessionId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedFarm]);

  useEffect(() => {
    if (activeSessionId) {
      loadSessionMessages(activeSessionId);
    }
  }, [activeSessionId, loadSessionMessages]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  // A freshly-created field routes here flagged for setup. Just surface the
  // workspace so the setup prompt (below) is front-and-centre. Deterministic —
  // no agent call, so creating a field can never trigger a model action on its own.
  useEffect(() => {
    if (setupFieldId && setupFieldId === selectedFarm) {
      clearSetup();
      setPane('canvas');
    }
  }, [setupFieldId, selectedFarm, clearSetup]);

  const startNewSession = async () => {
    if (!selectedFarm) return;
    setHistoryOpen(false);
    try {
      const session = await chat.createSession(selectedFarm);
      setSessions(prev => [session, ...prev]);
      setActiveSessionId(session.id);
      setMessages([WELCOME]);
      syncUrl(selectedFarm, session.id);
    } catch {
      // ignore
    }
  };

  const selectSession = (sessionId: string) => {
    setActiveSessionId(sessionId);
    syncUrl(selectedFarm, sessionId);
  };

  const deleteSession = async (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm('Delete this chat?')) return;
    try {
      await chat.deleteSession(sessionId);
      const remaining = sessions.filter(s => s.id !== sessionId);
      setSessions(remaining);
      if (activeSessionId === sessionId) {
        const next = remaining[0]?.id || '';
        setActiveSessionId(next);
        syncUrl(selectedFarm, next);
        if (!next) setMessages([WELCOME]);
      }
    } catch {
      // ignore
    }
  };

  const appendAssistant = (content: string, extra?: Partial<Message>) => {
    setMessages(m => [...m, { role: 'assistant', content, ...extra }]);
  };

  // Field selection is owned by the shared FieldBar/context; here we only forward.
  const selectFarm = useCallback((farmId: string) => {
    selectField(farmId);
  }, [selectField]);

  const createFieldByName = async (name: string, location = '') => {
    return createField(name, location);
  };

  const performUpload = async (files: File[], farmId: string, farmName: string) => {
    setUploading(true);
    setUploadHint('');
    const names: string[] = [];
    let lastCount = 0;
    try {
      for (const file of files) {
        const res = await data.uploadInbox(farmId, file);
        names.push(file.name);
        lastCount = res.file_count;
      }
      appendAssistant(
        `Uploaded **${names.join('**, **')}** to field **${farmName}** (${lastCount} file(s) in inbox). ` +
        `Say "use my uploaded files" and I will classify each file and build your SWAT+ setup.`,
      );
    } catch (e) {
      appendAssistant(`Upload failed: ${e instanceof Error ? e.message : 'unknown error'}`);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const confirmUploadTarget = async () => {
    if (!pendingUploadFiles.length) {
      setUploadTargetOpen(false);
      return;
    }
    let farmId = selectedFarm;
    let farmName = farmsList.find(f => f.id === farmId)?.name || '';

    if (!farmId) {
      if (uploadExistingFarmId) {
        farmId = uploadExistingFarmId;
        farmName = farmsList.find(f => f.id === farmId)?.name || farmName;
        selectFarm(farmId);
      } else {
        const name = uploadNewFieldName.trim();
        if (!name) {
          setUploadHint('Enter a name for the new field, or pick an existing one.');
          return;
        }
        try {
          const farm = await createFieldByName(name);
          farmId = farm.id;
          farmName = farm.name;
        } catch (e) {
          appendAssistant(`Could not create field: ${e instanceof Error ? e.message : 'unknown error'}`);
          return;
        }
      }
    }

    setUploadTargetOpen(false);
    const files = pendingUploadFiles;
    setPendingUploadFiles([]);
    await performUpload(files, farmId, farmName);
  };

  const cancelUploadTarget = () => {
    setUploadTargetOpen(false);
    setPendingUploadFiles([]);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const refreshSessions = async (farmId: string, sessionId: string) => {
    try {
      const list = await chat.listSessions(farmId);
      setSessions(list);
      if (sessionId) setActiveSessionId(sessionId);
    } catch {
      // ignore
    }
  };

  const sendMessage = async (text: string) => {
    if (!text.trim() || !selectedFarm || loading) return;

    let sessionId = activeSessionId;
    if (!sessionId) {
      try {
        const session = await chat.createSession(selectedFarm);
        sessionId = session.id;
        setSessions(prev => [session, ...prev]);
        setActiveSessionId(sessionId);
        syncUrl(selectedFarm, sessionId);
      } catch {
        appendAssistant('Could not start a chat session. Try again.');
        return;
      }
    }

    setMessages(m => [...m, { role: 'user', content: text }]);
    setLoading(true);
    try {
      const res = await chat.send(selectedFarm, text, {
        provider: aiSettings.provider,
        model: aiSettings.model,
        useAgent: true,
        sessionId,
      });
      if (res.session_id && res.session_id !== sessionId) {
        setActiveSessionId(res.session_id);
        syncUrl(selectedFarm, res.session_id);
        sessionId = res.session_id;
      }
      appendAssistant(res.response, {
        tools_used: res.tools_used,
        cards: res.cards,
      });
      {
        const iws = pickInteractiveWidgets(res.widgets);
        const outs = pickOutputWidgets(res.widgets);
        // Keep output widgets (charts/tables) even when the same turn also asks a question, so
        // they aren't dropped; interactive widgets take the canvas first, results wait behind them.
        if (outs.length) setLastResultWidgets(outs);
        if (iws.length) { setCanvasWidgets(iws); setPhase('collecting'); setPane('canvas'); }
        else if (outs.length) { setCanvasWidgets([]); setPhase('results'); setPane('canvas'); }
      }
      // After any analysis run, refresh the field report + readiness so the canvas shows the new results.
      if ((res.tools_used || []).some(t => t.startsWith('run_'))) {
        setReportKey(k => k + 1);
        farms.readiness(selectedFarm).then(setReadiness).catch(() => {});
        setPane('canvas');
      }
      if (res.created_farm_id) {
        const list = await refreshFarms();
        const created = list.find(f => f.id === res.created_farm_id);
        if (created) {
          selectFarm(res.created_farm_id);
          appendAssistant(`Switched to your new field **${created.name}**. You can upload data or ask me to set it up.`);
          await refreshSessions(res.created_farm_id, sessionId);
          return;
        }
      }
      await refreshSessions(selectedFarm, sessionId);
    } catch (e) {
      const err = e instanceof Error ? e.message : 'Unknown error';
      appendAssistant(`Could not reach the AI: ${err}. Open Settings and connect your AI provider.`);
    } finally {
      setLoading(false);
    }
  };

  const send = () => sendMessage(input).then(() => setInput(''));

  const handleWidgetSubmit = async (widget: Widget, data: Record<string, unknown>) => {
    if (!selectedFarm || canvasBusy) return;
    const sessionId = activeSessionId;
    setCanvasBusy(true);
    const label =
      (data.label as string) ||
      (data.confirmed !== undefined ? (data.confirmed ? 'Yes' : 'No') : '');
    if (label) setMessages(m => [...m, { role: 'user', content: label }]);
    setLoading(true);
    try {
      const res = await chat.interact(selectedFarm, sessionId, widget.widget_id, widget.kind, data, {
        provider: aiSettings.provider,
        model: aiSettings.model,
      });
      appendAssistant(res.response, { tools_used: res.tools_used, cards: res.cards });
      const iws = pickInteractiveWidgets(res.widgets);
      const outs = pickOutputWidgets(res.widgets);
      setCanvasWidgets(iws);
      if (outs.length) setLastResultWidgets(outs);
      setPhase(iws.length ? 'collecting' : (outs.length ? 'results' : 'idle'));
      await refreshSessions(selectedFarm, res.session_id || sessionId);
    } catch (e) {
      appendAssistant(`Could not submit that: ${e instanceof Error ? e.message : 'unknown error'}`);
    } finally {
      setCanvasBusy(false);
      setLoading(false);
    }
  };

  const onFilesSelected = async (fileList: FileList | null) => {
    if (!fileList?.length || uploading) return;
    const files = Array.from(fileList);
    setUploadHint('');

    if (!selectedFarm) {
      setPendingUploadFiles(files);
      setUploadNewFieldName(fieldNameFromFile(files[0]));
      setUploadExistingFarmId('');
      setUploadTargetOpen(true);
      if (fileInputRef.current) fileInputRef.current.value = '';
      return;
    }

    const farmName = farmsList.find(f => f.id === selectedFarm)?.name || 'this field';
    await performUpload(files, selectedFarm, farmName);
  };

  const openFilePicker = () => {
    if (uploading) return;
    fileInputRef.current?.click();
  };

  const warnings = readiness?.checks.filter(c => c.status === 'missing' || c.status === 'warning') || [];
  const idleActions = readiness?.ready_to_simulate ? QUICK_ACTIONS : SETUP_ACTIONS;
  const canvasTitle = canvasWidgets[0]?.title || (lastResultWidgets.length ? 'Results' : 'Workspace');

  return (
    <div className="flex h-full min-h-0 bg-[var(--se-bg)] text-[var(--se-text)] relative">
      {/* ===================== CHAT SIDE PANEL ===================== */}
      <aside className={clsx(
        'w-full lg:w-[380px] xl:w-[400px] shrink-0 min-w-0 flex-col border-r border-[var(--se-border)] bg-[var(--se-card)]',
        pane === 'chat' ? 'flex' : 'hidden lg:flex',
      )}>
        {/* Header */}
        <div className="px-4 pt-3.5 pb-3 border-b border-[var(--se-border)] space-y-3">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg bg-[var(--se-accent)] flex items-center justify-center shrink-0 shadow-sm">
              <Bot className="w-4 h-4 text-white" />
            </div>
            <div className="min-w-0">
              <h1 className="text-sm font-semibold leading-tight">Advisor</h1>
              <p className="text-[11px] text-[var(--se-text-fnt)] leading-tight truncate">
                {aiStatus?.configured
                  ? `${aiStatus.provider}${aiStatus.model ? ' · ' + aiStatus.model : ''}`
                  : 'AI not connected'}
              </p>
            </div>
            <div className="ml-auto flex items-center gap-0.5">
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setHistoryOpen(o => !o)}
                  disabled={!selectedFarm}
                  title="Chat history"
                  className="p-1.5 rounded-lg text-[var(--se-text-mut)] hover:text-[var(--se-text)] hover:bg-[var(--se-rail)] disabled:opacity-30"
                >
                  <Clock className="w-4 h-4" />
                </button>
                {historyOpen && (
                  <>
                    <div className="fixed inset-0 z-20" onClick={() => setHistoryOpen(false)} />
                    <div className="absolute right-0 top-full mt-1.5 w-72 z-30 rounded-xl border border-[var(--se-border)] bg-[var(--se-card)] shadow-lg p-1.5 max-h-[70vh] overflow-y-auto">
                      {sessionsLoading && (
                        <div className="flex justify-center py-4"><Loader2 className="w-4 h-4 animate-spin text-[var(--se-text-fnt)]" /></div>
                      )}
                      {!sessionsLoading && sessions.length === 0 && (
                        <p className="text-xs text-[var(--se-text-fnt)] px-2 py-3">No saved chats yet.</p>
                      )}
                      {sessions.map(s => (
                        <div
                          key={s.id}
                          role="button"
                          tabIndex={0}
                          onClick={() => { selectSession(s.id); setHistoryOpen(false); }}
                          onKeyDown={e => { if (e.key === 'Enter') { selectSession(s.id); setHistoryOpen(false); } }}
                          className={clsx(
                            'group rounded-lg px-2.5 py-2 cursor-pointer flex items-start gap-2 border',
                            s.id === activeSessionId ? 'bg-[var(--se-accent-sf)] border-[var(--se-accent-bd)]' : 'hover:bg-[var(--se-rail)] border-transparent',
                          )}
                        >
                          <MessageSquare className="w-3.5 h-3.5 shrink-0 mt-0.5 text-[var(--se-text-fnt)]" />
                          <div className="min-w-0 flex-1">
                            <p className="text-xs font-medium truncate">{s.title}</p>
                            <p className="text-[10px] text-[var(--se-text-fnt)] truncate mt-0.5">{s.last_preview || `${s.message_count} messages`}</p>
                          </div>
                          <span className="text-[10px] text-[var(--se-text-fnt)] shrink-0 mt-0.5">{formatSessionDate(s.updated_at)}</span>
                          <button
                            type="button"
                            onClick={e => deleteSession(s.id, e)}
                            className="opacity-0 group-hover:opacity-100 p-0.5 text-[var(--se-text-fnt)] hover:text-[var(--se-error)] shrink-0"
                            title="Delete chat"
                          >
                            <Trash2 className="w-3 h-3" />
                          </button>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>
              <button
                type="button"
                onClick={startNewSession}
                disabled={!selectedFarm}
                title="New chat"
                className="p-1.5 rounded-lg text-[var(--se-text-mut)] hover:text-[var(--se-text)] hover:bg-[var(--se-rail)] disabled:opacity-30"
              >
                <Plus className="w-4 h-4" />
              </button>
              <Link to="/settings" title="Settings" className="p-1.5 rounded-lg text-[var(--se-text-mut)] hover:text-[var(--se-text)] hover:bg-[var(--se-rail)]">
                <Settings2 className="w-4 h-4" />
              </Link>
            </div>
          </div>

          {!aiStatus?.configured && (
            <div className="flex items-start gap-2 text-[11px] text-[var(--se-warn)] bg-[var(--se-warn-sf)] border border-[var(--se-warn-bd)] rounded-lg px-2.5 py-1.5">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
              <span>Connect an AI provider in <Link to="/settings" className="text-[var(--se-accent)] underline">Settings</Link>.</span>
            </div>
          )}
          {selectedFarm && readiness && !readiness.ready_to_simulate && aiStatus?.configured && (
            <div className="flex items-start gap-2 text-[11px] text-[var(--se-accent)] bg-[var(--se-accent-sf)] border border-[var(--se-accent-bd)] rounded-lg px-2.5 py-1.5">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
              <span>This field isn't set up yet — tell me its location or draw it on a map to begin.</span>
            </div>
          )}
          {selectedFarm && warnings.length > 0 && (
            <div className="flex items-start gap-2 text-[11px] text-[var(--se-warn)] bg-[var(--se-warn-sf)] border border-[var(--se-warn-bd)] rounded-lg px-2.5 py-1.5">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
              <span>{warnings.map(w => w.label).join(', ')} — results may be less accurate.</span>
            </div>
          )}
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4 min-h-0">
          {messagesLoading && (
            <div className="flex justify-center py-8"><Loader2 className="w-5 h-5 animate-spin text-[var(--se-accent)]" /></div>
          )}
          {!messagesLoading && messages.map((msg, i) => (
            <div key={msg.id || i} className={clsx('flex gap-2.5', msg.role === 'user' ? 'justify-end' : 'justify-start')}>
              {msg.role === 'assistant' && (
                <div className="w-7 h-7 rounded-full bg-[var(--se-accent-sf)] flex items-center justify-center shrink-0 mt-0.5">
                  <Bot className="w-3.5 h-3.5 text-[var(--se-accent)]" />
                </div>
              )}
              <div className={clsx(
                'max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed',
                msg.role === 'user'
                  ? 'bg-[var(--se-accent)] text-white'
                  : 'bg-[var(--se-rail)] border border-[var(--se-border)]',
              )}>
                {msg.role === 'assistant' ? (
                  <AssistantMarkdown text={msg.content} />
                ) : (
                  <p className="whitespace-pre-wrap">{msg.content}</p>
                )}
                {msg.tools_used && msg.tools_used.filter(t => t.startsWith('run_')).length > 0 && (
                  <p className="text-[var(--se-text-fnt)] text-[10px] mt-2 pt-1.5 border-t border-[var(--se-border)]">
                    Ran: {msg.tools_used.filter(t => t.startsWith('run_')).map(t => t.replace('run_', '').replace('_analysis', '')).join(', ')}
                  </p>
                )}
              </div>
              {msg.role === 'user' && (
                <div className="w-7 h-7 rounded-full bg-[var(--se-rail)] border border-[var(--se-border)] flex items-center justify-center shrink-0 mt-0.5">
                  <User className="w-3.5 h-3.5 text-[var(--se-text-mut)]" />
                </div>
              )}
            </div>
          ))}
          {loading && (
            <div className="flex gap-2.5">
              <div className="w-7 h-7 rounded-full bg-[var(--se-accent-sf)] flex items-center justify-center">
                <Bot className="w-3.5 h-3.5 text-[var(--se-accent)]" />
              </div>
              <div className="bg-[var(--se-rail)] border border-[var(--se-border)] rounded-2xl px-3.5 py-2.5">
                <Loader2 className="w-4 h-4 animate-spin text-[var(--se-accent)]" />
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Quick actions + composer */}
        <div className="border-t border-[var(--se-border)] px-4 py-3 space-y-2.5 shrink-0">
          {selectedFarm && aiStatus?.configured && readiness?.ready_to_simulate && (
            <div className="flex gap-1.5 overflow-x-auto pb-1 -mb-1">
              {idleActions.slice(0, 5).map(({ label, message }) => (
                <button
                  key={label}
                  onClick={() => sendMessage(message)}
                  disabled={loading}
                  className="shrink-0 text-[11px] px-2.5 py-1 rounded-full bg-white border border-[var(--se-border)] text-[var(--se-text-mut)] hover:border-[var(--se-accent)] hover:text-[var(--se-accent)] transition-colors disabled:opacity-40 whitespace-nowrap"
                >
                  {label}
                </button>
              ))}
            </div>
          )}
          <input
            id="chat-file-upload"
            ref={fileInputRef}
            type="file"
            className="sr-only"
            multiple
            accept=".zip,.tif,.tiff,.csv,.json,.geojson,.shp,.kml,.gpkg,.pcp,.tem,.cli,application/zip,image/tiff,text/csv,application/json,application/geo+json"
            onChange={e => onFilesSelected(e.target.files)}
          />
          {uploadHint && <p className="text-xs text-[var(--se-warn)]">{uploadHint}</p>}
          <div className="flex gap-2 items-end">
            <button
              type="button"
              onClick={openFilePicker}
              disabled={uploading}
              className="p-2.5 rounded-xl border border-[var(--se-border)] bg-white hover:border-[var(--se-accent)] disabled:opacity-40 inline-flex items-center justify-center shrink-0"
              title="Upload field data (zip, DEM, CSV, GeoJSON…)"
            >
              {uploading ? <Loader2 className="w-5 h-5 animate-spin text-[var(--se-accent)]" /> : <Paperclip className="w-5 h-5 text-[var(--se-text-mut)]" />}
            </button>
            <textarea
              className="flex-1 min-w-0 bg-white border border-[var(--se-border)] rounded-xl px-3.5 py-2.5 text-sm resize-none focus:outline-none focus:border-[var(--se-accent)] max-h-32"
              placeholder={selectedFarm ? 'Ask about irrigation, water quality, yield…' : 'Select a field first…'}
              rows={1}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
            />
            <button
              onClick={send}
              disabled={!input.trim() || !selectedFarm || loading}
              className="p-2.5 rounded-xl bg-[var(--se-accent)] hover:bg-[var(--se-accent-h)] text-white disabled:opacity-40 shrink-0"
              title="Send"
            >
              <Send className="w-5 h-5" />
            </button>
          </div>
        </div>
      </aside>

      {/* ===================== CANVAS (MAIN STAGE) ===================== */}
      <main className={clsx('flex-1 flex-col min-w-0 min-h-0 bg-[var(--se-bg)]', pane === 'canvas' ? 'flex' : 'hidden lg:flex')}>
        <div className="flex items-center gap-3 px-6 py-3 border-b border-[var(--se-border)] shrink-0 bg-[var(--se-card)]">
          <LayoutPanelLeft className="w-4 h-4 text-[var(--se-accent)]" />
          <span className="text-sm font-medium truncate">{canvasTitle}</span>
          <div className="ml-auto"><PhaseStepper phase={phase} /></div>
        </div>
        <div className="flex-1 overflow-y-auto min-h-0">
          <div
            key={`${canvasWidgets.map(w => w.widget_id).join(',') || 'out'}-${lastResultWidgets.length}-${phase}`}
            className={clsx(
              'mx-auto px-6 py-6 h-full se-fade-in',
              canvasWidgets.length ? canvasMaxWidth(canvasWidgets) : 'max-w-5xl',
            )}
          >
            {canvasWidgets.length > 0 ? (
              <div className="space-y-5">
                {canvasWidgets.map((w, i) => (
                  <div key={w.widget_id} className="bg-[var(--se-card)] border border-[var(--se-border)] rounded-xl p-5 shadow-sm">
                    {canvasWidgets.length > 1 && (
                      <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--se-text-fnt)] mb-2">
                        Question {i + 1} of {canvasWidgets.length}
                      </p>
                    )}
                    {w.prompt && w.kind !== 'choice' && w.kind !== 'confirm' && (
                      <p className="text-sm text-[var(--se-text-mut)] mb-4">{w.prompt}</p>
                    )}
                    <WidgetView widget={w} onSubmit={handleWidgetSubmit} disabled={canvasBusy} farmId={selectedFarm} />
                  </div>
                ))}
              </div>
            ) : lastResultWidgets.length > 0 ? (
              <div className="space-y-4">
                <button onClick={() => setLastResultWidgets([])}
                  className="text-xs text-[var(--se-text-mut)] hover:text-[var(--se-accent)] flex items-center gap-1">
                  ← Back to field overview
                </button>
                {lastResultWidgets.map(w => (
                  <WidgetView key={w.widget_id} widget={w} onSubmit={handleWidgetSubmit} disabled={canvasBusy} farmId={selectedFarm} />
                ))}
              </div>
            ) : selectedFarm && readiness && !readiness.ready_to_simulate ? (
              <GuidedSetup
                farmId={selectedFarm}
                farmName={readiness.farm_name || farmsList.find(f => f.id === selectedFarm)?.name || ''}
                onComplete={() => { farms.readiness(selectedFarm).then(setReadiness).catch(() => {}); }}
              />
            ) : selectedFarm && readiness ? (
              <FieldReport farmId={selectedFarm} reloadKey={reportKey} onAsk={sendMessage} />
            ) : (
              <div className="h-full min-h-[55vh] flex flex-col items-center justify-center text-center">
                <div className="w-14 h-14 rounded-2xl bg-[var(--se-accent-sf)] flex items-center justify-center mb-4">
                  <Sparkles className="w-7 h-7 text-[var(--se-accent)]" />
                </div>
                {!selectedFarm ? (
                  <>
                    <p className="text-lg font-semibold">Pick a field to begin</p>
                    <p className="text-sm text-[var(--se-text-mut)] mt-1.5 max-w-sm">Choose or create a field in the bar above. Maps, charts, and results will appear here as we work.</p>
                  </>
                ) : (
                  <p className="text-sm text-[var(--se-text-mut)]">Loading your field…</p>
                )}
              </div>
            )}
          </div>
        </div>
      </main>

      {/* Responsive pane toggle (small screens only) */}
      <div className="lg:hidden fixed bottom-4 left-1/2 -translate-x-1/2 z-40 flex rounded-full border border-[var(--se-border)] bg-[var(--se-card)] shadow-lg overflow-hidden text-sm">
        <button
          onClick={() => setPane('chat')}
          className={clsx('flex items-center gap-1.5 px-4 py-2', pane === 'chat' ? 'bg-[var(--se-accent)] text-white' : 'text-[var(--se-text-mut)]')}
        >
          <MessageSquare className="w-4 h-4" /> Chat
        </button>
        <button
          onClick={() => setPane('canvas')}
          className={clsx('flex items-center gap-1.5 px-4 py-2', pane === 'canvas' ? 'bg-[var(--se-accent)] text-white' : 'text-[var(--se-text-mut)]')}
        >
          <LayoutPanelLeft className="w-4 h-4" /> Workspace
        </button>
      </div>

      {uploadTargetOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-2xl border border-[var(--se-border)] bg-[var(--se-card)] p-5 shadow-xl space-y-4">
            <h2 className="text-base font-semibold">Where should these files go?</h2>
            <p className="text-xs text-[var(--se-text-mut)]">
              {pendingUploadFiles.length} file(s):{' '}
              {pendingUploadFiles.map(f => f.name).join(', ').slice(0, 120)}
              {pendingUploadFiles.map(f => f.name).join(', ').length > 120 ? '…' : ''}
            </p>

            <div className="space-y-2">
              <label className="text-xs text-[var(--se-text-mut)] block">New field name</label>
              <input
                type="text"
                className="w-full bg-white border border-[var(--se-border)] rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-[var(--se-accent)]"
                value={uploadNewFieldName}
                onChange={e => { setUploadNewFieldName(e.target.value); setUploadExistingFarmId(''); }}
                placeholder="e.g. 1 hru test field"
              />
            </div>

            {farmsList.length > 0 && (
              <div className="space-y-2">
                <label className="text-xs text-[var(--se-text-mut)] block">Or use an existing field</label>
                <select
                  className="w-full bg-white border border-[var(--se-border)] rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-[var(--se-accent)]"
                  value={uploadExistingFarmId}
                  onChange={e => { setUploadExistingFarmId(e.target.value); if (e.target.value) setUploadNewFieldName(''); }}
                >
                  <option value="">— create new field above —</option>
                  {farmsList.map(f => (
                    <option key={f.id} value={f.id}>{f.name}</option>
                  ))}
                </select>
              </div>
            )}

            <div className="flex gap-2 justify-end pt-1">
              <button type="button" onClick={cancelUploadTarget} className="px-4 py-2 rounded-lg text-sm border border-[var(--se-border)] bg-white hover:bg-[var(--se-rail)]">
                Cancel
              </button>
              <button
                type="button"
                onClick={confirmUploadTarget}
                disabled={!uploadExistingFarmId && !uploadNewFieldName.trim()}
                className="px-4 py-2 rounded-lg text-sm bg-[var(--se-accent)] hover:bg-[var(--se-accent-h)] text-white disabled:opacity-40"
              >
                Upload here
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
