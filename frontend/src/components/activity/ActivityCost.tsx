import { Link } from 'react-router-dom'
import type { ActivityCost as Cost } from '../../api/hooks'
import { formatDurationHM } from '../../utils/formatSpeed'
import StatCard from '../shared/StatCard'
import { hrvZoneColor, readinessZoneColor, restingHrTone, toneColor } from '../garmin/garmin'

/** Garmin's training-effect codes as a phrase: OVERREACHING_VO2MAX → "Overreaching VO2 max". */
function effectLabel(code: string | null): string | null {
  if (!code || code === 'NONE') return null
  const words = code.toLowerCase().replace(/_/g, ' ').replace(/\bvo2max\b/, 'VO2 max')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

const signed = (v: number) => (v > 0 ? `+${v}` : `${v}`)

/** What the activity took out of you by Garmin's measure, and the night after against
 *  your normal. Hidden when Garmin has nothing for it. */
export default function ActivityCost({ cost, day }: { cost: Cost | undefined; day: string | undefined }) {
  const bb = cost?.body_battery
  const night = cost?.night
  const recovery = cost?.recovery_hours
  if (!bb && recovery == null && !night) return null

  const bbLevels = bb?.start != null && bb?.end != null ? `${bb.start} → ${bb.end}` : null
  const hasBand = night?.hrv_balanced_low != null && night?.hrv_balanced_upper != null

  return (
    <section>
      <div className="section-head mb-4 flex items-baseline justify-between gap-3">
        <span className="eyebrow">What it cost</span>
        {day && <Link to={`/garmin?day=${day}`} className="text-[11px] text-gray-500 hover:text-gray-300">The whole day →</Link>}
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 stagger-children">
        {bb?.impact != null && (
          <StatCard label="Body battery" value={signed(bb.impact)} color="text-amber-400"
            sublabel={[bbLevels, effectLabel(bb.effect)].filter(Boolean).join(' · ') || undefined} />
        )}
        {recovery != null && (
          <StatCard label="Recovery time" value={recovery} unit="h" sublabel="Garmin's estimate right after" />
        )}
        {night?.sleep_score != null && (
          <StatCard label="Sleep that night" value={night.sleep_score}
            sublabel={[
              night.sleep_score_normal != null && `normal ${night.sleep_score_normal}`,
              night.sleep_seconds != null && formatDurationHM(night.sleep_seconds),
            ].filter(Boolean).join(' · ') || undefined} />
        )}
        {night?.hrv != null && (
          <StatCard label="HRV that night" value={night.hrv} unit="ms"
            accent={hrvZoneColor(night.hrv, night.hrv_balanced_low, night.hrv_balanced_upper, null)}
            sublabel={hasBand ? `balanced ${night.hrv_balanced_low}–${night.hrv_balanced_upper}` : undefined} />
        )}
        {night?.resting_hr != null && (
          <StatCard label="Resting HR next day" value={night.resting_hr} unit="bpm"
            accent={toneColor(restingHrTone(night.resting_hr, night.resting_hr_normal))}
            sublabel={night.resting_hr_normal != null ? `7-day avg ${night.resting_hr_normal}` : undefined} />
        )}
        {night?.body_battery_charged != null && (
          <StatCard label="Charged overnight" value={signed(night.body_battery_charged)} sublabel="body battery" />
        )}
        {night?.readiness != null && (
          <StatCard label="Readiness next morning" value={night.readiness}
            accent={readinessZoneColor(night.readiness)}
            sublabel={night.readiness_level?.toLowerCase()} />
        )}
      </div>
    </section>
  )
}
