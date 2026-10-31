import RunProgress from '@/components/RunProgress';
import type { Widget } from '@/lib/widgets';

export default function ProgressWidget({ widget }: { widget: Widget }) {
  const p = widget.payload as { progress?: number; label?: string };
  return <RunProgress progress={p.progress ?? 0} label={p.label || 'Working…'} />;
}
