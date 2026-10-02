import { useState } from 'react'
import clsx from 'clsx'
import {
  useUpdateZonesSettings, type AthleteZonesResponse, type ZonesSettings,
} from '../../api/hooks'
import ChartPanel from '../shared/ChartPanel'
import { useTheme } from '../../hooks/useTheme'

const HR_ZONE_COLORS = ['#6b7280', '#3b82f6', '#22c55e', '#eab308', '#ef4444']
const HR_ZONE_NAMES = ['Recovery', 'Aerobic', 'Tempo', 'Threshold', 'VO2max']

export default function HeartRateZones({ zones, zonesSettings }: {
  zones: AthleteZonesResponse | undefined
  zonesSettings: ZonesSettings | undefined
}) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const updateZonesSettings = useUpdateZonesSettings()
  const hrZones = zones?.heart_rate?.zones ?? undefined
  const maxHr = zones?.heart_rate?.max_hr ?? undefined
  if (!hrZones || hrZones.length === 0) return null

  return (
    <ChartPanel
      title="Heart rate zones"
      glow={false}
      toolbar={
        <ZoneSourceSelector
          current={zonesSettings?.source ?? 'estimated'}
          onChange={source => updateZonesSettings.mutate({ source })}
          isLight={isLight}
          pending={updateZonesSettings.isPending}
        />
      }
      footer={
        <div className="space-y-0.5">
          <div className={clsx('text-[11px]', isLight ? 'text-gray-500' : 'text-gray-500')}>
            {zones?.heart_rate?.source === 'strava' && `Custom zones from Strava · max HR ${maxHr ?? '?'} bpm`}
            {zones?.heart_rate?.source === 'manual' && `Manual zones · max HR ${maxHr ?? '?'} bpm`}
            {zones?.heart_rate?.source === 'estimated' && `Estimated from activity data · max HR ${maxHr ?? '?'} bpm`}
          </div>
          {zones?.heart_rate?.fallback_reason && (
            <div className="text-[11px] text-amber-400">
              Requested <span className="font-semibold">{zones.heart_rate.requested_source}</span>, falling back to {zones.heart_rate.source}: {zones.heart_rate.fallback_reason}
            </div>
          )}
        </div>
      }
    >
      <div className="space-y-2.5">
        {hrZones.map((zone, i) => {
          const color = HR_ZONE_COLORS[i] ?? '#6b7280'
          const name = HR_ZONE_NAMES[i] ?? `Zone ${i + 1}`
          const scale = (maxHr ?? 220) * 1.05
          const maxLabel = `${zone.max}`
          const barMax = zone.max
          const barMin = zone.min
          const rangeWidth = ((barMax - barMin) / scale) * 100
          const offsetLeft = (barMin / scale) * 100
          return (
            <div key={i} className="flex items-center gap-3">
              <span className="text-xs font-mono w-6 text-center font-bold" style={{ color }}>Z{i + 1}</span>
              <span className="text-sm text-gray-400 w-20 shrink-0">{name}</span>
              <div className={clsx('flex-1 h-7 rounded overflow-hidden relative', isLight ? 'bg-gray-100' : 'bg-surface-700')}>
                <div
                  className="absolute h-full rounded flex items-center justify-center"
                  style={{
                    left: `${offsetLeft}%`,
                    width: `${rangeWidth}%`,
                    backgroundColor: color,
                    opacity: 0.4,
                  }}
                />
                <div className="absolute inset-0 flex items-center justify-center">
                  <span className="text-[11px] font-mono font-bold" style={{ color }}>
                    {zone.min} – {maxLabel} bpm
                  </span>
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {zonesSettings?.source === 'manual' && (
        <ManualZonesEditor
          initial={zonesSettings?.manual_zones ?? hrZones}
          isLight={isLight}
          onSave={zones => updateZonesSettings.mutate({ source: 'manual', manual_zones: zones })}
          saving={updateZonesSettings.isPending}
        />
      )}
    </ChartPanel>
  )
}

// ────────────────────────────────────────────────────────
// ZoneSourceSelector — pick strava / estimated / manual
// ────────────────────────────────────────────────────────

function ZoneSourceSelector({
  current, onChange, isLight, pending,
}: {
  current: 'strava' | 'estimated' | 'manual'
  onChange: (source: 'strava' | 'estimated' | 'manual') => void
  isLight: boolean
  pending: boolean
}) {
  const options: Array<{ value: 'strava' | 'estimated' | 'manual'; label: string }> = [
    { value: 'estimated', label: 'Estimated' },
    { value: 'strava', label: 'Strava' },
    { value: 'manual', label: 'Manual' },
  ]
  return (
    <div className={clsx('inline-flex rounded-md overflow-hidden border', isLight ? 'border-gray-200' : 'border-surface-600')}>
      {options.map((o, i) => {
        const selected = current === o.value
        return (
          <button
            key={o.value}
            onClick={() => !selected && onChange(o.value)}
            disabled={pending}
            className={clsx(
              'text-[10px] uppercase tracking-[0.1em] px-2.5 py-1.5 md:py-1 transition-colors',
              i > 0 && (isLight ? 'border-l border-gray-200' : 'border-l border-surface-600'),
              selected
                ? (isLight ? 'bg-gray-900 text-white' : 'bg-gray-200 text-gray-900')
                : (isLight ? 'bg-white text-gray-600 hover:bg-gray-50' : 'bg-surface-800 text-gray-400 hover:bg-surface-700'),
              pending && 'opacity-60 cursor-wait',
            )}
          >
            {o.label}
          </button>
        )
      })}
    </div>
  )
}

// ────────────────────────────────────────────────────────
// ManualZonesEditor — edit 5 zone upper-bounds
// ────────────────────────────────────────────────────────

function ManualZonesEditor({
  initial, isLight, onSave, saving,
}: {
  initial: Array<{ min: number; max: number }>
  isLight: boolean
  onSave: (zones: Array<{ min: number; max: number }>) => void
  saving: boolean
}) {
  const [maxes, setMaxes] = useState<string[]>(() => {
    const src = initial.slice(0, 5)
    while (src.length < 5) src.push({ min: 0, max: 0 })
    return src.map(z => String(z.max ?? 0))
  })
  const [error, setError] = useState<string | null>(null)

  const parsed = maxes.map(s => parseInt(s, 10))
  const allValid = parsed.every(n => Number.isFinite(n) && n > 0 && n < 250)
  const monotonic = allValid && parsed.every((n, i) => i === 0 || n > parsed[i - 1])
  const canSave = allValid && monotonic

  const handleSave = () => {
    if (!canSave) {
      setError(!allValid ? 'All zones must be positive and below 250' : 'Each zone max must be greater than the previous')
      return
    }
    setError(null)
    const zones: Array<{ min: number; max: number }> = []
    for (let i = 0; i < 5; i++) {
      zones.push({ min: i === 0 ? 0 : parsed[i - 1], max: parsed[i] })
    }
    onSave(zones)
  }

  const accent = '#60a5fa' // blue — primary action
  return (
    <div className={clsx('mt-5 pt-4 border-t', isLight ? 'border-gray-200' : 'border-surface-600')}>
      <div className={clsx('text-[10px] uppercase tracking-[0.15em] mb-3', isLight ? 'text-gray-400' : 'text-gray-500')}>
        Manual thresholds <span className="normal-case tracking-normal">— upper bpm of each zone</span>
      </div>
      <div className="grid grid-cols-3 md:grid-cols-5 gap-2 mb-3">
        {maxes.map((v, i) => {
          const color = HR_ZONE_COLORS[i] ?? '#6b7280'
          return (
            <div key={i}>
              <label className="eyebrow mb-1.5 block" style={{ color }}>Z{i + 1} max</label>
              <input
                type="number"
                inputMode="numeric"
                value={v}
                onChange={e => setMaxes(cur => cur.map((x, ix) => ix === i ? e.target.value : x))}
                className="input w-full font-mono tabular-nums text-center"
                min={0}
                max={250}
              />
            </div>
          )
        })}
      </div>
      {error && <div className="text-[11px] text-red-400 mb-2">{error}</div>}
      <button
        onClick={handleSave}
        disabled={saving || !canSave}
        className="btn"
        style={{
          borderColor: `${accent}50`,
          color: accent,
          backgroundColor: `${accent}15`,
        }}
      >
        {saving ? 'Saving…' : 'Save zones'}
      </button>
    </div>
  )
}
