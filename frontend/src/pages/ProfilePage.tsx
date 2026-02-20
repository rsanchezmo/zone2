import { useAthleteProfile, useAthleteZones, useSyncStatus } from '../api/hooks'

const HR_ZONE_COLORS = ['#6b7280', '#3b82f6', '#22c55e', '#eab308', '#ef4444']
const HR_ZONE_NAMES = ['Recovery', 'Aerobic', 'Tempo', 'Threshold', 'VO2max']

export default function ProfilePage() {
  const { data: profile, isLoading: profileLoading } = useAthleteProfile()
  const { data: zones } = useAthleteZones()
  const { data: syncStatus } = useSyncStatus()

  if (profileLoading) return <div className="text-gray-500 p-6">Loading profile...</div>
  if (!profile) return <div className="text-gray-500 p-6">Unable to load profile</div>

  const fullName = `${profile.firstname ?? ''} ${profile.lastname ?? ''}`.trim()
  const location = [profile.city, profile.state, profile.country].filter(Boolean).join(', ')
  const createdAt = profile.created_at ? new Date(profile.created_at).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' }) : null
  const updatedAt = profile.updated_at ? new Date(profile.updated_at).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' }) : null

  const hrZones = zones?.heart_rate?.zones as { min: number; max: number }[] | undefined

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
              const maxLabel = zone.max === -1 ? 'max' : `${zone.max}`
              const barMax = zone.max === -1 ? 220 : zone.max
              const barMin = zone.min
              // Bar width proportional to the zone range
              const rangeWidth = ((barMax - barMin) / 220) * 100
              const offsetLeft = (barMin / 220) * 100
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
          {zones?.heart_rate?.custom_zones && (
            <div className="text-[11px] text-gray-500 mt-3">Custom zones configured</div>
          )}
        </div>
      )}

    </div>
  )
}
