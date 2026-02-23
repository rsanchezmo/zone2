import { useState } from 'react'
import { useAthleteProfile, useAthleteZones, useSyncStatus, useSportTypes, useGoals, useCreateGoal, useUpdateGoal, useDeleteGoal } from '../api/hooks'
import { getSportColor } from '../constants/sportColors'

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
  const { data: profile, isLoading: profileLoading } = useAthleteProfile()
  const { data: zones } = useAthleteZones()
  const { data: syncStatus } = useSyncStatus()
  const { data: sportTypes } = useSportTypes()
  const { data: goals } = useGoals()
  const createGoal = useCreateGoal()
  const updateGoal = useUpdateGoal()
  const deleteGoal = useDeleteGoal()

  const [showGoalForm, setShowGoalForm] = useState(false)
  const [editingGoalId, setEditingGoalId] = useState<number | null>(null)
  const currentYear = new Date().getFullYear()
  const [goalForm, setGoalForm] = useState({ year: String(currentYear), sport_type: 'Run', metric: 'distance_km', period: 'weekly', target_value: '' })

  if (profileLoading) return <div className="text-gray-500 p-6">Loading profile...</div>
  if (!profile) return <div className="text-gray-500 p-6">Unable to load profile</div>

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
      <div className="bg-surface-800 border border-surface-600 rounded-xl p-6 flex items-center gap-6">
        {profile.profile_medium && profile.profile_medium !== 'avatar/athlete/large.png' ? (
          <img
            src={profile.profile_medium}
            alt={fullName}
            className="w-20 h-20 rounded-full border-2 border-surface-600 object-cover"
          />
        ) : (
          <div className="w-20 h-20 rounded-full border-2 border-surface-600 bg-surface-700 flex items-center justify-center text-3xl text-gray-500">
            {(profile.firstname?.[0] ?? '?').toUpperCase()}
          </div>
        )}
        <div className="flex-1 min-w-0">
          <h1 className="text-2xl font-bold truncate">{fullName || 'Athlete'}</h1>
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
        <div className="bg-surface-800 border border-surface-600 rounded-xl p-4">
          <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Subscription</div>
          <div className="text-lg font-bold" style={{ color: (profile.premium || profile.summit) ? '#ffd700' : '#6b7280' }}>
            {(profile.premium || profile.summit) ? 'Subscriber' : 'Free'}
          </div>
        </div>
        {profile.sex && (
          <div className="bg-surface-800 border border-surface-600 rounded-xl p-4">
            <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Gender</div>
            <div className="text-lg font-bold text-neon-red">{profile.sex === 'M' ? 'Male' : profile.sex === 'F' ? 'Female' : profile.sex}</div>
          </div>
        )}
        {profile.weight != null && profile.weight > 0 && (
          <div className="bg-surface-800 border border-surface-600 rounded-xl p-4">
            <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Weight</div>
            <div className="text-lg font-bold text-neon-red">{profile.weight} <span className="text-sm text-gray-400">kg</span></div>
          </div>
        )}
        {syncStatus?.total_activities != null && (
          <div className="bg-surface-800 border border-surface-600 rounded-xl p-4">
            <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Activities</div>
            <div className="text-lg font-bold text-neon-red">{syncStatus.total_activities}</div>
          </div>
        )}
        {createdAt && (
          <div className="bg-surface-800 border border-surface-600 rounded-xl p-4">
            <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Member Since</div>
            <div className="text-sm font-bold text-neon-red">{createdAt}</div>
          </div>
        )}
        {profile.follower_count != null && (
          <div className="bg-surface-800 border border-surface-600 rounded-xl p-4">
            <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Followers</div>
            <div className="text-lg font-bold text-neon-red">{profile.follower_count}</div>
          </div>
        )}
        {profile.friend_count != null && (
          <div className="bg-surface-800 border border-surface-600 rounded-xl p-4">
            <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Following</div>
            <div className="text-lg font-bold text-neon-red">{profile.friend_count}</div>
          </div>
        )}
        {profile.ftp != null && profile.ftp > 0 && (
          <div className="bg-surface-800 border border-surface-600 rounded-xl p-4">
            <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">FTP</div>
            <div className="text-lg font-bold text-neon-red">{profile.ftp} <span className="text-sm text-gray-400">W</span></div>
          </div>
        )}
        {updatedAt && (
          <div className="bg-surface-800 border border-surface-600 rounded-xl p-4">
            <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Last Updated</div>
            <div className="text-sm font-bold text-neon-red">{updatedAt}</div>
          </div>
        )}
      </div>

      {/* Heart Rate Zones */}
      {hrZones && hrZones.length > 0 && (
        <div className="bg-surface-800 border border-surface-600 rounded-xl p-4">
          <div className="text-xs text-gray-500 uppercase tracking-wider mb-4">Heart Rate Zones</div>
          <div className="space-y-2.5">
            {hrZones.map((zone, i) => {
              const color = HR_ZONE_COLORS[i] ?? '#6b7280'
              const name = HR_ZONE_NAMES[i] ?? `Zone ${i + 1}`
              const scale = (maxHr ?? 220) * 1.05 // 5% padding above max HR
              const maxLabel = `${zone.max}`
              const barMax = zone.max
              const barMin = zone.min
              // Bar width proportional to the zone range
              const rangeWidth = ((barMax - barMin) / scale) * 100
              const offsetLeft = (barMin / scale) * 100
              return (
                <div key={i} className="flex items-center gap-3">
                  <span className="text-xs font-mono w-6 text-center font-bold" style={{ color }}>Z{i + 1}</span>
                  <span className="text-sm text-gray-400 w-20 shrink-0">{name}</span>
                  <div className="flex-1 h-7 bg-surface-700 rounded overflow-hidden relative">
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
      <div className="bg-surface-800 border border-surface-600 rounded-xl p-4">
        <div className="flex items-center justify-between mb-4">
          <div className="text-xs text-gray-500 uppercase tracking-wider">Goals</div>
          {!showGoalForm && (
            <button
              onClick={() => { setEditingGoalId(null); setGoalForm({ year: String(currentYear), sport_type: 'Run', metric: 'distance_km', period: 'weekly', target_value: '' }); setShowGoalForm(true) }}
              className="text-xs bg-surface-700 hover:bg-surface-600 px-3 py-1.5 rounded-lg transition-colors"
            >
              + Add Goal
            </button>
          )}
        </div>

        {/* Goal form */}
        {showGoalForm && (
          <div className="mb-4 p-3 bg-surface-700 rounded-lg space-y-3">
            <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
              <input
                type="number"
                min="2020"
                max="2040"
                placeholder="Year"
                value={goalForm.year}
                onChange={e => setGoalForm(f => ({ ...f, year: e.target.value }))}
                className="bg-surface-800 border border-surface-600 rounded px-2 py-1.5 text-sm"
              />
              <select
                value={goalForm.sport_type}
                onChange={e => setGoalForm(f => ({ ...f, sport_type: e.target.value }))}
                className="bg-surface-800 border border-surface-600 rounded px-2 py-1.5 text-sm"
              >
                <option value="__all__">All Sports</option>
                {(sportTypes ?? []).map((s: string) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
              <select
                value={goalForm.metric}
                onChange={e => setGoalForm(f => ({ ...f, metric: e.target.value }))}
                className="bg-surface-800 border border-surface-600 rounded px-2 py-1.5 text-sm"
              >
                {METRIC_OPTIONS.map(m => (
                  <option key={m.value} value={m.value}>{m.label}</option>
                ))}
              </select>
              <select
                value={goalForm.period}
                onChange={e => setGoalForm(f => ({ ...f, period: e.target.value }))}
                className="bg-surface-800 border border-surface-600 rounded px-2 py-1.5 text-sm"
              >
                {PERIOD_OPTIONS.map(p => (
                  <option key={p.value} value={p.value}>{p.label}</option>
                ))}
              </select>
              <input
                type="number"
                step="any"
                min="0"
                placeholder="Target value"
                value={goalForm.target_value}
                onChange={e => setGoalForm(f => ({ ...f, target_value: e.target.value }))}
                className="bg-surface-800 border border-surface-600 rounded px-2 py-1.5 text-sm"
              />
            </div>
            <div className="flex gap-2">
              <button
                onClick={handleGoalSubmit}
                disabled={!goalForm.target_value || parseFloat(goalForm.target_value) <= 0}
                className="text-xs bg-neon-red/20 text-neon-red hover:bg-neon-red/30 px-3 py-1.5 rounded-lg transition-colors disabled:opacity-30"
              >
                {editingGoalId != null ? 'Update' : 'Create'}
              </button>
              <button
                onClick={cancelForm}
                className="text-xs bg-surface-600 hover:bg-surface-500 px-3 py-1.5 rounded-lg transition-colors"
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
                <div key={goal.id as number} className="flex items-center gap-3 py-2 px-2 rounded-lg hover:bg-surface-700/50 transition-colors group">
                  <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: color }} />
                  <span className="text-xs font-mono text-gray-500 min-w-[36px]">{goal.year as number}</span>
                  <span className="text-sm text-gray-300 min-w-[80px]">{sport === '__all__' ? 'All Sports' : sport}</span>
                  <span className="text-xs text-gray-500">{metricLabel(goal.metric as string)}</span>
                  <span className="text-xs font-mono text-gray-400 ml-auto">{goal.target_value as number} / {periodLabel(goal.period as string).toLowerCase()}</span>
                  <button
                    onClick={() => startEdit(goal)}
                    className="text-xs text-gray-500 hover:text-gray-300 opacity-0 group-hover:opacity-100 transition-opacity"
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
          <div className="text-sm text-gray-600">No goals set. Add a goal to track your progress.</div>
        ) : null}
      </div>

    </div>
  )
}
