import type { PlanAccomplishment, Streaks } from '../../api/hooks'
import { useTheme } from '../../hooks/useTheme'
import { scoreColor } from '../../utils/scoreColor'
import { CheckIcon } from '../icons'

/* ── Streak badge — current or best, with uppercase label ──────── */
function StreakBadge({ value, label, kind, title }: { value: number; label: string; kind: 'current' | 'best'; title?: string }) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const accent = kind === 'best'
    ? (isLight ? '#b45309' : '#fbbf24') // amber
    : (isLight ? '#111827' : '#f3f4f6') // neutral strong
  return (
    <div
      className="panel flex items-center gap-1.5 px-2.5 py-1"
      title={title}
    >
      {kind === 'best' ? (
        <svg width="11" height="11" viewBox="0 0 16 16" fill="none" className="shrink-0" aria-hidden="true">
          <path d="M9 1.5L4 9h4l-1 5.5L12 7H8z" fill={accent} />
        </svg>
      ) : (
        <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke={accent} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="shrink-0" aria-hidden="true">
          <circle cx="10" cy="3" r="1.5" fill={accent} stroke="none" />
          <path d="M5 7l3-1.5 2 2.5 2-1M4 10l3 1 1.5-2M6 12.5l1 2.5M9.5 10l1 5" />
        </svg>
      )}
      <span className="text-xs font-mono tabular-nums font-semibold" style={{ color: accent }}>{value}</span>
      <span className="eyebrow text-[9px]">{label}</span>
    </div>
  )
}

/* ── Plan accomplishment badge — % of planned sessions executed ── */
function PlanRateBadge({ rate, label, title }: { rate: number; label: string; title?: string }) {
  const accent = scoreColor(rate)
  return (
    <div
      className="panel flex items-center gap-1.5 px-2.5 py-1"
      title={title}
    >
      <span style={{ color: accent }}><CheckIcon size={11} /></span>
      <span className="text-xs font-mono tabular-nums font-semibold" style={{ color: accent }}>
        {Math.round(rate)}%
      </span>
      <span className="eyebrow text-[9px]">{label}</span>
    </div>
  )
}

/** Day and week streaks plus plan accomplishment, under the calendar header. */
export default function CalendarBadges({ streaks, planRate }: {
  streaks: Streaks | undefined
  planRate: PlanAccomplishment | undefined
}) {
  if (!((streaks && (streaks.current_streak > 0 || streaks.longest_streak > 0 || (streaks.current_week_streak ?? 0) > 0 || (streaks.longest_week_streak ?? 0) > 0)) || planRate?.rate != null)) return null
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      {streaks && streaks.current_streak > 0 && (
        <StreakBadge
          value={streaks.current_streak}
          label={`day${streaks.current_streak !== 1 ? 's' : ''}`}
          kind="current"
          title="Current streak — consecutive days with activities"
        />
      )}
      {streaks && streaks.longest_streak > 0 && (
        <StreakBadge
          value={streaks.longest_streak}
          label="best days"
          kind="best"
          title={`Longest day streak: ${streaks.longest_streak_start} to ${streaks.longest_streak_end}`}
        />
      )}
      {streaks && streaks.current_week_streak != null && streaks.current_week_streak > 0 && (
        <StreakBadge
          value={streaks.current_week_streak}
          label={`wk${streaks.current_week_streak !== 1 ? 's' : ''}`}
          kind="current"
          title="Current streak — consecutive weeks with activities"
        />
      )}
      {streaks && streaks.longest_week_streak != null && streaks.longest_week_streak > 0 && (
        <StreakBadge
          value={streaks.longest_week_streak}
          label="best wks"
          kind="best"
          title={`Longest week streak: ${streaks.longest_week_streak_start} to ${streaks.longest_week_streak_end}`}
        />
      )}
      {/* All-time plan rate splits into a recent badge only once history outgrows the window */}
      {planRate?.rate != null && (
        <>
          {planRate.recent_rate != null && planRate.recent_planned < planRate.total_planned && (
            <PlanRateBadge
              rate={planRate.recent_rate}
              label="plan 4wk"
              title={`Plan accomplishment, last ${planRate.window_days} days: ${planRate.recent_completed} of ${planRate.recent_planned} planned sessions completed`}
            />
          )}
          <PlanRateBadge
            rate={planRate.rate}
            label={planRate.recent_planned < planRate.total_planned ? 'plan all' : 'plan'}
            title={`Plan accomplishment, all time: ${planRate.total_completed} of ${planRate.total_planned} planned sessions completed`}
          />
        </>
      )}
    </div>
  )
}
