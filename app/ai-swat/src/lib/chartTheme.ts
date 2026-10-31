// Shared chart design tokens — LIGHT surface (SWAT+ Editor theme).
// Categorical hues are the reference light-surface palette (validated for a white
// chart surface). Assign in fixed order, never cycle. Status colors are reserved.

export const CHART = {
  surface: '#FFFFFF',
  ink: '#1A2230',
  inkSecondary: '#5B6B7B',
  muted: '#8A97A4', // axis ticks / labels
  grid: '#E6E9ED', // hairline gridlines
  axis: '#CBD2D9', // baseline / axis
  // Categorical slots (fixed order): blue, aqua, yellow, green, violet, red, magenta, orange
  cat: ['#2a78d6', '#1baf7a', '#eda100', '#008300', '#4a3aa7', '#e34948', '#e87ba4', '#eb6834'],
  // Reserved status colors — icon + label always accompany these, never color alone.
  status: { good: '#0ca30c', warning: '#fab219', serious: '#ec835a', critical: '#d03b3b' },
  // Default single-series (sequential) hue.
  series1: '#2a78d6',
} as const;

// Consistent Recharts tooltip surface for the light theme.
export const tooltipStyle = {
  background: '#FFFFFF',
  border: `1px solid ${CHART.grid}`,
  borderRadius: 8,
  color: CHART.ink,
  fontSize: 12,
  boxShadow: '0 2px 8px rgba(16,24,40,0.10)',
} as const;

export const axisTick = { fill: CHART.muted, fontSize: 12 } as const;
