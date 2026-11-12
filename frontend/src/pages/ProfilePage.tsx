import { useMemo } from 'react'
import { useAthleteProfile, useAthleteZones, useZonesSettings, useRateLimits } from '../api/athlete'
import { useSyncStatus, useCacheCompleteness } from '../api/sync'
import { useSportTypes } from '../api/activities'
import { useGoals, useGoalProgress } from '../api/goals'
import { useCalendarFeedUrl } from '../api/calendar'
import { useGearList } from '../api/gear'
import { todayLocalStr } from '../utils/dates'
import BackdropSettingsPanel from '../components/shared/BackdropSettingsPanel'
import AthleteCard from '../components/profile/AthleteCard'
import PhotoCollage from '../components/profile/PhotoCollage'
import AthleteDetails from '../components/profile/AthleteDetails'
import HeartRateZones from '../components/profile/HeartRateZones'
import GearSection from '../components/profile/GearSection'
import GoalsSection from '../components/profile/GoalsSection'
import CacheCompleteness from '../components/profile/CacheCompleteness'
import RateLimits from '../components/profile/RateLimits'
import CalendarSubscription from '../components/profile/CalendarSubscription'
import WatchWorkouts from '../components/profile/WatchWorkouts'
import GarminConnection from '../components/profile/GarminConnection'
import AgentUsage from '../components/profile/AgentUsage'
import PageHeader from '../components/shared/PageHeader'

export default function ProfilePage() {
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


  if (profileLoading) {
    return (
      <div className="max-w-4xl mx-auto space-y-10 pb-12">
        <div className="panel p-6 flex items-center gap-6 animate-pulse">
          <div className="w-20 h-20 rounded-full bg-track" />
          <div className="flex-1 space-y-3">
            <div className="h-6 w-40 rounded bg-track" />
            <div className="h-4 w-28 rounded bg-surface-700" />
          </div>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="panel p-4 animate-pulse">
              <div className="h-3 w-16 rounded mb-3 bg-track" />
              <div className="h-6 w-20 rounded bg-track" />
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (!profile) {
    return (
      <div className="max-w-4xl mx-auto">
        <div className="panel p-8 text-center">
          <p className="text-sm text-gray-500">Unable to load profile</p>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto space-y-10 pb-12">
      <PageHeader title="Profile" description="athlete · goals · cache" />
      <AthleteCard profile={profile} />
      <PhotoCollage />
      <AthleteDetails profile={profile} totalActivities={syncStatus?.total_activities} />
      <HeartRateZones zones={zones} zonesSettings={zonesSettings} />
      <GearSection gear={gearList?.gear ?? []} />
      <GoalsSection goals={goals} progress={goalProgressData} sportTypes={sportTypes} />
      <CacheCompleteness completeness={cacheCompleteness} syncing={syncStatus?.syncing} />
      <RateLimits limits={rateLimits} />
      <AgentUsage />
      <BackdropSettingsPanel />
      <GarminConnection />
      <WatchWorkouts />
      <CalendarSubscription feedUrl={feedUrl} />
    </div>
  )
}
