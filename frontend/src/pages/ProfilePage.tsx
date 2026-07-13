import { useState } from 'react'
import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useAthleteProfile, useAthleteZones, useZonesSettings, useUpdateZonesSettings, useSyncStatus, useSportTypes, useGoals, useGoalProgress, useCreateGoal, useUpdateGoal, useDeleteGoal, useRateLimits, useCacheCompleteness, useBackfillStreams, useCalendarFeedUrl, useRotateCalendarFeedToken, useRecentPhotos, type AthleteGear, type Goal } from '../api/hooks'
import PhotoLightbox from '../components/shared/PhotoLightbox'
import { photoThumbUrl } from '../components/shared/photoUrls'
import { getSportColor } from '../constants/sportColors'
import { getSportCategory } from '../utils/formatSpeed'
import { todayLocalStr } from '../utils/dates'
import ChartPanel from '../components/shared/ChartPanel'
import { useTheme } from '../hooks/useTheme'
import { useToast } from '../hooks/useToast'
import { useNow } from '../hooks/useNow'
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

// Strava-style collage: three large tiles, then a right cluster of one wide +
// two small — the six most recent activity photos.
const COLLAGE_SLOTS = [
  'col-span-2 row-span-2',
  'col-span-2 row-span-2',
  'col-span-2 row-span-2',
  'col-span-2 row-span-1',
  'col-span-1 row-span-1',
  'col-span-1 row-span-1',
]

function PhotoCollage() {
  const { data: photos } = useRecentPhotos(6)
  const [lightboxIdx, setLightboxIdx] = useState<number | null>(null)
  if (!photos || photos.length === 0) return null

  return (
    <section>
      <div className="section-head mb-4"><span className="eyebrow">Recent photos</span></div>
      <div className="grid grid-cols-8 grid-rows-2 gap-1.5 h-48 sm:h-60 lg:h-72">
        {photos.slice(0, 6).map((photo, idx) => (
          <button
            key={photo.unique_id}
            onClick={() => setLightboxIdx(idx)}
            className={clsx(
              'relative overflow-hidden rounded-lg group ring-1 ring-inset ring-white/10 hover:ring-white/30 transition-all',
              COLLAGE_SLOTS[idx],
            )}
          >
            <img
              src={photoThumbUrl(photo)}
              alt={photo.activity_name || `Photo ${idx + 1}`}
              loading="lazy"
              className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105"
            />
            <span className="absolute inset-x-0 bottom-0 px-2 py-1 text-[10px] text-white/90 bg-gradient-to-t from-black/70 to-transparent opacity-0 group-hover:opacity-100 transition-opacity truncate">
              {photo.activity_name}
            </span>
          </button>
        ))}
      </div>
      <PhotoLightbox
        photos={photos}
        index={lightboxIdx}
        onIndexChange={setLightboxIdx}
        caption={(_photo, idx) => (
          <Link to={`/activities/${photos[idx].activity_id}`} className="hover:underline">
            {photos[idx].activity_name || 'View activity'}
          </Link>
        )}
      />
    </section>
  )
}

export default function ProfilePage() {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const { toast } = useToast()
  const { data: profile, isLoading: profileLoading } = useAthleteProfile()
  const { data: zones } = useAthleteZones()
  const { data: zonesSettings } = useZonesSettings()
  const updateZonesSettings = useUpdateZonesSettings()
  const { data: syncStatus } = useSyncStatus()
  const { data: sportTypes } = useSportTypes()
  const { data: goals } = useGoals()
  const todayStr = useMemo(() => todayLocalStr(), [])
  const { data: goalProgressData } = useGoalProgress(todayStr)
  const { data: rateLimits } = useRateLimits(syncStatus?.syncing)
  const { data: cacheCompleteness } = useCacheCompleteness(syncStatus?.syncing)
  const backfillStreams = useBackfillStreams()
  const createGoal = useCreateGoal()
  const updateGoal = useUpdateGoal()
  const deleteGoal = useDeleteGoal()

  const [showCacheDetails, setShowCacheDetails] = useState(false)
  const [showGoalForm, setShowGoalForm] = useState(false)

  // Subscribable iCal feed for Google/Apple Calendar → phone → Garmin watch.
  const [showSubscribe, setShowSubscribe] = useState(false)
  const { data: feedUrl } = useCalendarFeedUrl()
  const rotateFeedToken = useRotateCalendarFeedToken()

  function handleCopyFeedUrl() {
    if (!feedUrl?.url) return
    navigator.clipboard.writeText(feedUrl.url).then(
      () => toast('Feed URL copied', 'success'),
      () => toast('Could not copy — select the text manually', 'error'),
    )
  }

  function handleRotateFeedToken() {
    if (!window.confirm('Rotate the feed token? Any existing calendar subscription will stop working — you will need to re-add the new URL.')) return
    rotateFeedToken.mutate(undefined, {
      onSuccess: () => toast('Token rotated — re-subscribe with the new URL', 'success'),
    })
  }
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
      <div className="max-w-4xl mx-auto space-y-10 pb-12">
        <div className={clsx('panel p-6 flex items-center gap-6 animate-pulse', isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600')}>
          <div className={clsx('w-20 h-20 rounded-full', isLight ? 'bg-gray-200' : 'bg-surface-700')} />
          <div className="flex-1 space-y-3">
            <div className={clsx('h-6 w-40 rounded', isLight ? 'bg-gray-200' : 'bg-surface-700')} />
            <div className={clsx('h-4 w-28 rounded', isLight ? 'bg-gray-100' : 'bg-surface-700')} />
          </div>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className={clsx('panel p-4 animate-pulse', isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600')}>
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

  const hrZones = zones?.heart_rate?.zones ?? undefined
  const maxHr = zones?.heart_rate?.max_hr ?? undefined

  const sortByDist = (a: AthleteGear, b: AthleteGear) => (b.converted_distance ?? 0) - (a.converted_distance ?? 0)
  const shoes = (profile.shoes ?? []).slice().sort(sortByDist)
  const bikes = (profile.bikes ?? []).slice().sort(sortByDist)
  const hasGear = shoes.length > 0 || bikes.length > 0

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
      })
    } else {
      createGoal.mutate(payload, {
        onSuccess: () => { setShowGoalForm(false); setGoalForm({ year: String(currentYear), sport_type: 'Run', metric: 'distance_km', period: 'weekly', target_value: '' }); toast('Goal created', 'success') },
      })
    }
  }

  const startEdit = (goal: Goal) => {
    setEditingGoalId(goal.id)
    // Convert km back to meters for swimming distance goals
    let displayValue = goal.target_value
    if (goal.metric === 'distance_km' && getSportCategory(goal.sport_type) === 'swimming') {
      displayValue = displayValue * 1000
    }
    setGoalForm({
      year: String(goal.year),
      sport_type: goal.sport_type,
      metric: goal.metric,
      period: goal.period,
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
    <div className="max-w-4xl mx-auto space-y-10 pb-12">
      {/* ── Breadcrumb header ─────────────────────────── */}
      <header className="flex items-baseline gap-2">
        <span className="eyebrow">Profile</span>
        <span className={clsx('text-[11px]', isLight ? 'text-gray-300' : 'text-gray-700')}>·</span>
        <span className="text-[11px] text-gray-500 normal-case tracking-normal">athlete · goals · cache</span>
      </header>

      {/* ── Athlete card ──────────────────────────────── */}
      <section
        className={clsx(
          'panel hero-brackets p-6 md:p-8 flex items-center gap-6',
          isLight ? 'bg-white' : 'bg-surface-800',
        )}
        style={{ ['--card-accent' as string]: (profile.premium || profile.summit) ? '#eab308' : '#6b7280' }}
      >
        {profile.profile_medium && profile.profile_medium !== 'avatar/athlete/large.png' ? (
          <img
            src={profile.profile_medium}
            alt={fullName}
            className={clsx('w-24 h-24 rounded-full border object-cover shrink-0', isLight ? 'border-gray-200' : 'border-surface-600')}
          />
        ) : (
          <div className={clsx(
            'w-24 h-24 rounded-full border flex items-center justify-center text-3xl font-semibold shrink-0',
            isLight ? 'border-gray-200 bg-gray-100 text-gray-400' : 'border-surface-600 bg-surface-700 text-gray-500',
          )}>
            {(profile.firstname?.[0] ?? '?').toUpperCase()}
          </div>
        )}
        <div className="flex-1 min-w-0">
          <div className="eyebrow mb-1.5">Athlete</div>
          <h1
            className={clsx('text-2xl md:text-3xl font-semibold tracking-tight truncate', isLight ? 'text-gray-900' : 'text-gray-100')}
            style={{ letterSpacing: '-0.02em' }}
          >
            {fullName || 'Athlete'}
          </h1>
          <div className="flex items-center gap-3 mt-1.5 flex-wrap text-[11px] font-mono tabular-nums">
            {profile.username && (
              <span className={isLight ? 'text-gray-500' : 'text-gray-500'}>@{profile.username}</span>
            )}
            {location && (
              <>
                {profile.username && <span className={isLight ? 'text-gray-300' : 'text-gray-700'}>·</span>}
                <span className={isLight ? 'text-gray-500' : 'text-gray-500'}>{location}</span>
              </>
            )}
            {(profile.premium || profile.summit) && (
              <>
                <span className={isLight ? 'text-gray-300' : 'text-gray-700'}>·</span>
                <span className="uppercase tracking-[0.15em] text-amber-400 text-[10px] font-semibold">Subscriber</span>
              </>
            )}
          </div>
        </div>
      </section>

      {/* ── Recent photos ─────────────────────────────── */}
      <PhotoCollage />

      {/* ── Info strip ───────────────────────────────── */}
      <section>
        <div className="section-head mb-4"><span className="eyebrow">Details</span></div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {profile.sex && <InfoTile label="Gender" value={profile.sex === 'M' ? 'Male' : profile.sex === 'F' ? 'Female' : profile.sex} />}
          {profile.weight != null && profile.weight > 0 && <InfoTile label="Weight" value={profile.weight} unit="kg" />}
          {syncStatus?.total_activities != null && <InfoTile label="Activities" value={syncStatus.total_activities.toLocaleString()} />}
          {profile.ftp != null && profile.ftp > 0 && <InfoTile label="FTP" value={profile.ftp} unit="W" />}
          {profile.follower_count != null && <InfoTile label="Followers" value={profile.follower_count.toLocaleString()} />}
          {profile.friend_count != null && <InfoTile label="Following" value={profile.friend_count.toLocaleString()} />}
          {createdAt && <InfoTile label="Member since" value={createdAt} compact />}
          {updatedAt && <InfoTile label="Last updated" value={updatedAt} compact />}
        </div>
      </section>

      {/* ── Heart Rate Zones ─────────────────────────── */}
      {hrZones && hrZones.length > 0 && (
        <ChartPanel
          title="Heart rate zones"
          glow={false}
          toolbar={
            <ZoneSourceSelector
              current={zonesSettings?.source ?? 'estimated'}
              onChange={source => updateZonesSettings.mutate({ source })}
              isLight={isLight}
              pending={updateZonesSettings.isPending}
            />
          }
          footer={
            <div className="space-y-0.5">
              <div className={clsx('text-[11px]', isLight ? 'text-gray-500' : 'text-gray-500')}>
                {zones?.heart_rate?.source === 'strava' && `Custom zones from Strava · max HR ${maxHr ?? '?'} bpm`}
                {zones?.heart_rate?.source === 'manual' && `Manual zones · max HR ${maxHr ?? '?'} bpm`}
                {zones?.heart_rate?.source === 'estimated' && `Estimated from activity data · max HR ${maxHr ?? '?'} bpm`}
              </div>
              {zones?.heart_rate?.fallback_reason && (
                <div className="text-[11px] text-amber-400">
                  Requested <span className="font-semibold">{zones.heart_rate.requested_source}</span>, falling back to {zones.heart_rate.source}: {zones.heart_rate.fallback_reason}
                </div>
              )}
            </div>
          }
        >
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

          {zonesSettings?.source === 'manual' && (
            <ManualZonesEditor
              initial={zonesSettings?.manual_zones ?? hrZones}
              isLight={isLight}
              onSave={zones => updateZonesSettings.mutate({ source: 'manual', manual_zones: zones })}
              saving={updateZonesSettings.isPending}
            />
          )}
        </ChartPanel>
      )}

      {/* ── Gear ────────────────────────────────────── */}
      {hasGear && (
        <ChartPanel title="Gear" glow={false}>
          <div className="space-y-6">
            {shoes.length > 0 && (
              <GearGroup title="Shoes" items={shoes} isLight={isLight} accent={getSportColor('Run')} />
            )}
            {bikes.length > 0 && (
              <GearGroup title="Bikes" items={bikes} isLight={isLight} accent={getSportColor('Ride')} />
            )}
          </div>
        </ChartPanel>
      )}

      {/* ── Goals ───────────────────────────────────── */}
      <ChartPanel
        title="Goals"
        glow={false}
        toolbar={
          !showGoalForm ? (
            <button
              onClick={() => { setEditingGoalId(null); setGoalForm({ year: String(currentYear), sport_type: 'Run', metric: 'distance_km', period: 'weekly', target_value: '' }); setShowGoalForm(true) }}
              className="btn"
            >
              + Add goal
            </button>
          ) : undefined
        }
      >

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
            {goals.map(goal => {
              const sport = goal.sport_type
              const color = sport === '__all__' ? '#9ca3af' : getSportColor(sport)
              const metric = goal.metric
              const isSwimmingDist = metric === 'distance_km' && getSportCategory(sport) === 'swimming'
              const targetRaw = goal.target_value
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
                      {periodLabel(goal.period).toLowerCase()}
                    </span>
                    <span className="text-[11px] text-gray-500 font-mono">{goal.year}</span>
                    <div className="ml-auto flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button
                        onClick={() => startEdit(goal)}
                        className={clsx('text-[11px] px-1.5 py-0.5 rounded', isLight ? 'text-gray-400 hover:text-gray-600 hover:bg-gray-100' : 'text-gray-500 hover:text-gray-300 hover:bg-surface-700')}
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => deleteGoal.mutate(goal.id, {
                          onSuccess: () => toast('Goal deleted', 'success'),
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
      </ChartPanel>

      {/* ── Cache Completeness ──────────────────────── */}
      {cacheCompleteness && cacheCompleteness.total > 0 && (() => {
        const { streams, photos, detail, total } = cacheCompleteness
        const streamsPct = streams.total_expected > 0 ? (streams.complete / streams.total_expected) * 100 : 100
        const photosPct = photos.total_expected > 0 ? (photos.complete / photos.total_expected) * 100 : 100
        const detailPct = detail?.total_expected > 0 ? (detail.complete / detail.total_expected) * 100 : 100
        const allComplete = streams.missing === 0 && photos.missing === 0 && (detail?.missing ?? 0) === 0
        const missingCount = streams.missing + photos.missing + (detail?.missing ?? 0)
        return (
          <ChartPanel
            title="Cache completeness"
            glow={false}
            toolbar={
              !allComplete ? (
                <button
                  onClick={() => backfillStreams.mutate()}
                  disabled={backfillStreams.isPending || syncStatus?.syncing}
                  className="btn"
                >
                  {backfillStreams.isPending || syncStatus?.syncing ? 'Backfilling…' : 'Backfill missing'}
                </button>
              ) : (
                <span className="text-[10px] uppercase tracking-[0.15em] font-semibold text-green-400">Complete</span>
              )
            }
            footer={
              <div className="flex items-center justify-between">
                <span className={clsx('text-[11px]', isLight ? 'text-gray-500' : 'text-gray-500')}>
                  {allComplete
                    ? `All ${total.toLocaleString()} activities fully cached`
                    : `${missingCount.toLocaleString()} item${missingCount !== 1 ? 's' : ''} missing · ${total.toLocaleString()} total`}
                </span>
                {!allComplete && (
                  <button
                    onClick={() => setShowCacheDetails(d => !d)}
                    className={clsx('text-[11px] transition-colors', isLight ? 'text-gray-400 hover:text-gray-600' : 'text-gray-500 hover:text-gray-300')}
                  >
                    {showCacheDetails ? 'Hide details' : 'Show details'}
                  </button>
                )}
              </div>
            }
          >
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
            {/* Expandable details */}
            {showCacheDetails && !allComplete && (
              <div className={clsx('mt-4 pt-4 border-t text-xs space-y-1', isLight ? 'border-gray-100' : 'border-surface-600/50')}>
                {streams.missing > 0 && (
                  <div className={clsx(isLight ? 'text-gray-500' : 'text-gray-400')}>
                    <span className="font-mono tabular-nums">{streams.missing}</span> activit{streams.missing !== 1 ? 'ies' : 'y'} missing streams
                  </div>
                )}
                {photos.missing > 0 && (
                  <div className={clsx(isLight ? 'text-gray-500' : 'text-gray-400')}>
                    <span className="font-mono tabular-nums">{photos.missing}</span> activit{photos.missing !== 1 ? 'ies' : 'y'} missing photos (of {photos.total_expected} with photos)
                  </div>
                )}
                {detail && detail.missing > 0 && (
                  <div className={clsx(isLight ? 'text-gray-500' : 'text-gray-400')}>
                    <span className="font-mono tabular-nums">{detail.missing}</span> activit{detail.missing !== 1 ? 'ies' : 'y'} missing detail (description, laps, gear, etc.)
                  </div>
                )}
              </div>
            )}
          </ChartPanel>
        )
      })()}

      {/* ── Strava API Rate Limits ──────────────────── */}
      {rateLimits && (
        <ChartPanel
          title="Strava API rate limits"
          glow={false}
          footer={
            <span className={clsx('text-[11px]', isLight ? 'text-gray-500' : 'text-gray-500')}>
              Daily limit resets at midnight UTC
            </span>
          }
        >
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
                  <div className="flex items-center justify-between mb-1.5">
                    <span className={clsx('eyebrow', isLight ? 'text-gray-500' : 'text-gray-500')}>{label}</span>
                    <span className="text-sm font-mono tabular-nums font-semibold" style={{ color: barColor }}>
                      {data.usage.toLocaleString()} <span className={isLight ? 'text-gray-400' : 'text-gray-500'}>/</span> {data.limit.toLocaleString()}
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
        </ChartPanel>
      )}

      {/* ── Calendar subscription ───────────────────────── */}
      <section>
        <div className="eyebrow mb-3">Calendar subscription</div>
        <div className={clsx('rounded-lg border', isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600')}>
          <button
            onClick={() => setShowSubscribe(v => !v)}
            className={clsx('w-full flex items-center justify-between px-4 py-2.5 text-left', isLight ? 'hover:bg-gray-50' : 'hover:bg-surface-700/50')}
          >
            <span className="flex items-center gap-2">
              <span className="text-sm">Subscribe in Google Calendar</span>
              <FeedStatusPill lastFetchedAt={feedUrl?.last_fetched_at ?? null} />
            </span>
            <span className="text-xs text-gray-500 tabular-nums">{showSubscribe ? '−' : '+'}</span>
          </button>
          {showSubscribe && (
            <div className={clsx('px-4 pb-3 pt-1 space-y-2 border-t', isLight ? 'border-gray-200' : 'border-surface-600')}>
              <div className="flex gap-2 items-center">
                <input
                  readOnly
                  value={feedUrl?.url ?? 'Loading…'}
                  onFocus={e => e.currentTarget.select()}
                  className={clsx('flex-1 font-mono text-[11px] px-2 py-1.5 rounded border min-w-0', isLight ? 'bg-gray-50 border-gray-200 text-gray-700' : 'bg-surface-900 border-surface-600 text-gray-300')}
                />
                <button onClick={handleCopyFeedUrl} className="btn !text-xs" disabled={!feedUrl?.url}>Copy</button>
                <button
                  onClick={handleRotateFeedToken}
                  className="btn !text-xs"
                  disabled={rotateFeedToken.isPending || feedUrl?.env_managed}
                  title={feedUrl?.env_managed ? 'Token is pinned via STRAVA_WEB_CALENDAR_FEED_TOKEN — rotate it in .env and restart' : undefined}
                >
                  {rotateFeedToken.isPending ? 'Rotating…' : 'Rotate'}
                </button>
              </div>
              <p className="text-[11px] text-gray-500 leading-relaxed">
                Paste into Google Calendar → <b>Other calendars</b> → <b>From URL</b>. Events refresh every few hours.
                Your phone (and paired Garmin watch) pick it up automatically — Android/iOS users may need to toggle
                Sync on in Google Calendar settings the first time. Keep the URL private: anyone with it can read your plan.
                {feedUrl?.env_managed && (
                  <> Token is pinned via <code>STRAVA_WEB_CALENDAR_FEED_TOKEN</code> in <code>.env</code>.</>
                )}
              </p>
            </div>
          )}
        </div>
      </section>

    </div>
  )
}

// ────────────────────────────────────────────────────────
// ZoneSourceSelector — pick strava / estimated / manual
// ────────────────────────────────────────────────────────

function ZoneSourceSelector({
  current, onChange, isLight, pending,
}: {
  current: 'strava' | 'estimated' | 'manual'
  onChange: (source: 'strava' | 'estimated' | 'manual') => void
  isLight: boolean
  pending: boolean
}) {
  const options: Array<{ value: 'strava' | 'estimated' | 'manual'; label: string }> = [
    { value: 'estimated', label: 'Estimated' },
    { value: 'strava', label: 'Strava' },
    { value: 'manual', label: 'Manual' },
  ]
  return (
    <div className={clsx('inline-flex rounded-md overflow-hidden border', isLight ? 'border-gray-200' : 'border-surface-600')}>
      {options.map((o, i) => {
        const selected = current === o.value
        return (
          <button
            key={o.value}
            onClick={() => !selected && onChange(o.value)}
            disabled={pending}
            className={clsx(
              'text-[10px] uppercase tracking-[0.1em] px-2 py-1 transition-colors',
              i > 0 && (isLight ? 'border-l border-gray-200' : 'border-l border-surface-600'),
              selected
                ? (isLight ? 'bg-gray-900 text-white' : 'bg-gray-200 text-gray-900')
                : (isLight ? 'bg-white text-gray-600 hover:bg-gray-50' : 'bg-surface-800 text-gray-400 hover:bg-surface-700'),
              pending && 'opacity-60 cursor-wait',
            )}
          >
            {o.label}
          </button>
        )
      })}
    </div>
  )
}

// ────────────────────────────────────────────────────────
// ManualZonesEditor — edit 5 zone upper-bounds
// ────────────────────────────────────────────────────────

function ManualZonesEditor({
  initial, isLight, onSave, saving,
}: {
  initial: Array<{ min: number; max: number }>
  isLight: boolean
  onSave: (zones: Array<{ min: number; max: number }>) => void
  saving: boolean
}) {
  const [maxes, setMaxes] = useState<string[]>(() => {
    const src = initial.slice(0, 5)
    while (src.length < 5) src.push({ min: 0, max: 0 })
    return src.map(z => String(z.max ?? 0))
  })
  const [error, setError] = useState<string | null>(null)

  const parsed = maxes.map(s => parseInt(s, 10))
  const allValid = parsed.every(n => Number.isFinite(n) && n > 0 && n < 250)
  const monotonic = allValid && parsed.every((n, i) => i === 0 || n > parsed[i - 1])
  const canSave = allValid && monotonic

  const handleSave = () => {
    if (!canSave) {
      setError(!allValid ? 'All zones must be positive and below 250' : 'Each zone max must be greater than the previous')
      return
    }
    setError(null)
    const zones: Array<{ min: number; max: number }> = []
    for (let i = 0; i < 5; i++) {
      zones.push({ min: i === 0 ? 0 : parsed[i - 1], max: parsed[i] })
    }
    onSave(zones)
  }

  const accent = '#60a5fa' // blue — primary action
  return (
    <div className={clsx('mt-5 pt-4 border-t', isLight ? 'border-gray-200' : 'border-surface-600')}>
      <div className={clsx('text-[10px] uppercase tracking-[0.15em] mb-3', isLight ? 'text-gray-400' : 'text-gray-500')}>
        Manual thresholds <span className="normal-case tracking-normal">— upper bpm of each zone</span>
      </div>
      <div className="grid grid-cols-3 md:grid-cols-5 gap-2 mb-3">
        {maxes.map((v, i) => {
          const color = HR_ZONE_COLORS[i] ?? '#6b7280'
          return (
            <div key={i}>
              <label className="eyebrow mb-1.5 block" style={{ color }}>Z{i + 1} max</label>
              <input
                type="number"
                inputMode="numeric"
                value={v}
                onChange={e => setMaxes(cur => cur.map((x, ix) => ix === i ? e.target.value : x))}
                className="input w-full font-mono tabular-nums text-center"
                min={0}
                max={250}
              />
            </div>
          )
        })}
      </div>
      {error && <div className="text-[11px] text-red-400 mb-2">{error}</div>}
      <button
        onClick={handleSave}
        disabled={saving || !canSave}
        className="btn"
        style={{
          borderColor: `${accent}50`,
          color: accent,
          backgroundColor: `${accent}15`,
        }}
      >
        {saving ? 'Saving…' : 'Save zones'}
      </button>
    </div>
  )
}

// ────────────────────────────────────────────────────────
// GearGroup — list of gear items (shoes or bikes) from Strava
// ────────────────────────────────────────────────────────

function GearGroup({ title, items, isLight, accent }: { title: string; items: AthleteGear[]; isLight: boolean; accent: string }) {
  return (
    <div>
      <div className={clsx('text-[11px] uppercase tracking-[0.15em] mb-2 flex items-center gap-2', isLight ? 'text-gray-400' : 'text-gray-500')}>
        <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: accent }} aria-hidden="true" />
        {title}
      </div>
      <div className="space-y-1.5">
        {items.map(g => {
          const label = g.nickname && g.nickname.trim() ? g.nickname : g.name
          const secondary = g.nickname && g.nickname.trim() && g.nickname !== g.name ? g.name : null
          const distKm = g.converted_distance ?? 0
          return (
            <Link
              key={g.id}
              to={`/activities?gear_id=${encodeURIComponent(g.id)}`}
              className={clsx(
                'flex items-baseline gap-3 py-1.5 px-2 -mx-2 rounded-lg transition-colors',
                g.retired && 'opacity-50',
                isLight ? 'hover:bg-gray-50' : 'hover:bg-surface-700',
              )}
            >
              <div className="flex-1 min-w-0 flex items-baseline gap-2 flex-wrap">
                <span className={clsx('text-sm font-medium truncate', isLight ? 'text-gray-900' : 'text-gray-100')}>{label}</span>
                {secondary && (
                  <span className={clsx('text-[11px] truncate', isLight ? 'text-gray-500' : 'text-gray-500')}>{secondary}</span>
                )}
                {g.primary && (
                  <span
                    className="text-[9px] uppercase tracking-[0.15em] px-1.5 py-0.5 rounded border"
                    style={{ color: accent, borderColor: `${accent}40`, backgroundColor: `${accent}15` }}
                  >
                    Primary
                  </span>
                )}
                {g.retired && (
                  <span className={clsx('text-[9px] uppercase tracking-[0.15em] px-1.5 py-0.5 rounded border', isLight ? 'border-gray-300 text-gray-400' : 'border-gray-700 text-gray-500')}>Retired</span>
                )}
              </div>
              <span className={clsx('text-sm font-mono tabular-nums shrink-0', isLight ? 'text-gray-700' : 'text-gray-300')}>
                {distKm.toLocaleString(undefined, { maximumFractionDigits: 1 })}
                <span className={clsx('ml-1 text-[11px]', isLight ? 'text-gray-400' : 'text-gray-500')}>km</span>
              </span>
            </Link>
          )
        })}
      </div>
    </div>
  )
}

// ────────────────────────────────────────────────────────
// InfoTile — a clean detail tile for the athlete info strip
// ────────────────────────────────────────────────────────

function InfoTile({ label, value, unit, compact }: { label: string; value: string | number; unit?: string; compact?: boolean }) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  return (
    <div className={clsx(
      'panel p-4',
      isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600',
    )}>
      <div className="eyebrow mb-1.5">{label}</div>
      <div className={clsx(
        'font-mono tabular-nums font-semibold tracking-tight',
        compact ? 'text-sm' : 'text-xl',
        isLight ? 'text-gray-900' : 'text-gray-100',
      )}>
        {value}
        {unit && <span className={clsx('ml-1 font-medium tracking-normal', compact ? 'text-[11px]' : 'text-xs', isLight ? 'text-gray-400' : 'text-gray-500')}>{unit}</span>}
      </div>
    </div>
  )
}

// ────────────────────────────────────────────────────────
// FeedStatusPill — shows whether the ICS feed has been polled recently
// ────────────────────────────────────────────────────────
function FeedStatusPill({ lastFetchedAt }: { lastFetchedAt: string | null }) {
  const now = useNow(60_000)
  if (!lastFetchedAt) {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded border bg-amber-500/10 border-amber-500/30 text-amber-600">
        <span className="w-1.5 h-1.5 rounded-full bg-amber-500" /> Not subscribed yet
      </span>
    )
  }

  const last = new Date(lastFetchedAt)
  const ageMs = now - last.getTime()
  const ageHours = ageMs / (1000 * 60 * 60)
  // Google typically polls subscribed ICS every few hours. 25h gives headroom
  // for the occasional slower refresh before we flag it as stale.
  const isActive = ageHours < 25

  const relative = formatRelative(ageMs)
  const tone = isActive
    ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-600'
    : 'bg-amber-500/10 border-amber-500/30 text-amber-600'
  const dotTone = isActive ? 'bg-emerald-500' : 'bg-amber-500'
  const label = isActive ? `Active · polled ${relative}` : `Stale · ${relative}`

  return (
    <span className={clsx('inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded border', tone)} title={`Last fetch: ${last.toLocaleString()}`}>
      <span className={clsx('w-1.5 h-1.5 rounded-full', dotTone)} /> {label}
    </span>
  )
}

function formatRelative(ms: number): string {
  const sec = Math.max(0, Math.floor(ms / 1000))
  if (sec < 60) return `${sec}s ago`
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min}m ago`
  const hr = Math.floor(min / 60)
  if (hr < 48) return `${hr}h ago`
  const day = Math.floor(hr / 24)
  return `${day}d ago`
}
