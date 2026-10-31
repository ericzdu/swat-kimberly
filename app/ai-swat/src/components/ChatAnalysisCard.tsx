import clsx from 'clsx';
import { Droplets, Sprout, Wheat, FlaskConical, CheckCircle2, AlertTriangle, XCircle, Info } from 'lucide-react';
import type { ChatAnalysisCard as Card } from '@/lib/api';
import { severityColor } from '@/lib/api';
import ConfidenceBadge from '@/components/ConfidenceBadge';

const TYPE_META = {
  irrigation: { icon: Droplets, label: 'Irrigation advice' },
  fertilizer: { icon: Sprout, label: 'Fertilizer advice' },
  nitrate: { icon: FlaskConical, label: 'Water quality' },
  yield: { icon: Wheat, label: 'Yield estimate' },
} as const;

function verdictBadge(card: Card) {
  const v = card.verdict;
  if (card.type === 'irrigation') {
    if (v === 'yes') {
      return { text: 'Irrigate today', icon: AlertTriangle, className: 'bg-[var(--se-error-sf)] text-[var(--se-error)] border-[var(--se-border)]' };
    }
    if (v === 'soon') {
      return { text: 'Irrigate soon', icon: AlertTriangle, className: 'bg-[var(--se-warn-sf)] text-[var(--se-warn)] border-[var(--se-border)]' };
    }
    return { text: 'No irrigation needed', icon: CheckCircle2, className: 'bg-[var(--se-ok-sf)] text-[var(--se-ok)] border-[var(--se-border)]' };
  }
  if (card.type === 'fertilizer') {
    if (v === 'yes') {
      return { text: 'Apply fertilizer', icon: AlertTriangle, className: 'bg-[var(--se-warn-sf)] text-[var(--se-warn)] border-[var(--se-border)]' };
    }
    if (v === 'soon') {
      return { text: 'Consider applying', icon: Info, className: 'bg-[var(--se-accent-sf)] text-[var(--se-accent)] border-[var(--se-accent-bd)]' };
    }
    return { text: 'Levels OK', icon: CheckCircle2, className: 'bg-[var(--se-ok-sf)] text-[var(--se-ok)] border-[var(--se-border)]' };
  }
  if (card.type === 'nitrate') {
    if (v === 'high') {
      return { text: 'High nitrate loss', icon: AlertTriangle, className: 'bg-[var(--se-error-sf)] text-[var(--se-error)] border-[var(--se-border)]' };
    }
    if (v === 'moderate') {
      return { text: 'Moderate loss', icon: AlertTriangle, className: 'bg-[var(--se-warn-sf)] text-[var(--se-warn)] border-[var(--se-border)]' };
    }
    return { text: 'Low loss', icon: CheckCircle2, className: 'bg-[var(--se-ok-sf)] text-[var(--se-ok)] border-[var(--se-border)]' };
  }
  if (v === 'unknown') {
    return { text: 'No data', icon: XCircle, className: 'bg-[var(--se-rail)] text-[var(--se-text-mut)] border-[var(--se-border)]' };
  }
  return { text: 'Estimate ready', icon: CheckCircle2, className: 'bg-[var(--se-ok-sf)] text-[var(--se-ok)] border-[var(--se-border)]' };
}

export default function ChatAnalysisCard({ card }: { card: Card }) {
  const meta = TYPE_META[card.type];
  const Icon = meta.icon;
  const badge = verdictBadge(card);
  const BadgeIcon = badge.icon;
  const colors = severityColor(card.severity);

  return (
    <div className={clsx('rounded-lg border p-4 space-y-3 shadow-sm', colors)}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <Icon className="w-4 h-4 shrink-0 text-[var(--se-text-mut)]" />
          <span className="text-xs font-medium uppercase tracking-wide text-[var(--se-text-mut)]">{meta.label}</span>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <ConfidenceBadge confidence={card.confidence} size="xs" />
          <span className={clsx('inline-flex items-center gap-1 text-[11px] font-semibold px-2.5 py-1 rounded-full border', badge.className)}>
            <BadgeIcon className="w-3.5 h-3.5" />
            {badge.text}
          </span>
        </div>
      </div>

      <div>
        <p className="text-base font-semibold text-[var(--se-text)] leading-snug">{card.recommendation}</p>
        <p className="text-sm text-[var(--se-text-mut)] mt-1">{card.headline}</p>
      </div>

      {card.type === 'irrigation' && card.water_balance && (
        <div className="grid grid-cols-2 gap-2">
          <Metric label="Soil moisture" value={card.water_balance.soil_moisture_mm} unit="mm" highlight />
          <Metric label="Evapotranspiration" value={card.water_balance.et_mm} unit="mm" />
          <Metric label="Rainfall" value={card.water_balance.precip_mm} unit="mm" />
          <Metric label="Runoff" value={card.water_balance.runoff_mm} unit="mm" />
        </div>
      )}

      {card.type === 'fertilizer' && card.nutrient_balance && (
        <div className="grid grid-cols-2 gap-2">
          <Metric label="Nitrogen" value={card.nutrient_balance.nitrogen_kgha} unit="kg/ha" highlight />
          <Metric label="Phosphorus" value={card.nutrient_balance.phosphorus_kgha} unit="kg/ha" />
        </div>
      )}

      {card.type === 'nitrate' && card.nitrate && (
        <div className="grid grid-cols-2 gap-2">
          <Metric label="Leached to groundwater" value={card.nitrate.leached_to_groundwater_kgha} unit="kg/ha" highlight />
          <Metric label="Total N loss" value={card.nitrate.total_no3_loss_kgha} unit="kg/ha" />
          {card.nitrate.stream?.mean_no3_mgL != null && (
            <Metric label="Stream nitrate" value={card.nitrate.stream.mean_no3_mgL} unit="mg/L" decimals={1} />
          )}
          <Metric label="Drinking limit" value={card.nitrate.limit_mgL} unit="mg/L" decimals={0} />
        </div>
      )}

      {card.type === 'yield' && card.yield_kgha != null && card.yield_kgha > 0 && (
        <div className="rounded-lg bg-[var(--se-rail)] px-3 py-2 text-center">
          <p className="text-2xl font-bold text-[var(--se-text)]">{(card.yield_kgha / 1000).toFixed(1)}</p>
          <p className="text-xs text-[var(--se-text-mut)]">tonnes / ha ({card.yield_kgha.toFixed(0)} kg/ha)</p>
        </div>
      )}

      {card.explanation && (
        <p className="text-xs text-[var(--se-text-mut)] leading-relaxed border-t border-[var(--se-border)] pt-3">{card.explanation}</p>
      )}

      {card.advice && (
        <p className="text-sm text-[var(--se-text)] font-medium">{card.advice}</p>
      )}
    </div>
  );
}

function Metric({ label, value, unit, highlight, decimals = 0 }: { label: string; value?: number; unit: string; highlight?: boolean; decimals?: number }) {
  const n = value ?? 0;
  return (
    <div className={clsx('rounded-lg px-3 py-2 border border-[var(--se-border-lt)]', highlight ? 'bg-[var(--se-accent-sf)]' : 'bg-[var(--se-rail)]')}>
      <p className="text-[10px] uppercase tracking-wide text-[var(--se-text-fnt)]">{label}</p>
      <p className={clsx('text-lg font-semibold tabular-nums', highlight ? 'text-[var(--se-accent)]' : 'text-[var(--se-text)]')}>
        {n.toFixed(decimals)} <span className="text-xs font-normal text-[var(--se-text-fnt)]">{unit}</span>
      </p>
    </div>
  );
}
