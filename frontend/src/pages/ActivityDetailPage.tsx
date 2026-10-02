import { useMemo } from 'react'
import { useParams } from 'react-router-dom'
import {
  useActivity, useAthleteZones, useSimilarActivities, useActivityScore, useActivityRoute,
} from '../api/hooks'
import ChartPanel from '../components/shared/ChartPanel'
import HrZoneDistributionChart from '../components/shared/HrZoneDistributionChart'
import { buildHrHistogram } from '../components/shared/hrHistogram'
import { getSportCategory } from '../utils/formatSpeed'
import { buildSplits, buildStreamData } from '../components/activity/activityData'
import ActivityHeader from '../components/activity/ActivityHeader'
import RouteMap from '../components/activity/RouteMap'
import { ActivityMetrics, BestEfforts } from '../components/activity/ActivityMetrics'
import ExecutionScore from '../components/activity/ExecutionScore'
import { LapsTable, SplitsTable } from '../components/activity/ActivityTables'
import StreamCharts from '../components/activity/StreamCharts'
import RoutePerformance from '../components/activity/RoutePerformance'
import SimilarActivities from '../components/activity/SimilarActivities'
import SegmentEfforts from '../components/activity/SegmentEfforts'

export default function ActivityDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { data: activity, isLoading } = useActivity(Number(id))
  const { data: athleteZones } = useAthleteZones()
  const { data: similarActivities } = useSimilarActivities(Number(id))
  const { data: activityScore } = useActivityScore(Number(id))
  const { data: matched } = useActivityRoute(Number(id))

  const { positions, velocities, streamSeries, gapSpeeds, overallGap } = useMemo(() => buildStreamData(activity), [activity])
  const splits = useMemo(() => buildSplits(activity, gapSpeeds), [activity, gapSpeeds])

  const hrZoneBounds = athleteZones?.heart_rate?.zones ?? undefined
  const hrHistogram = useMemo(() => {
    if (streamSeries.heartrate.length === 0) return null
    return buildHrHistogram(streamSeries.heartrate.map(p => p.value))
  }, [streamSeries.heartrate])

  if (isLoading) return <div className="text-gray-500">Loading...</div>
  if (!activity) return <div className="text-gray-500">Activity not found</div>

  const hasGap = getSportCategory(activity.sport_type) === 'running' && streamSeries.gap.length > 0

  return (
    <div className="max-w-6xl mx-auto space-y-10 pb-12">
      <ActivityHeader activity={activity} id={id} />
      <RouteMap activity={activity} positions={positions} velocities={velocities} splits={splits} matched={matched} />
      <ActivityMetrics activity={activity} overallGap={overallGap} />
      <BestEfforts activity={activity} />
      {activityScore?.score && <ExecutionScore result={activityScore} sportType={activity.sport_type} />}
      {hrHistogram && hrZoneBounds && hrZoneBounds.length >= 5 && (
        <ChartPanel title="HR zone distribution" glow={false}>
          <HrZoneDistributionChart histogram={hrHistogram} zones={hrZoneBounds} />
        </ChartPanel>
      )}
      <LapsTable activity={activity} />
      <SplitsTable activity={activity} splits={splits} hasGap={hasGap} />
      <StreamCharts activity={activity} activityScore={activityScore} streamSeries={streamSeries} />
      <RoutePerformance activity={activity} />
      <SimilarActivities similar={similarActivities} sportType={activity.sport_type} />
      <SegmentEfforts activity={activity} />
    </div>
  )
}
