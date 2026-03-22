import { useState } from 'react'
import { useMemo } from 'react'
import { useAthleteProfile, useAthleteZones, useSyncStatus, useSportTypes, useGoals, useGoalProgress, useCreateGoal, useUpdateGoal, useDeleteGoal, useRateLimits, useCacheCompleteness, useBackfillStreams } from '../api/hooks'
import { getSportColor } from '../constants/sportColors'
import { getSportCategory } from '../utils/formatSpeed'
import { useTheme } from '../hooks/useTheme'
import { useToast } from '../hooks/useToast'
import clsx from 'clsx'

const HR_ZONE_COLORS = ['#6b7280', '#3b82f6', '#22c55e', '#eab308', '#ef4444']
const HR_ZONE_NAMES = ['Recovery', 'Aerobic', 'Tempo', 'Threshold', 'VO2max']

function getMetricOptions(sportType: string) {
  const isSwimming = getSportCategory(sportType) === 'swimming'
  return [
    { value: 'distance_km', label: isSwimming ? 'Distance (m)' : 'Distance (km)' },
    { value: 'time_hours', label: 'Time (hours)' },
    { value: 'activities', label: 'Activities' },
    { value: 'elevation_m', label: 'Elevation (m)' },
  ]
}

const PERIOD_OPTIONS = [
  { value: 'weekly', label: 'Weekly' },
  { value: 'monthly', label: 'Monthly' },
  { value: 'yearly', label: 'Yearly' },
]

function metricLabel(metric: string, sportType?: string): string {
  return getMetricOptions(sportType ?? 'Run').find(m => m.value === metric)?.label ?? metric
}

function periodLabel(period: string): string {
  return PERIOD_OPTIONS.find(p => p.value === period)?.label ?? period
}

export default function ProfilePage() {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const { toast } = useToast()
  const { data: profile, isLoading: profileLoading } = useAthleteProfile()
  const { data: zones } = useAthleteZones()
  const { data: syncStatus } = useSyncStatus()
  const { data: sportTypes } = useSportTypes()
  const { data: goals } = useGoals()
  const todayStr = useMemo(() => new Date().toISOString().slice(0, 10), [])
  const { data: goalProgressData } = useGoalProgress(todayStr)
  const { data: rateLimits } = useRateLimits()
  const { data: cacheCompleteness } = useCacheCompleteness()
  const backfillStreams = useBackfillStreams()
  const createGoal = useCreateGoal()
  const updateGoal = useUpdateGoal()
  const deleteGoal = useDeleteGoal()

  const [showCacheDetails, setShowCacheDetails] = useState(false)
  const [showGoalForm, setShowGoalForm] = useState(false)
  const [editingGoalId, setEditingGoalId] = useState<number | null>(null)
  const currentYear = new Date().getFullYear()
  const [goalForm, setGoalForm] = useState({ year: String(currentYear), sport_type: 'Run', metric: 'distance_km', period: 'weekly', target_value: '' })

  const cardClass = clsx(
    'rounded-xl border p-4',
    isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600',
  )

  const inputClass = 'input'
  const selectClass = 'select'

  // Build a lookup: goal id → progress data
  const progressMap = useMemo(() => {
    const map = new Map<number, { current_value: number; percentage: number; period_start: string; period_end: string }>()
    if (goalProgressData?.goals) {
      for (const g of goalProgressData.goals) {
        map.set(g.id, g)
      }
    }
    return map
  }, [goalProgressData])

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
    let target = parseFloat(goalForm.target_value)
    const yearNum = parseInt(goalForm.year)
    if (!target || target <= 0 || !yearNum) return
    // Convert meters to km for swimming distance goals (backend stores km)
    if (goalForm.metric === 'distance_km' && getSportCategory(goalForm.sport_type) === 'swimming') {
      target = target / 1000
    }
    const payload = { year: yearNum, sport_type: goalForm.sport_type, metric: goalForm.metric, period: goalForm.period, target_value: target }
    if (editingGoalId != null) {
      updateGoal.mutate({ id: editingGoalId, ...payload }, {
        onSuccess: () => { setEditingGoalId(null); setShowGoalForm(false); toast('Goal updated', 'success') },
        onError: () => toast('Failed to update goal', 'error'),
      })
    } else {
      createGoal.mutate(payload, {
        onSuccess: () => { setShowGoalForm(false); setGoalForm({ year: String(currentYear), sport_type: 'Run', metric: 'distance_km', period: 'weekly', target_value: '' }); toast('Goal created', 'success') },
        onError: () => toast('Failed to create goal', 'error'),
      })
    }
  }

  const startEdit = (goal: Record<string, unknown>) => {
    setEditingGoalId(goal.id as number)
    // Convert km back to meters for swimming distance goals
    let displayValue = goal.target_value as number
    if (goal.metric === 'distance_km' && getSportCategory(goal.sport_type as string) === 'swimming') {
      displayValue = displayValue * 1000
    }
    setGoalForm({
      year: String(goal.year),
      sport_type: goal.sport_type as string,
      metric: goal.metric as string,
      period: goal.period as string,
      target_value: String(displayValue),
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
                className={selectClass}
              >
                <option value="__all__">All Sports</option>
                {(sportTypes ?? []).map((s: string) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
              <select
                value={goalForm.metric}
                onChange={e => setGoalForm(f => ({ ...f, metric: e.target.value }))}
                className={selectClass}
              >
                {getMetricOptions(goalForm.sport_type).map(m => (
                  <option key={m.value} value={m.value}>{m.label}</option>
                ))}
              </select>
              <select
                value={goalForm.period}
                onChange={e => setGoalForm(f => ({ ...f, period: e.target.value }))}
                className={selectClass}
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
                className="btn"
              >
                {editingGoalId != null ? 'Update' : 'Create'}
              </button>
              <button
                onClick={cancelForm}
                className="btn"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* Goals list with progress */}
        {goals && goals.length > 0 ? (
          <div className="space-y-3">
            {goals.map((goal: Record<string, unknown>) => {
              const sport = goal.sport_type as string
              const color = sport === '__all__' ? '#9ca3af' : getSportColor(sport)
              const metric = goal.metric as string
              const isSwimmingDist = metric === 'distance_km' && getSportCategory(sport) === 'swimming'
              const targetRaw = goal.target_value as number
              const targetDisplay = isSwimmingDist ? Math.round(targetRaw * 1000) : targetRaw
              const targetUnit = isSwimmingDist ? 'm' : metric === 'distance_km' ? 'km' : metric === 'time_hours' ? 'hrs' : metric === 'elevation_m' ? 'm' : ''

              const progress = progressMap.get(goal.id as number)
              const currentRaw = progress?.current_value ?? null
              const currentDisplay = currentRaw !== null ? (isSwimmingDist ? Math.round(currentRaw * 1000) : Math.round(currentRaw * 10) / 10) : null
              const pct = progress?.percentage ?? null
              const clampedPct = pct !== null ? Math.min(pct, 100) : 0

              // Color logic: green if >=100%, sport color otherwise
              const barColor = pct !== null && pct >= 100 ? '#22c55e' : color

              return (
                <div
                  key={goal.id as number}
                  className={clsx(
                    'rounded-xl border p-3 group transition-all duration-200',
                    isLight ? 'bg-white border-gray-200 hover:border-gray-300' : 'bg-surface-800 border-surface-600 hover:border-surface-500',
                  )}
                  style={{ borderLeftWidth: 3, borderLeftColor: barColor }}
                >
                  {/* Top row: sport, metric, period, actions */}
                  <div className="flex items-center gap-2 mb-2">
                    <span className={clsx('text-sm font-medium', isLight ? 'text-gray-800' : 'text-gray-200')}>
                      {sport === '__all__' ? 'All Sports' : sport}
                    </span>
                    <span className={clsx('text-[11px] px-1.5 py-0.5 rounded-md', isLight ? 'bg-gray-100 text-gray-500' : 'bg-surface-700 text-gray-400')}>
                      {metricLabel(metric, sport)}
                    </span>
                    <span className={clsx('text-[11px] px-1.5 py-0.5 rounded-md', isLight ? 'bg-gray-100 text-gray-500' : 'bg-surface-700 text-gray-400')}>
                      {periodLabel(goal.period as string).toLowerCase()}
                    </span>
                    <span className="text-[11px] text-gray-500 font-mono">{goal.year as number}</span>
                    <div className="ml-auto flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button
                        onClick={() => startEdit(goal)}
                        className={clsx('text-[11px] px-1.5 py-0.5 rounded', isLight ? 'text-gray-400 hover:text-gray-600 hover:bg-gray-100' : 'text-gray-500 hover:text-gray-300 hover:bg-surface-700')}
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => deleteGoal.mutate(goal.id as number, {
                          onSuccess: () => toast('Goal deleted', 'success'),
                          onError: () => toast('Failed to delete goal', 'error'),
                        })}
                        className="text-[11px] px-1.5 py-0.5 rounded text-red-400 hover:text-red-300 hover:bg-red-500/10"
                      >
                        Delete
                      </button>
                    </div>
                  </div>

                  {/* Progress bar */}
                  <div className="flex items-center gap-3">
                    <div className="flex-1">
                      <div className={clsx('h-2 rounded-full overflow-hidden', isLight ? 'bg-gray-100' : 'bg-surface-700')}>
                        <div
                          className="h-full rounded-full transition-all duration-700 ease-out"
                          style={{ width: `${clampedPct}%`, backgroundColor: barColor }}
                        />
                      </div>
                    </div>
                    <div className="text-right shrink-0 min-w-[100px]">
                      {currentDisplay !== null ? (
                        <span className="text-sm font-mono font-medium" style={{ color: barColor }}>
                          {currentDisplay}
                          <span className="text-gray-500 mx-0.5">/</span>
                          {targetDisplay}
                          {targetUnit && <span className="text-[11px] text-gray-500 ml-0.5">{targetUnit}</span>}
                        </span>
                      ) : (
                        <span className="text-sm font-mono text-gray-500">
                          — / {targetDisplay}{targetUnit && <span className="text-[11px] ml-0.5">{targetUnit}</span>}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Percentage badge */}
                  {pct !== null && (
                    <div className="flex items-center gap-2 mt-1.5">
                      <span className={clsx(
                        'text-[11px] font-semibold px-1.5 py-0.5 rounded-md',
                        pct >= 100
                          ? (isLight ? 'bg-green-100 text-green-700' : 'bg-green-500/15 text-green-400')
                          : pct >= 70
                            ? (isLight ? 'bg-blue-100 text-blue-700' : 'bg-blue-500/15 text-blue-400')
                            : (isLight ? 'bg-gray-100 text-gray-600' : 'bg-surface-700 text-gray-400'),
                      )}>
                        {pct >= 100 ? 'Done!' : `${Math.round(pct)}%`}
                      </span>
                      {progress?.period_start && progress?.period_end && (
                        <span className="text-[10px] text-gray-500">
                          {new Date(progress.period_start).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                          {' — '}
                          {new Date(progress.period_end).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                        </span>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        ) : !showGoalForm ? (
          <div className={clsx('text-sm', isLight ? 'text-gray-400' : 'text-gray-600')}>No goals set. Add a goal to track your progress.</div>
        ) : null}
      </div>

      {/* Cache Completeness */}
      {cacheCompleteness && cacheCompleteness.total > 0 && (() => {
        const { streams, photos, detail, total } = cacheCompleteness
        const streamsPct = streams.total_expected > 0 ? (streams.complete / streams.total_expected) * 100 : 100
        const photosPct = photos.total_expected > 0 ? (photos.complete / photos.total_expected) * 100 : 100
        const detailPct = detail?.total_expected > 0 ? (detail.complete / detail.total_expected) * 100 : 100
        const allComplete = streams.missing === 0 && photos.missing === 0 && (detail?.missing ?? 0) === 0
        return (
          <div className={cardClass}>
            <div className="flex items-center justify-between mb-4">
              <div className="text-xs text-gray-500 uppercase tracking-wider">Cache Completeness</div>
              {!allComplete && (
                <button
                  onClick={() => backfillStreams.mutate()}
                  disabled={backfillStreams.isPending || syncStatus?.syncing}
                  className={clsx(
                    'text-xs px-3 py-1.5 rounded-lg transition-colors disabled:opacity-30',
                    isLight ? 'bg-gray-100 hover:bg-gray-200 text-gray-600' : 'bg-surface-700 hover:bg-surface-600 text-gray-300',
                  )}
                >
                  {backfillStreams.isPending || syncStatus?.syncing ? 'Backfilling...' : 'Backfill Missing'}
                </button>
              )}
            </div>
            <div className="space-y-3">
              {/* Streams */}
              <div>
                <div className="flex items-center justify-between mb-1">
                  <span className={clsx('text-sm', isLight ? 'text-gray-600' : 'text-gray-400')}>Streams</span>
                  <span className="text-sm font-mono" style={{ color: streams.missing === 0 ? '#22c55e' : '#eab308' }}>
                    {streams.complete.toLocaleString()} <span className="text-gray-500">/</span> {streams.total_expected.toLocaleString()}
                  </span>
                </div>
                <div className={clsx('h-2 rounded-full overflow-hidden', isLight ? 'bg-gray-100' : 'bg-surface-700')}>
                  <div
                    className="h-full rounded-full transition-all"
                    style={{ width: `${Math.min(streamsPct, 100)}%`, backgroundColor: streams.missing === 0 ? '#22c55e' : '#eab308' }}
                  />
                </div>
              </div>
              {/* Photos */}
              {photos.total_expected > 0 && (
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <span className={clsx('text-sm', isLight ? 'text-gray-600' : 'text-gray-400')}>Photos</span>
                    <span className="text-sm font-mono" style={{ color: photos.missing === 0 ? '#22c55e' : '#eab308' }}>
                      {photos.complete.toLocaleString()} <span className="text-gray-500">/</span> {photos.total_expected.toLocaleString()}
                    </span>
                  </div>
                  <div className={clsx('h-2 rounded-full overflow-hidden', isLight ? 'bg-gray-100' : 'bg-surface-700')}>
                    <div
                      className="h-full rounded-full transition-all"
                      style={{ width: `${Math.min(photosPct, 100)}%`, backgroundColor: photos.missing === 0 ? '#22c55e' : '#eab308' }}
                    />
                  </div>
                </div>
              )}
              {/* Detail */}
              {detail && detail.total_expected > 0 && (
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <span className={clsx('text-sm', isLight ? 'text-gray-600' : 'text-gray-400')}>Detail</span>
                    <span className="text-sm font-mono" style={{ color: detail.missing === 0 ? '#22c55e' : '#eab308' }}>
                      {detail.complete.toLocaleString()} <span className="text-gray-500">/</span> {detail.total_expected.toLocaleString()}
                    </span>
                  </div>
                  <div className={clsx('h-2 rounded-full overflow-hidden', isLight ? 'bg-gray-100' : 'bg-surface-700')}>
                    <div
                      className="h-full rounded-full transition-all"
                      style={{ width: `${Math.min(detailPct, 100)}%`, backgroundColor: detail.missing === 0 ? '#22c55e' : '#eab308' }}
                    />
                  </div>
                </div>
              )}
            </div>
            {/* Summary line */}
            <div className="flex items-center justify-between mt-3">
              <div className="text-[11px] text-gray-500">
                {allComplete
                  ? 'All activity data is complete'
                  : `${streams.missing + photos.missing + (detail?.missing ?? 0)} item${streams.missing + photos.missing + (detail?.missing ?? 0) !== 1 ? 's' : ''} missing`}
              </div>
              {!allComplete && (
                <button
                  onClick={() => setShowCacheDetails(d => !d)}
                  className={clsx('text-[11px] transition-colors', isLight ? 'text-gray-400 hover:text-gray-600' : 'text-gray-500 hover:text-gray-300')}
                >
                  {showCacheDetails ? 'Hide details' : 'Show details'}
                </button>
              )}
            </div>
            {/* Expandable details */}
            {showCacheDetails && !allComplete && (
              <div className={clsx('mt-3 pt-3 border-t text-xs space-y-1', isLight ? 'border-gray-100' : 'border-surface-600')}>
                {streams.missing > 0 && (
                  <div className={clsx(isLight ? 'text-gray-500' : 'text-gray-400')}>
                    {streams.missing} activit{streams.missing !== 1 ? 'ies' : 'y'} missing streams
                  </div>
                )}
                {photos.missing > 0 && (
                  <div className={clsx(isLight ? 'text-gray-500' : 'text-gray-400')}>
                    {photos.missing} activit{photos.missing !== 1 ? 'ies' : 'y'} missing photos (of {photos.total_expected} with photos)
                  </div>
                )}
                {detail && detail.missing > 0 && (
                  <div className={clsx(isLight ? 'text-gray-500' : 'text-gray-400')}>
                    {detail.missing} activit{detail.missing !== 1 ? 'ies' : 'y'} missing detail (description, laps, gear, etc.)
                  </div>
                )}
                <div className={clsx(isLight ? 'text-gray-400' : 'text-gray-500')}>
                  {total} total activities in cache
                </div>
              </div>
            )}
          </div>
        )
      })()}

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
