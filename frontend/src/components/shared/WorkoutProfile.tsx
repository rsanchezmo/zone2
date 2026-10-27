import { useState } from 'react'
import { formatDurationHM, formatPace, getPaceUnit, isSpeedSport } from '../../utils/formatSpeed'
import {
  formatSegmentAmount, getSegmentColor, getSegmentLabel, workoutBlocks,
  type Segment, type WorkoutBlock,
} from './segmentUtils'

const TICK_STEPS_MIN = [5, 10, 15, 20, 30, 60]

function formatClock(seconds: number): string {
  const total = Math.round(seconds)
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

function targetText(seg: Segment, sportType: string): string {
  const values = [seg.target_pace_min, seg.target_pace_max].filter((v): v is number => v != null && v > 0)
  if (values.length > 0) {
    const useSpeed = isSpeedSport(sportType)
    return `${[...new Set(values.map(v => formatPace(v, useSpeed)))].join('–')} ${getPaceUnit(sportType)}`
  }
  return seg.target_hr_zone ? `Z${seg.target_hr_zone}` : ''
}

function describe(b: WorkoutBlock, sportType: string): string {
  const name = b.rep ? `${getSegmentLabel(b.segment.type)} ${b.rep}/${b.reps}` : getSegmentLabel(b.segment.type)
  const amount = formatSegmentAmount(b.km, b.mins)
  return [name, amount || 'until lap', targetText(b.segment, sportType), amount && `≈ ${formatClock(b.seconds)}`]
    .filter(Boolean).join(' · ')
}

/** A workout's steps as a profile: width is estimated time, height the target intensity. */
export default function WorkoutProfile({ segments, sportType }: { segments: Segment[]; sportType: string }) {
  const [active, setActive] = useState<number | null>(null)
  const blocks = workoutBlocks(segments, sportType)
  if (blocks.length === 0) return null

  const total = blocks.reduce((sum, b) => sum + b.seconds, 0)
  const moving = blocks.map(b => b.speed).filter(s => s > 0)
  const fastest = Math.max(0, ...moving)
  const slowest = Math.min(...moving)
  const floor = 0.75 * slowest
  // The slowest moving step keeps a fifth of the height so it doesn't read as standing still
  const height = (speed: number): number => {
    if (speed <= 0) return 0.08
    if (fastest === slowest) return 0.5
    return 0.2 + 0.8 * (speed - floor) / (fastest - floor)
  }
  const step = (TICK_STEPS_MIN.find(m => total / 60 / m <= 6) ?? 60) * 60
  const ticks = Array.from({ length: Math.floor(total / step) + 1 }, (_, i) => i * step).filter(t => t <= total * 0.95)
  const hasOpen = blocks.some(b => !b.km && !b.mins)
  const summary = `≈ ${formatDurationHM(total)}${hasOpen ? ` · steps until lap counted as 5'` : ''}`
  const shown = active != null ? blocks[active] : null

  return (
    <div>
      <div className="flex items-end gap-px h-24" role="img" aria-label={`Workout profile, ${summary}`}
        onMouseLeave={() => setActive(null)}>
        {blocks.map((b, i) => {
          const color = getSegmentColor(b.segment.type)
          const label = b.segment.type !== 'rest' && b.seconds / total >= 0.06 ? formatSegmentAmount(b.km, b.mins) : ''
          return (
            <div key={i} className="flex flex-col justify-end h-full min-w-[3px]" style={{ flex: `${b.seconds} 1 0` }}
              onMouseEnter={() => setActive(i)} onClick={() => setActive(i)}>
              {label && <span className="text-[9px] font-mono text-center truncate mb-0.5" style={{ color }}>{label}</span>}
              <div
                className="rounded-t-sm transition-opacity"
                style={{
                  height: `${height(b.speed) * 85}%`,
                  background: `linear-gradient(to bottom, ${color}66, ${color}14)`,
                  borderTop: `2px ${b.km || b.mins ? 'solid' : 'dashed'} ${color}`,
                  opacity: active == null || active === i ? 1 : 0.45,
                }}
              />
            </div>
          )
        })}
      </div>
      <div className="relative h-3 mt-1 border-t border-gray-500/20">
        {ticks.map(t => (
          <span key={t} className="absolute top-0.5 text-[9px] font-mono tabular-nums text-gray-500 -translate-x-1/2 first:translate-x-0"
            style={{ left: `${t / total * 100}%` }}>
            {t / 60}'
          </span>
        ))}
      </div>
      <div className="text-[11px] font-mono tabular-nums text-gray-500 mt-2 truncate">
        {shown ? describe(shown, sportType) : summary}
      </div>
    </div>
  )
}
