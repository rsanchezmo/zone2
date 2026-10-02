import { useMemo } from 'react'
import { useTheme } from '../../hooks/useTheme'
import type { GarminTrends } from '../../api/hooks'
import { formatDurationHM } from '../../utils/formatSpeed'
import { num, weekdayPattern } from './garmin'
import { RhythmTile } from './GarminTiles'

// Weekly-rhythm window. 7/30d give too few samples per weekday for the
// comparison to mean anything, so this section has its own selector.
const RHYTHM_OPTIONS = [
  { label: '90d', days: 90 },
  { label: '1y', days: 365 },
] as const

/** Which weekday wins each metric, over its own window. */
export default function WeeklyRhythm({ trends, days, onDaysChange, loading }: {
  trends: GarminTrends | undefined
  days: number
  onDaysChange: (days: number) => void
  loading: boolean
}) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  // ── Weekly rhythm: per-weekday averages over their own window ────
  const rhythm = useMemo(() => {
    const m = trends?.metrics
    return {
      sleepScore: weekdayPattern(m?.sleep, r => num(r.score), 'max'),
      sleepDuration: weekdayPattern(m?.sleep, r => num(r.total_seconds), 'max'),
      stress: weekdayPattern(m?.stress, r => num(r.avg), 'min'),
      restingHr: weekdayPattern(m?.heart_rates, r => num(r.resting), 'min'),
      steps: weekdayPattern(m?.daily_steps, r => num(r.total_steps), 'max'),
      calories: weekdayPattern(m?.user_summary, r => num(r.total_kcal), 'max'),
      hrv: weekdayPattern(m?.hrv, r => num(r.last_night_avg), 'max'),
      intensity: weekdayPattern(m?.intensity_minutes, r => {
        const mod = num(r.moderate)
        const vig = num(r.vigorous)
        return mod == null && vig == null ? null : (mod ?? 0) + (vig ?? 0)
      }, 'max'),
    }
  }, [trends])

  return (
    <section className="space-y-4">
      <div className="flex items-center gap-3 pt-2">
        <div className="section-head flex-1">
          <span className="eyebrow">Weekly rhythm</span>
        </div>
        <div className="flex items-center gap-0.5" role="tablist">
          {RHYTHM_OPTIONS.map(opt => (
            <button key={opt.days} className="chip"
              data-active={opt.days === days}
              onClick={() => onDaysChange(opt.days)}>
              {opt.label}
            </button>
          ))}
        </div>
      </div>
      {loading ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="panel h-36 animate-pulse" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <RhythmTile label="Best sleep" pattern={rhythm.sleepScore}
            format={v => `${Math.round(v)} score`} isLight={isLight} />
          <RhythmTile label="Longest sleep" pattern={rhythm.sleepDuration}
            format={formatDurationHM} isLight={isLight} />
          <RhythmTile label="Highest HRV" pattern={rhythm.hrv}
            format={v => `${Math.round(v)} ms`} isLight={isLight} />
          <RhythmTile label="Least stress" pattern={rhythm.stress}
            format={v => `${Math.round(v)} stress`} isLight={isLight} />
          <RhythmTile label="Lowest resting HR" pattern={rhythm.restingHr}
            format={v => `${Math.round(v)} bpm`} isLight={isLight} />
          <RhythmTile label="Most steps" pattern={rhythm.steps}
            format={v => `${Math.round(v).toLocaleString()} steps`} isLight={isLight} />
          <RhythmTile label="Biggest burn" pattern={rhythm.calories}
            format={v => `${Math.round(v).toLocaleString()} kcal`} isLight={isLight} />
          <RhythmTile label="Most intensity" pattern={rhythm.intensity}
            format={v => `${Math.round(v)} min`} isLight={isLight} />
        </div>
      )}
    </section>
  )
}
