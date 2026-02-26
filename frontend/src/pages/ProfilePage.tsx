import { useState } from 'react'
import { useAthleteProfile, useAthleteZones, useSyncStatus, useSportTypes, useGoals, useCreateGoal, useUpdateGoal, useDeleteGoal, useRateLimits } from '../api/hooks'
import { getSportColor } from '../constants/sportColors'
import { useTheme } from '../hooks/useTheme'
import clsx from 'clsx'

const HR_ZONE_COLORS = ['#6b7280', '#3b82f6', '#22c55e', '#eab308', '#ef4444']
const HR_ZONE_NAMES = ['Recovery', 'Aerobic', 'Tempo', 'Threshold', 'VO2max']

const METRIC_OPTIONS = [
  { value: 'distance_km', label: 'Distance (km)' },
  { value: 'time_hours', label: 'Time (hours)' },
  { value: 'activities', label: 'Activities' },
  { value: 'elevation_m', label: 'Elevation (m)' },
]

const PERIOD_OPTIONS = [
  { value: 'weekly', label: 'Weekly' },
  { value: 'monthly', label: 'Monthly' },
  { value: 'yearly', label: 'Yearly' },
]

function metricLabel(metric: string): string {
  return METRIC_OPTIONS.find(m => m.value === metric)?.label ?? metric
}

function periodLabel(period: string): string {
  return PERIOD_OPTIONS.find(p => p.value === period)?.label ?? period
}

export default function ProfilePage() {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const { data: profile, isLoading: profileLoading } = useAthleteProfile()
  const { data: zones } = useAthleteZones()
  const { data: syncStatus } = useSyncStatus()
  const { data: sportTypes } = useSportTypes()
  const { data: goals } = useGoals()
  const { data: rateLimits } = useRateLimits()
  const createGoal = useCreateGoal()
  const updateGoal = useUpdateGoal()
  const deleteGoal = useDeleteGoal()

  const [showGoalForm, setShowGoalForm] = useState(false)
  const [editingGoalId, setEditingGoalId] = useState<number | null>(null)
  const currentYear = new Date().getFullYear()
  const [goalForm, setGoalForm] = useState({ year: String(currentYear), sport_type: 'Run', metric: 'distance_km', period: 'weekly', target_value: '' })

  const cardClass = clsx(
    'rounded-xl border p-4',
    isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600',
  )

  const inputClass = clsx(
    'border rounded px-2 py-1.5 text-sm',
    isLight ? 'bg-white border-gray-200 text-gray-700' : 'bg-surface-800 border-surface-600 text-gray-200',
  )

  if (profileLoading) {
    return (
      <div className="max-w-4xl mx-auto space-y-6">
        {/* Skeleton header */}
        <div className={clsx(cardClass, 'p-6 flex items-center gap-6 animate-pulse')}>
          <div className={clsx('w-20 h-20 rounded-full', isLight ? 'bg-gray-200' : 'bg-surface-700')} />
          <div className="flex-1 space-y-3">
            <div className={clsx('h-6 w-40 rounded', isLight ? 'bg-gray-200' : 'bg-surface-700')} />
            <div className={clsx('h-4 w-28 rounded', isLight ? 'bg-gray-100' : 'bg-surface-700')} />
          </div>
        </div>
        {/* Skeleton info cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className={clsx(cardClass, 'animate-pulse')}>
              <div className={clsx('h-3 w-16 rounded mb-3', isLight ? 'bg-gray-200' : 'bg-surface-700')} />
              <div className={clsx('h-6 w-20 rounded', isLight ? 'bg-gray-200' : 'bg-surface-700')} />
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (!profile) {
    return (
      <div className="max-w-4xl mx-auto">
        <div className={clsx(cardClass, 'p-8 text-center')}>
          <p className="text-sm text-gray-500">Unable to load profile</p>
        </div>
      </div>
    )
  }

  const fullName = `${profile.firstname ?? ''} ${profile.lastname ?? ''}`.trim()
  const location = [profile.city, profile.state, profile.country].filter(Boolean).join(', ')
  const createdAt = profile.created_at ? new Date(profile.created_at).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' }) : null
  const updatedAt = profile.updated_at ? new Date(profile.updated_at).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' }) : null

  const hrZones = zones?.heart_rate?.zones as { min: number; max: number }[] | undefined
  const maxHr = zones?.heart_rate?.max_hr as number | undefined

  const handleGoalSubmit = () => {
    const target = parseFloat(goalForm.target_value)
    const yearNum = parseInt(goalForm.year)
    if (!target || target <= 0 || !yearNum) return
    const payload = { year: yearNum, sport_type: goalForm.sport_type, metric: goalForm.metric, period: goalForm.period, target_value: target }
    if (editingGoalId != null) {
      updateGoal.mutate({ id: editingGoalId, ...payload }, {
        onSuccess: () => { setEditingGoalId(null); setShowGoalForm(false) },
      })
    } else {
      createGoal.mutate(payload, {
        onSuccess: () => { setShowGoalForm(false); setGoalForm({ year: String(currentYear), sport_type: 'Run', metric: 'distance_km', period: 'weekly', target_value: '' }) },
      })
    }
  }

  const startEdit = (goal: Record<string, unknown>) => {
    setEditingGoalId(goal.id as number)
    setGoalForm({
      year: String(goal.year),
      sport_type: goal.sport_type as string,
      metric: goal.metric as string,
      period: goal.period as string,
      target_value: String(goal.target_value),
    })
    setShowGoalForm(true)
  }

  const cancelForm = () => {
    setShowGoalForm(false)
    setEditingGoalId(null)
    setGoalForm({ year: String(currentYear), sport_type: 'Run', metric: 'distance_km', period: 'weekly', target_value: '' })
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Profile header */}
      <div className={clsx(cardClass, 'p-6 flex items-center gap-6')}>
        {profile.profile_medium && profile.profile_medium !== 'avatar/athlete/large.png' ? (
          <img
            src={profile.profile_medium}
            alt={fullName}
            className={clsx('w-20 h-20 rounded-full border-2 object-cover', isLight ? 'border-gray-200' : 'border-surface-600')}
          />
        ) : (
          <div className={clsx(
            'w-20 h-20 rounded-full border-2 flex items-center justify-center text-3xl',
            isLight ? 'border-gray-200 bg-gray-100 text-gray-400' : 'border-surface-600 bg-surface-700 text-gray-500',
          )}>
            {(profile.firstname?.[0] ?? '?').toUpperCase()}
          </div>
        )}
        <div className="flex-1 min-w-0">
          <h1 className={clsx('text-2xl font-bold truncate', isLight ? 'text-gray-900' : 'text-white')}>{fullName || 'Athlete'}</h1>
          {profile.username && (
            <div className="text-sm text-gray-500">@{profile.username}</div>
          )}
          {location && (
            <div className="text-sm text-gray-400 mt-1">{location}</div>
          )}
        </div>
      </div>

      {/* Info grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className={cardClass}>
          <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Subscription</div>
          <div className="text-lg font-bold" style={{ color: (profile.premium || profile.summit) ? '#eab308' : '#6b7280' }}>
            {(profile.premium || profile.summit) ? 'Subscriber' : 'Free'}
          </div>
        </div>
        {profile.sex && (
          <div className={cardClass}>
            <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Gender</div>
            <div className={clsx('text-lg font-bold', isLight ? 'text-gray-900' : 'text-gray-100')}>{profile.sex === 'M' ? 'Male' : profile.sex === 'F' ? 'Female' : profile.sex}</div>
          </div>
        )}
        {profile.weight != null && profile.weight > 0 && (
          <div className={cardClass}>
            <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Weight</div>
            <div className={clsx('text-lg font-bold', isLight ? 'text-gray-900' : 'text-gray-100')}>{profile.weight} <span className="text-sm text-gray-400">kg</span></div>
          </div>
        )}
        {syncStatus?.total_activities != null && (
          <div className={cardClass}>
            <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Activities</div>
            <div className={clsx('text-lg font-bold', isLight ? 'text-gray-900' : 'text-gray-100')}>{syncStatus.total_activities}</div>
          </div>
        )}
        {createdAt && (
          <div className={cardClass}>
            <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Member Since</div>
            <div className={clsx('text-sm font-bold', isLight ? 'text-gray-900' : 'text-gray-100')}>{createdAt}</div>
          </div>
        )}
        {profile.follower_count != null && (
          <div className={cardClass}>
            <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Followers</div>
            <div className={clsx('text-lg font-bold', isLight ? 'text-gray-900' : 'text-gray-100')}>{profile.follower_count}</div>
          </div>
        )}
        {profile.friend_count != null && (
          <div className={cardClass}>
            <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Following</div>
            <div className={clsx('text-lg font-bold', isLight ? 'text-gray-900' : 'text-gray-100')}>{profile.friend_count}</div>
          </div>
        )}
        {profile.ftp != null && profile.ftp > 0 && (
          <div className={cardClass}>
            <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">FTP</div>
            <div className={clsx('text-lg font-bold', isLight ? 'text-gray-900' : 'text-gray-100')}>{profile.ftp} <span className="text-sm text-gray-400">W</span></div>
          </div>
        )}
        {updatedAt && (
          <div className={cardClass}>
            <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Last Updated</div>
            <div className={clsx('text-sm font-bold', isLight ? 'text-gray-900' : 'text-gray-100')}>{updatedAt}</div>
          </div>
        )}
      </div>

      {/* Heart Rate Zones */}
      {hrZones && hrZones.length > 0 && (
        <div className={cardClass}>
          <div className="text-xs text-gray-500 uppercase tracking-wider mb-4">Heart Rate Zones</div>
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
          <div className="text-[11px] text-gray-500 mt-3">
            {zones?.heart_rate?.custom_zones
              ? 'Custom zones from Strava'
              : `Estimated from activity data (max HR: ${maxHr ?? '?'} bpm)`}
          </div>
        </div>
      )}

      {/* Goals */}
      <div className={cardClass}>
        <div className="flex items-center justify-between mb-4">
          <div className="text-xs text-gray-500 uppercase tracking-wider">Goals</div>
          {!showGoalForm && (
            <button
              onClick={() => { setEditingGoalId(null); setGoalForm({ year: String(currentYear), sport_type: 'Run', metric: 'distance_km', period: 'weekly', target_value: '' }); setShowGoalForm(true) }}
              className={clsx(
                'text-xs px-3 py-1.5 rounded-lg transition-colors',
                isLight ? 'bg-gray-100 hover:bg-gray-200 text-gray-600' : 'bg-surface-700 hover:bg-surface-600 text-gray-300',
              )}
            >
              + Add Goal
            </button>
          )}
        </div>

        {/* Goal form */}
        {showGoalForm && (
          <div className={clsx('mb-4 p-3 rounded-lg space-y-3', isLight ? 'bg-gray-50' : 'bg-surface-700')}>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
              <input
                type="number" min="2020" max="2040" placeholder="Year"
                value={goalForm.year}
                onChange={e => setGoalForm(f => ({ ...f, year: e.target.value }))}
                className={inputClass}
              />
              <select
                value={goalForm.sport_type}
                onChange={e => setGoalForm(f => ({ ...f, sport_type: e.target.value }))}
                className={inputClass}
              >
                <option value="__all__">All Sports</option>
                {(sportTypes ?? []).map((s: string) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
              <select
                value={goalForm.metric}
                onChange={e => setGoalForm(f => ({ ...f, metric: e.target.value }))}
                className={inputClass}
              >
                {METRIC_OPTIONS.map(m => (
                  <option key={m.value} value={m.value}>{m.label}</option>
                ))}
              </select>
              <select
                value={goalForm.period}
                onChange={e => setGoalForm(f => ({ ...f, period: e.target.value }))}
                className={inputClass}
              >
                {PERIOD_OPTIONS.map(p => (
                  <option key={p.value} value={p.value}>{p.label}</option>
                ))}
              </select>
              <input
                type="number" step="any" min="0" placeholder="Target value"
                value={goalForm.target_value}
                onChange={e => setGoalForm(f => ({ ...f, target_value: e.target.value }))}
                className={inputClass}
              />
            </div>
            <div className="flex gap-2">
              <button
                onClick={handleGoalSubmit}
                disabled={!goalForm.target_value || parseFloat(goalForm.target_value) <= 0}
                className={clsx(
                  'text-xs px-3 py-1.5 rounded-lg transition-colors disabled:opacity-30',
                  isLight
                    ? 'bg-gray-900 text-white hover:bg-gray-800'
                    : 'bg-white/10 text-gray-300 hover:bg-white/15',
                )}
              >
                {editingGoalId != null ? 'Update' : 'Create'}
              </button>
              <button
                onClick={cancelForm}
                className={clsx(
                  'text-xs px-3 py-1.5 rounded-lg transition-colors',
                  isLight ? 'bg-gray-200 text-gray-600 hover:bg-gray-300' : 'bg-surface-600 hover:bg-surface-500 text-gray-300',
                )}
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* Goals list */}
        {goals && goals.length > 0 ? (
          <div className="space-y-2">
            {goals.map((goal: Record<string, unknown>) => {
              const sport = goal.sport_type as string
              const color = sport === '__all__' ? '#9ca3af' : getSportColor(sport)
              return (
                <div
                  key={goal.id as number}
                  className={clsx(
                    'flex items-center gap-3 py-2 px-2 rounded-lg transition-colors group',
                    isLight ? 'hover:bg-gray-50' : 'hover:bg-surface-700/50',
                  )}
                >
                  <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: color }} />
                  <span className="text-xs font-mono text-gray-500 min-w-[36px]">{goal.year as number}</span>
                  <span className={clsx('text-sm min-w-[80px]', isLight ? 'text-gray-700' : 'text-gray-300')}>{sport === '__all__' ? 'All Sports' : sport}</span>
                  <span className="text-xs text-gray-500">{metricLabel(goal.metric as string)}</span>
                  <span className="text-xs font-mono text-gray-400 ml-auto">{goal.target_value as number} / {periodLabel(goal.period as string).toLowerCase()}</span>
                  <button
                    onClick={() => startEdit(goal)}
                    className={clsx('text-xs opacity-0 group-hover:opacity-100 transition-opacity', isLight ? 'text-gray-400 hover:text-gray-600' : 'text-gray-500 hover:text-gray-300')}
                  >
                    Edit
                  </button>
                  <button
                    onClick={() => deleteGoal.mutate(goal.id as number)}
                    className="text-xs text-red-400 hover:text-red-300 opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    Delete
                  </button>
                </div>
              )
            })}
          </div>
        ) : !showGoalForm ? (
          <div className={clsx('text-sm', isLight ? 'text-gray-400' : 'text-gray-600')}>No goals set. Add a goal to track your progress.</div>
        ) : null}
      </div>

      {/* Strava API Rate Limits */}
      {rateLimits && (
        <div className={cardClass}>
          <div className="text-xs text-gray-500 uppercase tracking-wider mb-4">Strava API Rate Limits</div>
          <div className="space-y-3">
            {[
              { label: '15-minute', data: rateLimits.fifteen_min },
              { label: 'Daily', data: rateLimits.daily },
            ].map(({ label, data }) => {
              const pct = data.limit > 0 ? (data.usage / data.limit) * 100 : 0
              const isOver = data.usage >= data.limit
              const isWarning = pct >= 80
              const barColor = isOver ? '#ef4444' : isWarning ? '#eab308' : '#22c55e'
              return (
                <div key={label}>
                  <div className="flex items-center justify-between mb-1">
                    <span className={clsx('text-sm', isLight ? 'text-gray-600' : 'text-gray-400')}>{label}</span>
                    <span className="text-sm font-mono" style={{ color: barColor }}>
                      {data.usage.toLocaleString()} <span className="text-gray-500">/</span> {data.limit.toLocaleString()}
                    </span>
                  </div>
                  <div className={clsx('h-2 rounded-full overflow-hidden', isLight ? 'bg-gray-100' : 'bg-surface-700')}>
                    <div
                      className="h-full rounded-full transition-all"
                      style={{ width: `${Math.min(pct, 100)}%`, backgroundColor: barColor }}
                    />
                  </div>
                </div>
              )
            })}
          </div>
          <div className="text-[11px] text-gray-500 mt-3">
            Daily limit resets at midnight UTC
          </div>
        </div>
      )}

    </div>
  )
}
