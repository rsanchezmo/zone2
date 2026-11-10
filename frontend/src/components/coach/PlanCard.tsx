import clsx from 'clsx'
import { Link } from 'react-router-dom'
import type { CoachPlanSummary } from '../../api/hooks'
import { getSportColor } from '../../constants/sportColors'
import { useTheme } from '../../hooks/useTheme'
import { formatClockDuration } from '../../utils/formatSpeed'
import { scoreColor } from '../../utils/scoreColor'
import { fmtDate } from '../garmin/garmin'

const STATUS_LABEL: Record<CoachPlanSummary['status'], string> = { active: 'Active', done: 'Done', abandoned: 'Stopped' }
const SIZE = 88

/** The share of the plan's sessions done, in the box where an activity card shows its route. */
function CompletionThumb({ plan, color }: { plan: CoachPlanSummary; color: string }) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const { total, due, done } = plan.sessions
  const r = 30, c = 2 * Math.PI * r
  const share = total ? done / total : 0
  const pace = plan.status === 'active' && total ? due / total : null
  return (
    <div
      className={'shrink-0 rounded-lg border flex items-center justify-center bg-surface-700 border-surface-600'}
      style={{ width: SIZE, height: SIZE }}
      aria-hidden="true"
    >
      <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`}>
        <g transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}>
          <circle cx={SIZE / 2} cy={SIZE / 2} r={r} fill="none" stroke={isLight ? '#e5e7eb' : '#262626'} strokeWidth={5} />
          <circle cx={SIZE / 2} cy={SIZE / 2} r={r} fill="none" stroke={color} strokeWidth={5} strokeLinecap="round"
            strokeDasharray={`${c * share} ${c}`} />
          {pace != null && (
            <line x1={SIZE / 2 + r - 5} x2={SIZE / 2 + r + 5} y1={SIZE / 2} y2={SIZE / 2}
              stroke={isLight ? '#111827' : '#f3f4f6'} strokeWidth={1.5}
              transform={`rotate(${pace * 360} ${SIZE / 2} ${SIZE / 2})`} />
          )}
        </g>
        <text x="50%" y="50%" dominantBaseline="central" textAnchor="middle" fontSize={15} fontWeight={600}
          className="font-mono" fill={isLight ? '#111827' : '#f3f4f6'}>
          {Math.round(share * 100)}%
        </text>
      </svg>
    </div>
  )
}

function Stat({ icon, value, unit, valueColor }: { icon: React.ReactNode; value: string; unit?: string; valueColor?: string }) {
  const { theme } = useTheme()
  return (
    <div className="flex items-center gap-1.5">
      {icon}
      <span className={clsx('text-sm font-mono font-semibold', theme === 'light' ? 'text-gray-900' : 'text-gray-100')} style={valueColor ? { color: valueColor } : undefined}>
        {value}
      </span>
      {unit && <span className="text-[10px] text-gray-500 uppercase tracking-wider">{unit}</span>}
    </div>
  )
}

const icon = (d: React.ReactNode, className = 'text-gray-500') => (
  <svg className={clsx('w-3.5 h-3.5', className)} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">{d}</svg>
)

/** A plan in the list, shaped like an activity card: completion, race, sessions, score and the goal. */
export default function PlanCard({ plan }: { plan: CoachPlanSummary }) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const color = getSportColor(plan.race?.sport_type ?? 'Run')
  const active = plan.status === 'active' && plan.days_to_race >= 0
  const compared = plan.status === 'active' ? plan.prediction_s : plan.result_s
  const vsGoal = plan.goal_time_s != null && compared != null ? Math.round(compared - plan.goal_time_s) : null
  const { done, due, total } = plan.sessions
  return (
    <Link
      to={`/coach/${plan.id}`}
      className={clsx(
        'group flex items-center gap-3.5 rounded-xl border card-glow transition-all duration-200 p-3.5',
        'bg-surface-800 border-surface-600 hover:border-surface-500',
      )}
      style={{ borderLeftWidth: 3, borderLeftColor: color, '--card-accent': color } as React.CSSProperties}
    >
      <CompletionThumb plan={plan} color={color} />

      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className={clsx('font-semibold tracking-tight truncate transition-colors', isLight ? 'text-gray-900 group-hover:text-gray-950' : 'text-gray-100 group-hover:text-white')}>
              {plan.name}
            </div>
            <div className="flex items-center gap-2 mt-1.5 flex-wrap">
              <span
                className="inline-flex items-center gap-1 text-[10px] uppercase tracking-[0.15em] px-2 py-0.5 rounded-full border font-semibold"
                style={active ? { backgroundColor: color + '15', color, borderColor: `${color}40` } : undefined}
              >
                <span className="w-1 h-1 rounded-full" style={{ backgroundColor: active ? color : 'currentColor' }} aria-hidden="true" />
                {active && plan.phase ? plan.phase : STATUS_LABEL[plan.status]}
              </span>
              <span className="text-[11px] font-mono tabular-nums text-gray-500">
                {fmtDate(plan.start_date)} – {fmtDate(plan.end_date)}
                {plan.race && ` · ${plan.race.name}`}
              </span>
            </div>
          </div>
          <svg
            className={clsx('w-4 h-4 shrink-0 mt-1 transition-transform duration-200 group-hover:translate-x-0.5', isLight ? 'text-gray-300' : 'text-gray-600')}
            fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true"
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        </div>

        <div className="flex items-center gap-4 mt-3 flex-wrap tabular-nums">
          <Stat
            icon={icon(<path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />)}
            value={`${done}/${total}`}
            unit={due < total ? `sessions · ${due} due` : 'sessions'}
          />
          {plan.average_score != null && (
            <Stat
              icon={icon(<path strokeLinecap="round" strokeLinejoin="round" d="M12 3l2.6 5.6 6.1.7-4.5 4.2 1.2 6L12 16.6 6.6 19.5l1.2-6L3.3 9.3l6.1-.7z" />)}
              value={String(plan.average_score)}
              unit="score"
              valueColor={scoreColor(plan.average_score)}
            />
          )}
          {active && (
            <Stat
              icon={icon(<><path strokeLinecap="round" d="M4 21V4M4 4l9 4-9 4" /></>)}
              value={String(plan.days_to_race)}
              unit="days to race"
            />
          )}
          {plan.goal_time_s != null && (
            <Stat
              icon={icon(<><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="4" /></>)}
              value={formatClockDuration(plan.goal_time_s)}
              unit={vsGoal != null ? `goal · ${vsGoal > 0 ? '+' : '−'}${formatClockDuration(Math.abs(vsGoal))} ${plan.status !== 'active' ? 'raced' : plan.prediction_source === 'garmin' ? 'by Garmin' : 'predicted'}` : 'goal'}
            />
          )}
          {plan.goal_time_s == null && plan.result_s != null && (
            <Stat
              icon={icon(<><circle cx="12" cy="12" r="10" /><path strokeLinecap="round" d="M12 6v6l4 2" /></>)}
              value={formatClockDuration(plan.result_s)}
              unit="raced"
            />
          )}
        </div>
      </div>
    </Link>
  )
}
