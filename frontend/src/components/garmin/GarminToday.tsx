import { useTheme } from '../../hooks/useTheme'
import StatCard from '../shared/StatCard'
import {
  ACCENT, acwrTone, bbTone, fmtKm, fmtRecovery, fmtSigned, hrvTone, readinessTone,
  restingHrTone, sleepTone, spo2Tone, stressTone, toneColor, type GarminCard,
} from './garmin'
import { HeroTile } from './GarminTiles'

/** Today's hero tiles: readiness, sleep, body battery, HRV and load ratio. */
export function TodaySection({ card }: { card: GarminCard }) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const bodyBatteryNet = card.bbCharged != null && card.bbDrained != null
    ? card.bbCharged - card.bbDrained
    : null
  return (
    <section className="space-y-4">
      <div className="section-head">
        <span className="eyebrow">Today</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
      <HeroTile
        label="Readiness"
        value={card.readinessScore}
        qualifier={card.readinessFeedback?.text ?? card.readinessLevel}
        tone={readinessTone(card.readinessScore)}
        detail={fmtRecovery(card.recoveryTimeMin) ?? card.readinessLevel?.toLowerCase()}
        isLight={isLight}
      />
      <HeroTile
        label="Sleep score"
        value={card.sleepScore}
        qualifier={card.sleepFeedback?.text ?? card.sleepQualifier}
        tone={card.sleepFeedback?.tone ?? sleepTone(card.sleepQualifier)}
        detail={card.sleepHours != null
          ? `${card.sleepHours.toFixed(1)}h asleep${card.sleepQualifier ? ` · ${card.sleepQualifier.toLowerCase()}` : ''}${card.sleepInsight ? ` · ${card.sleepInsight.text.toLowerCase()}` : ''}`
          : undefined}
        isLight={isLight}
      />
      <HeroTile
        label="Body Battery"
        value={bodyBatteryNet != null ? fmtSigned(bodyBatteryNet) : null}
        qualifier={bodyBatteryNet != null
          ? (bodyBatteryNet > 0 ? 'Net charged' : 'Net drained')
          : undefined}
        tone={bbTone(card.bbCharged, card.bbDrained)}
        detail={card.bbCharged != null && card.bbDrained != null
          ? `${card.bbCharged} charged · ${card.bbDrained} drained`
          : undefined}
        isLight={isLight}
      />
      <HeroTile
        label="HRV"
        value={card.hrvLastNight}
        unit="ms"
        qualifier={card.hrvFeedback?.text ?? card.hrvStatus}
        tone={hrvTone(card.hrvStatus)}
        detail={card.hrvWeekly != null ? `7-day avg ${card.hrvWeekly} ms` : undefined}
        isLight={isLight}
      />
      <HeroTile
        label="Load ratio"
        value={card.acwrRatio != null ? card.acwrRatio.toFixed(2) : null}
        qualifier={card.acwrStatus}
        tone={acwrTone(card.acwrRatio)}
        detail="acute / chronic load"
        isLight={isLight}
      />
      </div>
    </section>
  )
}

/** Vitals (resting HR, VO2 max, stress, SpO2) and activity (steps, distance, calories, floors). */
export function VitalsSection({ card }: { card: GarminCard }) {
  return (
    <>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Resting HR" value={card.restingHR ?? '–'} unit="bpm"
          sublabel={card.hr7dAvg != null ? `7d avg ${card.hr7dAvg}` : undefined}
          accent={toneColor(restingHrTone(card.restingHR, card.hr7dAvg))} />
        <StatCard label="VO2 max"
          value={card.vo2max != null ? card.vo2max.toFixed(1) : '–'}
          sublabel={card.vo2maxDate ? `updated ${card.vo2maxDate}` : undefined}
          accent={ACCENT} />
        <StatCard label="Stress avg" value={card.stressAvg ?? '–'}
          sublabel={card.stressMax != null ? `peak ${card.stressMax}` : undefined}
          accent={toneColor(stressTone(card.stressAvg))} />
        <StatCard label="SpO2"
          value={card.avgSpo2 != null ? `${Math.round(card.avgSpo2)}%` : '–'}
          sublabel={card.avgSpo2Sleep != null ? `sleep ${Math.round(card.avgSpo2Sleep)}%` : undefined}
          accent={toneColor(spo2Tone(card.avgSpo2))} />
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Steps" value={card.stepsToday?.toLocaleString() ?? '–'}
          sublabel={card.stepGoal != null ? `goal ${card.stepGoal.toLocaleString()}` : undefined}
          accent={ACCENT} />
        <StatCard label="Distance"
          value={fmtKm(card.distanceM)} unit="km"
          sublabel={card.distanceM != null ? `${card.distanceM.toLocaleString()} m walked` : undefined}
          accent={ACCENT} />
        <StatCard label="Calories"
          value={card.totalKcal != null ? Math.round(card.totalKcal).toLocaleString() : '–'}
          unit="kcal"
          sublabel={card.activeKcal != null ? `${Math.round(card.activeKcal)} active` : undefined}
          accent={ACCENT} />
        <StatCard label="Floors"
          value={card.floors != null ? Math.round(card.floors).toString() : '–'}
          sublabel={card.imVigorous != null || card.imModerate != null
            ? `IM ${(card.imVigorous ?? 0) + (card.imModerate ?? 0)} min`
            : undefined}
          accent={ACCENT} />
      </div>
    </>
  )
}
