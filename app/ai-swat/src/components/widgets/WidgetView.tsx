import ChatAnalysisCard from '@/components/ChatAnalysisCard';
import ConfidenceBadge from '@/components/ConfidenceBadge';
import ChoiceWidget from './ChoiceWidget';
import ConfirmWidget from './ConfirmWidget';
import MapDrawWidget from './MapDrawWidget';
import ChartWidget from './ChartWidget';
import TableWidget from './TableWidget';
import ChecklistWidget from './ChecklistWidget';
import ProgressWidget from './ProgressWidget';
import GenericForm from './GenericForm';
import SwatEditorWidget from './SwatEditorWidget';
import type { Widget } from '@/lib/widgets';
import type { ChatAnalysisCard as CardType, OutputConfidence } from '@/lib/api';

// Closed dispatcher over the widget union. Unknown kinds render a safe stub —
// never eval, never dangerouslySetInnerHTML.
export default function WidgetView({ widget, onSubmit, disabled, farmId }: {
  widget: Widget;
  onSubmit: (w: Widget, data: Record<string, unknown>) => void;
  disabled?: boolean;
  farmId: string;
}) {
  switch (widget.kind) {
    case 'result-card':
      return <ChatAnalysisCard card={widget.payload as CardType} />;
    case 'confidence':
      return <ConfidenceBadge confidence={widget.payload as OutputConfidence} />;
    case 'choice':
      return <ChoiceWidget widget={widget} onSubmit={onSubmit} disabled={disabled} />;
    case 'confirm':
      return <ConfirmWidget widget={widget} onSubmit={onSubmit} disabled={disabled} />;
    case 'map-draw':
      return <MapDrawWidget widget={widget} onSubmit={onSubmit} disabled={disabled} farmId={farmId} />;
    case 'form':
      return <GenericForm widget={widget} onSubmit={onSubmit} disabled={disabled} />;
    case 'chart':
      return <ChartWidget widget={widget} />;
    case 'table':
      return <TableWidget widget={widget} />;
    case 'checklist':
      return <ChecklistWidget widget={widget} />;
    case 'progress':
      return <ProgressWidget widget={widget} />;
    case 'swat-editor-panel':
      return <SwatEditorWidget />;
    default:
      return (
        <div className="rounded-lg border border-earth-400/30 bg-earth-400/5 p-4 text-sm text-earth-400">
          This element ("{widget.kind}") isn't available yet.
        </div>
      );
  }
}
