import { useCallback, useState, useEffect } from 'react'
import clsx from 'clsx'
import { getDistUnit } from '../../utils/formatSpeed'
import {
  SEGMENT_TYPES,
  getSegmentColor,
  getSegmentLabel,
  type Segment,
} from './segmentUtils'

export type { Segment } from './segmentUtils'

/* Numeric input that keeps a local string buffer so users can type decimals freely */
function NumericInput({ value, onChange, className, placeholder = '--' }: {
  value: number | null | undefined
  onChange: (v: number | null) => void
  className?: string
  placeholder?: string
}) {
  const [raw, setRaw] = useState(() => value != null ? String(value) : '')

  // Sync from parent when the external value changes (e.g. template pick)
  useEffect(() => {
    const ext = value != null ? String(value) : ''
    const frame = requestAnimationFrame(() => setRaw(prev => {
      // Don't overwrite if the user is mid-edit and the parsed value matches
      const parsed = prev === '' ? null : parseFloat(prev)
      if (parsed === value) return prev
      return ext
    }))
    return () => cancelAnimationFrame(frame)
  }, [value])

  return (
    <input
      type="text"
      inputMode="decimal"
      placeholder={placeholder}
      value={raw}
      onChange={e => {
        const v = e.target.value
        // Allow digits, dots, and empty
        if (v !== '' && !/^-?\d*\.?\d*$/.test(v)) return
        setRaw(v)
        if (v === '' || v === '.' || v === '-') {
          onChange(null)
        } else {
          const n = parseFloat(v)
          if (!isNaN(n)) onChange(n)
        }
      }}
      onBlur={() => {
        // Clean up trailing dots on blur
        if (raw === '' || raw === '.' || raw === '-') {
          setRaw('')
          onChange(null)
        }
      }}
      className={className}
    />
  )
}

function emptySegment(type: Segment['type'] = 'work'): Segment {
  return { type, distance_km: null, duration_mins: null, repetitions: 1 }
}

/** True for time-based pace units (min/km, min/100m) where smaller = faster.
 *  False for speed units (km/h) where larger = faster. */
function isPaceUnit(unit: string): boolean {
  return unit.startsWith('min/')
}

interface Props {
  segments: Segment[]
  onChange: (segments: Segment[]) => void
  paceUnit?: string
  sportType?: string
  compact?: boolean
}

export default function SegmentListBuilder({ segments, onChange, paceUnit = 'min/km', sportType, compact = false }: Props) {
  const distUnit = getDistUnit(sportType)
  const distIsMeters = distUnit === 'm'
  const toDisplayDist = (km: number | null | undefined) => (km == null ? km : (distIsMeters ? km * 1000 : km))
  const fromDisplayDist = (v: number | null) => (v == null ? v : (distIsMeters ? v / 1000 : v))

  const isPace = isPaceUnit(paceUnit)
  const fastLabel = isPace ? 'Fastest' : 'Min speed'
  const slowLabel = isPace ? 'Slowest' : 'Max speed'

  const update = useCallback((idx: number, patch: Partial<Segment>) => {
    const next = segments.map((s, i) => i === idx ? { ...s, ...patch } : s)
    onChange(next)
  }, [segments, onChange])

  const remove = useCallback((idx: number) => {
    onChange(segments.filter((_, i) => i !== idx))
  }, [segments, onChange])

  const moveUp = useCallback((idx: number) => {
    if (idx <= 0) return
    const next = [...segments]
    ;[next[idx - 1], next[idx]] = [next[idx], next[idx - 1]]
    onChange(next)
  }, [segments, onChange])

  const moveDown = useCallback((idx: number) => {
    if (idx >= segments.length - 1) return
    const next = [...segments]
    ;[next[idx], next[idx + 1]] = [next[idx + 1], next[idx]]
    onChange(next)
  }, [segments, onChange])

  const addSegment = useCallback((type: Segment['type']) => {
    onChange([...segments, emptySegment(type)])
  }, [segments, onChange])

  return (
    <div className="space-y-2">
      {segments.map((seg, idx) => {
        const color = getSegmentColor(seg.type)
        return (
          <div
            key={idx}
            className="flex rounded-lg overflow-hidden border"
            style={{ borderColor: `${color}30` }}
          >
            <div className="w-1 shrink-0" style={{ backgroundColor: color }} />
            <div className={clsx('flex-1', compact ? 'p-2' : 'p-2.5')} style={{ backgroundColor: `${color}08` }}>
              {/* Header row */}
              <div className="flex items-center justify-between mb-1.5">
                <div className="flex items-center gap-2">
                  <select
                    value={seg.type}
                    onChange={e => update(idx, { type: e.target.value as Segment['type'] })}
                    className="text-xs font-medium bg-transparent border-none outline-none cursor-pointer"
                    style={{ color }}
                  >
                    {SEGMENT_TYPES.map(t => (
                      <option key={t.value} value={t.value}>{t.label}</option>
                    ))}
                  </select>
                  {seg.label && (
                    <span className="text-[10px] text-gray-500">{seg.label}</span>
                  )}
                </div>
                <div className="flex items-center gap-1">
                  <button onClick={() => moveUp(idx)} disabled={idx === 0}
                    className={clsx('text-[10px] px-1', idx === 0 ? 'text-gray-700' : 'text-gray-500 hover:text-gray-300')}>
                    {'\u25B2'}
                  </button>
                  <button onClick={() => moveDown(idx)} disabled={idx === segments.length - 1}
                    className={clsx('text-[10px] px-1', idx === segments.length - 1 ? 'text-gray-700' : 'text-gray-500 hover:text-gray-300')}>
                    {'\u25BC'}
                  </button>
                  <button onClick={() => remove(idx)}
                    className="text-gray-500 hover:text-gray-300 text-xs leading-none px-1">
                    {'\u2715'}
                  </button>
                </div>
              </div>

              {/* Fields row */}
              <div className={clsx('grid gap-2', compact ? 'grid-cols-2' : 'grid-cols-3')}>
                {/* Distance */}
                <div>
                  <label className="text-[10px] text-gray-500 mb-0.5 block">Distance</label>
                  <div className="flex items-center gap-1">
                    <NumericInput
                      value={toDisplayDist(seg.distance_km) ?? null}
                      onChange={v => update(idx, { distance_km: fromDisplayDist(v) ?? null })}
                      className="w-16 bg-surface-700 border border-surface-600 rounded px-1.5 py-1 text-xs"
                    />
                    <span className="text-[10px] text-gray-500">{distUnit}</span>
                  </div>
                </div>

                {/* Duration */}
                <div>
                  <label className="text-[10px] text-gray-500 mb-0.5 block">Duration</label>
                  <div className="flex items-center gap-1">
                    <NumericInput
                      value={seg.duration_mins}
                      onChange={v => update(idx, { duration_mins: v })}
                      className="w-16 bg-surface-700 border border-surface-600 rounded px-1.5 py-1 text-xs"
                    />
                    <span className="text-[10px] text-gray-500">min</span>
                  </div>
                </div>

                {/* Reps (only for work segments) */}
                {seg.type === 'work' && (
                  <div>
                    <label className="text-[10px] text-gray-500 mb-0.5 block">Reps</label>
                    <input
                      type="number" min="1" max="99"
                      value={seg.repetitions ?? 1}
                      onChange={e => update(idx, { repetitions: parseInt(e.target.value) || 1 })}
                      className="w-16 bg-surface-700 border border-surface-600 rounded px-1.5 py-1 text-xs"
                    />
                  </div>
                )}
              </div>

              {/* Pace targets row */}
              <div className={clsx('grid gap-2 mt-1.5', compact ? 'grid-cols-2' : 'grid-cols-3')}>
                <div>
                  <label className="text-[10px] text-gray-500 mb-0.5 block">
                    {fastLabel} ({paceUnit})
                  </label>
                  <NumericInput
                    value={seg.target_pace_min}
                    onChange={v => update(idx, { target_pace_min: v })}
                    className="w-full bg-surface-700 border border-surface-600 rounded px-1.5 py-1 text-xs"
                  />
                </div>
                <div>
                  <label className="text-[10px] text-gray-500 mb-0.5 block">
                    {slowLabel} ({paceUnit})
                  </label>
                  <NumericInput
                    value={seg.target_pace_max}
                    onChange={v => update(idx, { target_pace_max: v })}
                    className="w-full bg-surface-700 border border-surface-600 rounded px-1.5 py-1 text-xs"
                  />
                </div>
                <div>
                  <label className="text-[10px] text-gray-500 mb-0.5 block">HR Zone</label>
                  <select
                    value={seg.target_hr_zone ?? ''}
                    onChange={e => update(idx, { target_hr_zone: e.target.value ? parseInt(e.target.value) : null })}
                    className="w-full bg-surface-700 border border-surface-600 rounded px-1.5 py-1 text-xs"
                  >
                    <option value="">--</option>
                    {[1, 2, 3, 4, 5].map(z => <option key={z} value={z}>Z{z}</option>)}
                  </select>
                </div>
              </div>

              {/* Recovery fields for work segments with reps */}
              {seg.type === 'work' && (seg.repetitions ?? 1) > 1 && (
                <div className="grid grid-cols-2 gap-2 mt-1.5 pt-1.5 border-t border-dashed" style={{ borderColor: `${color}20` }}>
                  <div>
                    <label className="text-[10px] text-gray-500 mb-0.5 block">Recovery time</label>
                    <div className="flex items-center gap-1">
                      <NumericInput
                        value={seg.recovery_duration_mins}
                        onChange={v => update(idx, { recovery_duration_mins: v })}
                        className="w-16 bg-surface-700 border border-surface-600 rounded px-1.5 py-1 text-xs"
                      />
                      <span className="text-[10px] text-gray-500">min</span>
                    </div>
                  </div>
                  <div>
                    <label className="text-[10px] text-gray-500 mb-0.5 block">Recovery dist</label>
                    <div className="flex items-center gap-1">
                      <NumericInput
                        value={toDisplayDist(seg.recovery_distance_km) ?? null}
                        onChange={v => update(idx, { recovery_distance_km: fromDisplayDist(v) ?? null })}
                        className="w-16 bg-surface-700 border border-surface-600 rounded px-1.5 py-1 text-xs"
                      />
                      <span className="text-[10px] text-gray-500">{distUnit}</span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        )
      })}

      {/* Add segment buttons */}
      <div className="flex flex-wrap gap-1.5">
        {SEGMENT_TYPES.filter(t => t.value !== 'rest').map(t => (
          <button
            key={t.value}
            onClick={() => addSegment(t.value)}
            className="text-xs rounded-full px-2.5 py-1 border transition-all hover:opacity-80"
            style={{ borderColor: `${t.color}50`, color: t.color, backgroundColor: `${t.color}10` }}
          >
            + {t.label}
          </button>
        ))}
      </div>
    </div>
  )
}

/* Compact visual summary of segments (read-only, for cards) */
export function SegmentSummary({ segments }: { segments: Segment[] }) {
  if (!segments || segments.length === 0) return null

  const totalKm = segments.reduce((sum, s) => {
    const dist = s.distance_km ?? 0
    const reps = s.repetitions ?? 1
    return sum + dist * reps
  }, 0)

  return (
    <div className="flex flex-wrap gap-1 items-center">
      {segments.map((seg, idx) => {
        const color = getSegmentColor(seg.type)
        const reps = seg.repetitions ?? 1
        const dist = seg.distance_km
        const dur = seg.duration_mins
        let label = getSegmentLabel(seg.type)
        if (dist) label += ` ${dist >= 1 ? `${dist}km` : `${Math.round(dist * 1000)}m`}`
        else if (dur) label += ` ${dur}'`
        if (reps > 1) label = `${reps}x ${label}`
        return (
          <span
            key={idx}
            className="text-[10px] font-mono rounded px-1.5 py-0.5 border whitespace-nowrap"
            style={{ color, borderColor: `${color}40`, backgroundColor: `${color}10` }}
          >
            {label}
          </span>
        )
      })}
      {totalKm > 0 && (
        <span className="text-[10px] text-gray-500 ml-1">
          = {totalKm >= 1 ? `${Math.round(totalKm * 10) / 10}km` : `${Math.round(totalKm * 1000)}m`}
        </span>
      )}
    </div>
  )
}
