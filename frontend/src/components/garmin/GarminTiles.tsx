import clsx from 'clsx'
import { WEEKDAYS_FULL, WEEKDAY_LETTERS } from '../../constants/weekdays'
import {
  ACCENT, NEG, POS, readinessZoneColor, toneColor, type Tone, type WeekdayPattern,
} from './garmin'

export function GarminSkeleton({ isLight }: { isLight: boolean }) {
  const bar = isLight ? 'bg-gray-100' : 'bg-surface-700'
  return (
    <div className="max-w-5xl mx-auto space-y-10 pb-12">
      <div className={clsx('h-12 panel animate-pulse rounded-xl')} />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {Array.from({ length: 12 }).map((_, i) => (
          <div key={i} className={clsx('rounded-xl p-4 panel animate-pulse')}>
            <div className={clsx('h-3 w-16 rounded mb-3', bar)} />
            <div className={clsx('h-7 w-20 rounded', bar)} />
          </div>
        ))}
      </div>
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className={clsx('panel p-5 animate-pulse')}>
          <div className={clsx('h-3 w-32 rounded mb-4', bar)} />
          <div className={clsx('h-[240px] rounded', bar)} />
        </div>
      ))}
    </div>
  )
}

// ─────────────────────────────────────────── hero tile

export function HeroTile({
  label, value, unit, qualifier, tone, detail, isLight,
}: {
  label: string
  value: number | string | null
  unit?: string
  qualifier?: string
  tone: Tone
  detail?: string
  isLight: boolean
}) {
  const c = toneColor(tone)
  return (
    <div
      className="panel relative overflow-hidden p-5"
      style={{ ['--card-accent' as string]: c } as React.CSSProperties}
    >
      {/* Top accent stripe carries the tone */}
      <div className="absolute top-0 left-0 right-0 h-[2px]" style={{ background: c, opacity: 0.85 }} />
      {/* Soft tone wash */}
      <div className="absolute inset-0 pointer-events-none"
        style={{ background: `radial-gradient(ellipse at top left, ${c}10, transparent 65%)` }} />

      <div className="relative flex items-center gap-2 mb-2.5">
        <span className="eyebrow">{label}</span>
        <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ background: c }} />
      </div>

      <div className="relative flex items-baseline gap-2">
        <span className={clsx('text-3xl md:text-4xl font-bold tabular-nums tracking-tight',
          isLight ? 'text-gray-900' : 'text-gray-100')}>
          {value ?? '–'}
        </span>
        {unit && (
          <span className={clsx('text-sm font-medium tracking-normal', isLight ? 'text-gray-400' : 'text-gray-500')}>
            {unit}
          </span>
        )}
      </div>

      {qualifier && (
        <div className="relative text-[10px] uppercase tracking-[0.18em] font-semibold mt-1.5"
          style={{ color: c }}>
          {qualifier}
        </div>
      )}
      {detail && (
        <div className={clsx('relative text-[11px] mt-1', isLight ? 'text-gray-500' : 'text-gray-500')}>
          {detail}
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────── weekly rhythm tile

export function RhythmTile({
  label, pattern, format, isLight,
}: {
  label: string
  pattern: WeekdayPattern | null
  format: (v: number) => string
  isLight: boolean
}) {
  if (!pattern) {
    return (
      <div className="panel p-4">
        <div className="eyebrow mb-2">{label}</div>
        <div className={clsx('text-sm py-6', isLight ? 'text-gray-400' : 'text-gray-600')}>
          Not enough data
        </div>
      </div>
    )
  }
  const maxMean = Math.max(...pattern.means.filter((m): m is number => m != null))
  const delta = pattern.deltaPct
  return (
    <div className="panel relative overflow-hidden p-4">
      <div className="absolute inset-0 pointer-events-none"
        style={{ background: `radial-gradient(ellipse at top left, ${ACCENT}0c, transparent 65%)` }} />
      <div className="relative eyebrow mb-1.5">{label}</div>
      <div className={clsx('relative text-xl font-bold tracking-tight',
        isLight ? 'text-gray-900' : 'text-gray-100')}>
        {WEEKDAYS_FULL[pattern.bestIdx]}
      </div>
      <div className={clsx('relative text-[11px] mt-0.5 mb-3', isLight ? 'text-gray-500' : 'text-gray-500')}>
        avg {format(pattern.bestMean)}
        {delta != null && Math.abs(delta) >= 0.5 && (
          <span style={{ color: ACCENT }}>
            {' '}· {delta >= 0 ? '+' : ''}{delta.toFixed(0)}% vs typical
          </span>
        )}
      </div>
      <div className="relative flex items-end gap-1">
        {pattern.means.map((m, i) => {
          const winner = i === pattern.bestIdx
          const heightPct = m != null && maxMean > 0 ? Math.max(10, (m / maxMean) * 100) : 4
          return (
            <div key={i} className="flex-1 flex flex-col items-center gap-1"
              title={m != null ? `${WEEKDAYS_FULL[i]} · avg ${format(m)}` : WEEKDAYS_FULL[i]}>
              <div className="w-full h-8 flex items-end">
                <div className="w-full rounded-sm"
                  style={{
                    height: `${heightPct}%`,
                    background: winner ? ACCENT : isLight ? '#e2e8f0' : '#334155',
                    boxShadow: winner ? `0 0 8px ${ACCENT}66` : undefined,
                  }} />
              </div>
              <div className={clsx('text-[9px] leading-none',
                winner ? 'font-semibold' : isLight ? 'text-gray-400' : 'text-gray-600')}
                style={winner ? { color: ACCENT } : undefined}>
                {WEEKDAY_LETTERS[i]}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─────────────────────────────────────────── readiness factor bars

export function FactorBars({
  factors, isLight,
}: {
  factors: { label: string; value: number | null }[]
  isLight: boolean
}) {
  if (!factors.length) {
    return <div className={clsx('text-xs py-12 text-center', isLight ? 'text-gray-400' : 'text-gray-500')}>
      No readiness data yet
    </div>
  }
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-4">
      {factors.map(f => {
        const v = f.value ?? 0
        const c = f.value != null ? readinessZoneColor(v) : ACCENT
        const label = f.value == null ? '–'
          : v >= 75 ? 'Excellent'
          : v >= 50 ? 'Good'
          : v >= 25 ? 'Fair'
          : 'Poor'
        return (
          <div key={f.label} className="space-y-1.5">
            <div className="flex items-baseline justify-between gap-2">
              <span className={clsx('text-[11px] uppercase tracking-[0.15em]', isLight ? 'text-gray-500' : 'text-gray-500')}>
                {f.label}
              </span>
              <span className="text-[11px] font-mono tabular-nums">
                <span style={{ color: c }}>{f.value != null ? `${Math.round(v)}%` : '–'}</span>
              </span>
            </div>
            <div className={clsx('relative h-2.5 rounded-full overflow-hidden', isLight ? 'bg-gray-100' : 'bg-surface-700')}>
              <div
                className="h-full rounded-full transition-all duration-300"
                style={{
                  width: `${Math.max(2, Math.min(100, v))}%`,
                  background: `linear-gradient(90deg, ${c}aa, ${c})`,
                  boxShadow: `0 0 8px ${c}55`,
                }}
              />
            </div>
            <div className={clsx('text-[10px] uppercase tracking-[0.12em]', isLight ? 'text-gray-400' : 'text-gray-500')}>
              {label}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ─────────────────────────────────────────── training load bars

export type LoadData = {
  aerobic_low: number | null
  aerobic_high: number | null
  anaerobic: number | null
  targets: {
    aerobic_low: (number | null)[]
    aerobic_high: (number | null)[]
    anaerobic: (number | null)[]
  }
  feedback: string
}

export function LoadBalanceBars({ load, isLight }: { load: LoadData | null; isLight: boolean }) {
  if (!load) {
    return <div className={clsx('text-xs py-12 text-center', isLight ? 'text-gray-400' : 'text-gray-500')}>
      No training-load data yet
    </div>
  }
  const buckets: { key: keyof typeof load.targets; label: string; value: number | null }[] = [
    { key: 'aerobic_low',  label: 'Aerobic low',  value: load.aerobic_low },
    { key: 'aerobic_high', label: 'Aerobic high', value: load.aerobic_high },
    { key: 'anaerobic',    label: 'Anaerobic',    value: load.anaerobic },
  ]
  const maxAxis = Math.max(
    ...buckets.flatMap(b => {
      const t = load.targets[b.key]
      return [b.value ?? 0, t[1] ?? 0]
    }),
    1,
  ) * 1.15

  // Color rule: green when value lands inside the personal target window;
  // amber if you've gone over the upper bound (overdoing it); red if you
  // fell short of the lower bound (undertraining this bucket).
  const colorFor = (val: number, tmin: number, tmax: number) =>
    val < tmin ? NEG : val > tmax ? '#f59e0b' : POS

  const rectBorder = isLight ? 'rgba(148, 163, 184, 0.7)' : 'rgba(148, 163, 184, 0.45)'

  return (
    <div className="flex flex-col justify-around h-full py-1">
      {buckets.map(b => {
        const target = load.targets[b.key]
        const tmin = target[0] ?? 0
        const tmax = target[1] ?? 0
        const val = b.value ?? 0
        const barColor = colorFor(val, tmin, tmax)
        const valuePct = (val / maxAxis) * 100
        const minPct = (tmin / maxAxis) * 100
        const widthPct = ((tmax - tmin) / maxAxis) * 100
        return (
          <div key={b.key}>
            <div className="flex items-baseline justify-between mb-1.5">
              <span className={clsx('text-[11px] uppercase tracking-[0.15em]', isLight ? 'text-gray-500' : 'text-gray-500')}>
                {b.label}
              </span>
              <span className="text-[11px] font-mono tabular-nums" style={{ color: barColor }}>
                {Math.round(val)}
              </span>
            </div>
            {/* Track: bar passes THROUGH the target rectangle.
                Container has no background — the rectangle is just an
                outline, the bar is a solid horizontal stripe centered in it. */}
            <div className="relative h-9">
              {/* Target rectangle outline (the "personal range") */}
              <div
                className="absolute top-0 bottom-0 rounded-lg"
                style={{
                  left: `${minPct}%`,
                  width: `${widthPct}%`,
                  border: `1.5px solid ${rectBorder}`,
                }}
              />
              {/* Value bar — solid colored stripe, vertically centered */}
              <div
                className="absolute rounded-full transition-all duration-300"
                style={{
                  left: 0,
                  width: `${valuePct}%`,
                  top: '50%',
                  height: 10,
                  transform: 'translateY(-50%)',
                  background: barColor,
                  boxShadow: `0 0 10px ${barColor}55`,
                }}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}
