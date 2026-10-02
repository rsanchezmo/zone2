import { useMemo } from 'react'
import clsx from 'clsx'
import {
  useAthleteProfile, useAthleteZones, useZonesSettings, useSyncStatus, useSportTypes, useGoals,
  useGoalProgress, useRateLimits, useCacheCompleteness, useCalendarFeedUrl, useGearList,
} from '../api/hooks'
import { todayLocalStr } from '../utils/dates'
import BackdropSettingsPanel from '../components/shared/BackdropSettingsPanel'
import { useTheme } from '../hooks/useTheme'
import AthleteCard from '../components/profile/AthleteCard'
import PhotoCollage from '../components/profile/PhotoCollage'
import AthleteDetails from '../components/profile/AthleteDetails'
import HeartRateZones from '../components/profile/HeartRateZones'
import GearSection from '../components/profile/GearSection'
import GoalsSection from '../components/profile/GoalsSection'
import CacheCompleteness from '../components/profile/CacheCompleteness'
import RateLimits from '../components/profile/RateLimits'
import CalendarSubscription from '../components/profile/CalendarSubscription'

export default function ProfilePage() {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const { data: profile, isLoading: profileLoading } = useAthleteProfile()
  const { data: gearList } = useGearList()
  const { data: zones } = useAthleteZones()
  const { data: zonesSettings } = useZonesSettings()
  const { data: syncStatus } = useSyncStatus()
  const { data: sportTypes } = useSportTypes()
  const { data: goals } = useGoals()
  const todayStr = useMemo(() => todayLocalStr(), [])
  const { data: goalProgressData } = useGoalProgress(todayStr)
  const { data: rateLimits } = useRateLimits(syncStatus?.syncing)
  const { data: cacheCompleteness } = useCacheCompleteness(syncStatus?.syncing)
  const { data: feedUrl } = useCalendarFeedUrl()

  const cardClass = clsx(
    'rounded-xl border p-4',
    isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600',
  )

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

  return (
    <div className="max-w-4xl mx-auto space-y-10 pb-12">
      <header className="flex items-baseline gap-2">
        <span className="eyebrow">Profile</span>
        <span className={clsx('text-[11px]', isLight ? 'text-gray-300' : 'text-gray-700')}>·</span>
        <span className="text-[11px] text-gray-500 normal-case tracking-normal">athlete · goals · cache</span>
      </header>
      <AthleteCard profile={profile} />
      <PhotoCollage />
      <AthleteDetails profile={profile} totalActivities={syncStatus?.total_activities} />
      <HeartRateZones zones={zones} zonesSettings={zonesSettings} />
      <GearSection gear={gearList?.gear ?? []} />
      <GoalsSection goals={goals} progress={goalProgressData} sportTypes={sportTypes} />
      <CacheCompleteness completeness={cacheCompleteness} syncing={syncStatus?.syncing} />
      <RateLimits limits={rateLimits} />
      <BackdropSettingsPanel />
      <CalendarSubscription feedUrl={feedUrl} />
    </div>
  )
}
