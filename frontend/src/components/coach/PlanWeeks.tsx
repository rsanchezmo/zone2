import clsx from 'clsx'
import { Link } from 'react-router-dom'
import type { CoachPlan, CoachPlanSession } from '../../api/hooks'
import { useTheme } from '../../hooks/useTheme'
import { dateToLocalStr, parseLocalDate } from '../../utils/dates'
import { scoreColor } from '../../utils/scoreColor'
import { fmtDate, fmtDayDate } from '../garmin/garmin'

function mondayOf(iso: string): string {
  const d = parseLocalDate(iso)
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7))
  return dateToLocalStr(d)
}

function Status({ s, today }: { s: CoachPlanSession; today: string }) {
  if (s.done) return <span className="text-green-500" title="Done">✓</span>
  if (s.date < today) return <span className="text-red-500" title="Missed">✗</span>
  return <span className="text-gray-500" title={s.date === today ? 'Today' : 'Upcoming'}>{s.date === today ? '●' : '·'}</span>
}

/** The plan's sessions week by week, each with whether it was done and how it scored. */
export function PlanWeeks({ plan }: { plan: CoachPlan }) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const today = plan.progress.today
  const weeks = plan.progress.weeks.map(w => ({
    ...w,
    sessions: plan.sessions.filter(s => mondayOf(s.date) === w.week_start),
  }))
  return (
    <section>
      <div className="section-head mb-4"><span className="eyebrow">Sessions</span></div>
      <div className="space-y-3">
        {weeks.map((w, i) => {
          const current = w.week_start <= today && today < addDays(w.week_start, 7)
          return (
            <div key={w.week_start} className={clsx('panel p-4', current && 'ring-1 ring-red-500/30')}>
              <div className="flex items-baseline justify-between gap-4 mb-2">
                <div className="text-[12px]">
                  <span className={clsx('font-semibold', isLight ? 'text-gray-900' : 'text-gray-100')}>Week {i + 1}</span>
                  <span className="text-gray-500"> · {fmtDate(w.week_start)}{w.phase && ` · ${w.phase}`}</span>
                </div>
                <div className="text-[11px] font-mono tabular-nums text-gray-500">
                  {w.done_km != null && `${w.done_km} run · `}{w.planned_km} planned{w.target_km != null && ` · ${w.target_km} target`} km
                </div>
              </div>
              {w.sessions.length === 0 ? (
                <p className="text-[11px] text-gray-500">No sessions in the plan this week.</p>
              ) : (
                <ul className="divide-y divide-current/5">
                  {w.sessions.map(s => (
                    <li key={s.id} className="flex items-center gap-3 py-1.5 text-[13px]">
                      <span className="w-4 text-center"><Status s={s} today={today} /></span>
                      <span className="w-24 shrink-0 text-[11px] text-gray-500">{fmtDayDate(s.date)}</span>
                      <span className={clsx('min-w-0 flex-1 truncate', isLight ? 'text-gray-800' : 'text-gray-200')} title={s.description ?? undefined}>
                        {s.title}
                        {s.planned_distance_km != null && <span className="font-mono text-gray-500"> · {s.planned_distance_km} km</span>}
                      </span>
                      {s.garmin_sync_state === 'failed' && <span className="text-[10px] text-red-500" title="The watch didn't get this session">watch failed</span>}
                      {s.score != null && (
                        <span className="font-mono tabular-nums text-[12px] font-semibold" style={{ color: scoreColor(s.score) }} title="Execution score">{s.score}</span>
                      )}
                      {s.activity_id != null && (
                        <Link to={`/activities/${s.activity_id}`} className="text-[11px] text-gray-500 hover:text-cyan-500">run ›</Link>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}

function addDays(iso: string, days: number): string {
  const d = parseLocalDate(iso)
  d.setDate(d.getDate() + days)
  return dateToLocalStr(d)
}

/** Tests and key sessions whose result decides the plan, with the rule agreed before. */
export function Checkpoints({ plan }: { plan: CoachPlan }) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  if (!plan.checkpoints.length) return null
  return (
    <section>
      <div className="section-head mb-4"><span className="eyebrow">Checkpoints</span></div>
      <div className="grid md:grid-cols-2 gap-3">
        {plan.checkpoints.map(c => (
          <div key={c.id} className="panel p-4 space-y-2">
            <div className="flex items-baseline justify-between gap-3">
              <span className={clsx('text-sm font-semibold', isLight ? 'text-gray-900' : 'text-gray-100')}>{c.title}</span>
              <span className="text-[11px] text-gray-500 shrink-0">{fmtDayDate(c.date)}</span>
            </div>
            <p className="text-[12px] text-gray-500 leading-relaxed">{c.rule}</p>
            {c.result ? (
              <div className="text-[12px] leading-relaxed">
                <span className={isLight ? 'text-gray-900' : 'text-gray-100'}>{c.result}</span>
                {c.decision && <span className="text-gray-500"> → {c.decision}</span>}
              </div>
            ) : (
              <div className="text-[11px] eyebrow">Pending</div>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}
