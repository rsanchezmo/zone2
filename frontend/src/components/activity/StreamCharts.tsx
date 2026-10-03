import { useMemo } from 'react'
import type { ActivityDetail, ActivityScoreResponse } from '../../api/hooks'
import { getSportColor } from '../../constants/sportColors'
import {
  getSportCategory, formatPace, formatClockDuration, isSpeedSport,
} from '../../utils/formatSpeed'
import StreamChart, { type ChartMarker, type ChartZone } from '../shared/StreamChart'
import { getSegmentColor } from '../shared/segmentUtils'
import { SEG_TYPE_LABELS, STOP_COLOR, paceUnitOf, type StreamSeries } from './activityData'

// Hoisted StreamChart props so its React.memo sees stable references
const ELEVATION_Y_DOMAIN: [string, string] = ['dataMin - 10', 'dataMax + 10']
const speedTickFormatter = (v: number): string => v.toFixed(1)
const paceTickFormatter = (v: number): string => formatPace(v, false)
const swimXFormatter = (v: number): string => String(Math.round(v * 1000))

/** Elevation, pace, heart rate and cadence along the distance, with planned segments and stops marked. */
export default function StreamCharts({ activity, activityScore, streamSeries }: {
  activity: ActivityDetail
  activityScore: ActivityScoreResponse | null | undefined
  streamSeries: StreamSeries
}) {
  const sportCategory = getSportCategory(activity.sport_type)
  const useSpeedUnit = isSpeedSport(activity.sport_type)
  const paceUnit = paceUnitOf(activity.sport_type)

  // Build segment zones for charts from execution score data
  const segmentZones = useMemo<ChartZone[]>(() => {
    if (!activityScore?.score) return []
    const segScores = activityScore.score.segment_scores
    if (!segScores || segScores.length === 0) return []

    return segScores
      .filter(seg => seg.start_km != null && seg.end_km != null && seg.end_km > seg.start_km)
      .map(seg => {
        const segType = seg.is_recovery ? 'recovery' : (seg.type || 'work')
        return {
          x1: seg.start_km!,
          x2: seg.end_km!,
          color: getSegmentColor(segType),
          label: SEG_TYPE_LABELS[segType] || segType,
          opacity: segType === 'work' ? 0.15 : 0.08,
        }
      })
  }, [activityScore])

  const stopMarkers = useMemo<ChartMarker[]>(
    () => (activity?.stops ?? []).map(stop => ({
      x: stop.start_km,
      label: formatClockDuration(stop.duration_s),
      color: STOP_COLOR,
    })),
    [activity],
  )
  const stopsLegend = useMemo(() => {
    const stops = activity?.stops ?? []
    if (stops.length === 0) return undefined
    const total = stops.reduce((sum, stop) => sum + stop.duration_s, 0)
    return {
      label: `${stops.length} ${stops.length === 1 ? 'stop' : 'stops'} · ${formatClockDuration(total)}`,
      color: STOP_COLOR,
    }
  }, [activity])

  const hasPace = streamSeries.pace.length > 0
  const hasHR = streamSeries.heartrate.length > 0
  const hasElevation = streamSeries.elevation.length > 0
  const hasCadence = streamSeries.cadence.length > 0
  const hasPower = streamSeries.power.length > 0
  const isRunning = sportCategory === 'running'
  const hasGap = isRunning && streamSeries.gap.length > 0
  const isSwimStream = sportCategory === 'swimming'
  const streamXUnit = isSwimStream ? 'm' : 'km'
  const streamXFormatter = isSwimStream ? swimXFormatter : undefined
  return (
    <>
      {hasElevation && (
        <StreamChart
          title="Elevation"
          data={streamSeries.elevation}
          color={getSportColor(activity.sport_type)}
          gradientId="elevGrad"
          unit="m"
          yDomain={ELEVATION_Y_DOMAIN}
          zones={segmentZones.length > 0 ? segmentZones : undefined}
          markers={stopMarkers}
          markersLegend={stopsLegend}
          xUnit={streamXUnit}
          xFormatter={streamXFormatter}
        />
      )}

      {hasPace && (
        <StreamChart
          title={useSpeedUnit ? 'Speed' : 'Pace'}
          data={streamSeries.pace}
          color={getSportColor(activity.sport_type)}
          gradientId="paceGrad"
          unit={paceUnit}
          reversed={!useSpeedUnit}
          formatValue={useSpeedUnit ? speedTickFormatter : paceTickFormatter}
          secondaryData={hasGap ? streamSeries.gap : undefined}
          secondaryColor="#f97316"
          secondaryLabel="GAP"
          zones={segmentZones.length > 0 ? segmentZones : undefined}
          markers={stopMarkers}
          markersLegend={stopsLegend}
          xUnit={streamXUnit}
          xFormatter={streamXFormatter}
        />
      )}

      {hasHR && (
        <StreamChart
          title="Heart Rate"
          data={streamSeries.heartrate}
          color="#ec4899"
          gradientId="hrGrad"
          unit="bpm"
          zones={segmentZones.length > 0 ? segmentZones : undefined}
          markers={stopMarkers}
          markersLegend={stopsLegend}
          xUnit={streamXUnit}
          xFormatter={streamXFormatter}
        />
      )}

      {hasCadence && (
        <StreamChart
          title="Cadence"
          data={streamSeries.cadence}
          color="#34d399"
          gradientId="cadGrad"
          unit="spm"
          zones={segmentZones.length > 0 ? segmentZones : undefined}
          markers={stopMarkers}
          markersLegend={stopsLegend}
          xUnit={streamXUnit}
          xFormatter={streamXFormatter}
        />
      )}

      {hasPower && (
        <StreamChart
          title="Power"
          data={streamSeries.power}
          color="#a855f7"
          gradientId="powerGrad"
          unit="W"
          zones={segmentZones.length > 0 ? segmentZones : undefined}
          markers={stopMarkers}
          markersLegend={stopsLegend}
          xUnit={streamXUnit}
          xFormatter={streamXFormatter}
        />
      )}
    </>
  )
}
