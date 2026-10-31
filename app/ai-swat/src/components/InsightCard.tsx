import clsx from 'clsx';
import type { LucideIcon } from 'lucide-react';
import type { InsightItem } from '@/lib/api';
import { severityColor } from '@/lib/api';
import ConfidenceBadge from '@/components/ConfidenceBadge';

interface Props {
  icon: LucideIcon;
  label: string;
  insight: InsightItem;
}

export default function InsightCard({ icon: Icon, label, insight }: Props) {
  const colors = severityColor(insight.severity);
  return (
    <div className={clsx('border rounded-xl p-5', colors)}>
      <div className="flex items-center gap-2 mb-3">
        <Icon className="w-4 h-4 opacity-80" />
        <span className="text-xs font-medium opacity-70">{label}</span>
      </div>
      <p className="text-lg font-semibold leading-snug">{insight.headline}</p>
      {insight.detail && (
        <p className="text-xs opacity-60 mt-2 line-clamp-2">{insight.detail}</p>
      )}
      {insight.confidence && (
        <div className="mt-3">
          <ConfidenceBadge confidence={insight.confidence} size="xs" />
        </div>
      )}
    </div>
  );
}
