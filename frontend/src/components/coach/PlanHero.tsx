import clsx from 'clsx'
import type { CoachPlan } from '../../api/hooks'
import { getSportColor } from '../../constants/sportColors'
import { useTheme } from '../../hooks/useTheme'
import { parseLocalDate } from '../../utils/dates'
import { formatClockDuration } from '../../utils/formatSpeed'
import GoalRing from '../shared/GoalRing'
import HeroStat from '../shared/HeroStat'
import { fmtDayDate } from '../garmin/garmin'

const DAY_MS = 86_400_000

function days(fromIso: string, toIso: string): number {
  return Math.round((parseLocalDate(toIso).getTime() - parseLocalDate(fromIso).getTime()) / DAY_MS)
}

function signedClock(seconds: number): string {
  return `${seconds > 0 ? '+' : '−'}${formatClockDuration(Math.abs(seconds))}`
}

/** The plan's hero, in the Year page's form: the share of the plan done on the ring (with
 *  where you should be by now), the race, the goal against the prediction, and this week. */
export default function PlanHero({ plan }: { plan: CoachPlan }) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const p = plan.progress
  const race = plan.race
  const accent = getSportColor(race?.sport_type ?? 'Run')
  const finished = plan.status !== 'active' || p.days_to_race < 0
  const { total, due, done } = p.sessions
  const missed = due - done
  const pred = p.prediction
  const goalS = plan.goal_time_s
  const thisWeek = p.weeks.find(w => w.week_start <= p.today && days(w.week_start, p.today) < 7)
  const weekIndex = thisWeek ? p.weeks.indexOf(thisWeek) : -1
  const blockDays = days(plan.start_date, plan.end_date) + 1
  const dayOfBlock = Math.min(blockDays, Math.max(0, days(plan.start_date, p.today) + 1))
  const raceDate = race?.date ?? plan.end_date
  const result = p.result?.time_s ?? null
  // The time to compare with the goal: the race once run, today's prediction before
  const compared = finished ? result : pred?.now_s ?? null

  const status = finished
    ? { label: 'Finished', tone: 'neutral' as const }
    : missed > 0
      ? { label: `${missed} missed`, tone: 'negative' as const }
      : { label: 'On track', tone: 'positive' as const }

  // Where the prediction leaves you when the goal time crosses the line
  const shortM = !finished && race?.distance_km && goalS && compared && compared > goalS
    ? Math.round(race.distance_km * (1 - goalS / compared) * 100) * 10
    : null

  return (
    <section
      className="panel hero-brackets relative p-6 md:p-8 grid gap-8 md:gap-10 md:grid-cols-[minmax(0,auto)_1fr]"
      style={{ ['--card-accent' as string]: accent }}
    >
      <div className="flex items-center justify-center md:justify-start">
        <GoalRing
          progress={total ? done / total : 0}
          pace={!finished && total ? due / total : undefined}
          accent={accent}
          size={260}
          stroke={10}
          label={`${total ? Math.round((done / total) * 100) : 0}% of the plan`}
          value={String(done)}
          subValue={`of ${total} sessions`}
          status={status}
        />
      </div>

      <div className="flex flex-col justify-center min-w-0">
        <div className="grid grid-cols-2 gap-x-8 gap-y-5">
          {finished ? (
            <HeroStat
              label="Race"
              value={result != null ? formatClockDuration(result) : '—'}
              footnote={p.result?.distance_km != null ? `${p.result.distance_km.toFixed(1)} km on ${fmtDayDate(raceDate)}` : fmtDayDate(raceDate)}
              accent={accent}
            />
          ) : (
            <HeroStat
              label="Race day"
              value={String(p.days_to_race)}
              unit="days"
              footnote={`${fmtDayDate(raceDate)}${race?.location ? `, ${race.location}` : ''}`}
              accent={accent}
            />
          )}
          <HeroStat
            label="vs. Goal"
            value={goalS != null && compared != null ? signedClock(Math.round(compared - goalS)) : '—'}
            tone={goalS == null || compared == null ? 'neutral' : compared <= goalS ? 'positive' : 'negative'}
            footnote={
              goalS == null ? plan.goal ?? undefined
              : finished ? `goal ${formatClockDuration(goalS)}`
              : `predicted ${compared != null ? formatClockDuration(compared) : '—'} for ${formatClockDuration(goalS)}${shortM ? `, ${shortM} m short` : ''}`
            }
          />
          {finished ? (
            <HeroStat label="Sessions done" value={p.sessions.completion_pct != null ? `${p.sessions.completion_pct}%` : '—'} footnote={`${done} of ${due}`} />
          ) : (
            <HeroStat
              label="This week"
              value={thisWeek?.done_km != null ? String(thisWeek.done_km) : '—'}
              unit="km"
              footnote={thisWeek ? `of ${thisWeek.planned_km} planned` : undefined}
            />
          )}
          <HeroStat
            label="Avg score"
            value={p.score.average != null ? String(p.score.average) : '—'}
            footnote={p.score.scored ? `${p.score.scored} sessions scored` : 'no sessions scored yet'}
          />
        </div>

        {!finished && (
          <div className="mt-6 pt-5 border-t border-dashed border-surface-600/40">
            <div className="flex items-center justify-between text-[10px] uppercase tracking-[0.15em] text-gray-500 mb-2">
              <span>{weekIndex >= 0 ? `Week ${weekIndex + 1} of ${p.weeks.length}${p.phase ? ` · ${p.phase}` : ''}` : 'Block elapsed'}</span>
              <span className="tabular-nums font-mono">
                Day <span style={{ color: accent }}>{dayOfBlock}</span> / {blockDays}
              </span>
            </div>
            <div className={clsx('h-[3px] rounded-full overflow-hidden', isLight ? 'bg-gray-200' : 'bg-surface-700')}>
              <div
                className="h-full rounded-full transition-all duration-700 ease-out"
                style={{ width: `${(dayOfBlock / blockDays) * 100}%`, backgroundColor: accent, opacity: 0.8 }}
              />
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
