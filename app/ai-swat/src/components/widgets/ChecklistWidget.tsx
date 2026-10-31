import DataChecklist from '@/components/DataChecklist';
import type { Widget } from '@/lib/widgets';
import type { ReadinessCheck } from '@/lib/api';

export default function ChecklistWidget({ widget }: { widget: Widget }) {
  const p = widget.payload as { checks?: ReadinessCheck[]; showProgress?: boolean };
  return <DataChecklist checks={p.checks || []} showProgress={p.showProgress} />;
}
