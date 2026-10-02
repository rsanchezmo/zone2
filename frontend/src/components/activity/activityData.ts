import polyline from '@mapbox/polyline'
import type { ActivityDetail, ActivityStreamPoint as StreamPoint } from '../../api/hooks'
import { convertSpeed, getSportCategory } from '../../utils/formatSpeed'

export interface Split {
  km: number
  isPartial: boolean
  splitDistance: number // actual distance of this split in meters
  time: number // seconds
  avgPace: number // converted pace/speed value
  gapPace: number | null // grade adjusted pace (running only)
  avgHR: number | null
  avgCadence: number | null
  elevGain: number
  elevLoss: number
}

/** Minetti metabolic cost factor for a given grade (as fraction, e.g. 0.05 = 5%) */
function minettiCostFactor(grade: number): number {
  const g = grade
  return 155.4 * g ** 5 - 30.4 * g ** 4 - 43.3 * g ** 3 + 46.3 * g ** 2 + 19.5 * g + 3.6
}

const FLAT_COST = 3.6 // minettiCostFactor(0)

/** Smooth an array with a simple moving average of given window size */
function smoothArray(arr: number[], window: number): number[] {
  const half = Math.floor(window / 2)
  return arr.map((_, i) => {
    let sum = 0
    let count = 0
    for (let j = Math.max(0, i - half); j <= Math.min(arr.length - 1, i + half); j++) {
      sum += arr[j]
      count++
    }
    return sum / count
  })
}

/** Compute GAP-adjusted speed for each stream point (running only) */
function computeGapSpeeds(streams: StreamPoint[]): number[] {
  if (streams.length < 2) return []

  // Compute raw grades
  const rawGrades: number[] = [0]
  for (let i = 1; i < streams.length; i++) {
    const dDist = (streams[i].distance ?? 0) - (streams[i - 1].distance ?? 0)
    const dAlt = (streams[i].altitude ?? 0) - (streams[i - 1].altitude ?? 0)
    rawGrades.push(dDist > 0.5 ? dAlt / dDist : 0) // grade as fraction
  }

  // Smooth grades
  const grades = smoothArray(rawGrades, 10)

  // Compute GAP speed per point
  return streams.map((pt, i) => {
    const speed = pt.velocity_smooth ?? 0
    if (speed <= 0.3) return 0
    const cost = minettiCostFactor(grades[i])
    return speed * (cost / FLAT_COST)
  })
}

export const SEG_TYPE_LABELS: Record<string, string> = {
  warmup: 'Warmup', work: 'Work', recovery: 'Recovery', cooldown: 'Cooldown', rest: 'Rest',
}

function computeSplits(streams: StreamPoint[], sportType: string | undefined, gapSpeeds?: number[]): Split[] {
  if (!streams || streams.length < 2) return []

  const cat = getSportCategory(sportType)
  const isRunning = cat === 'running'
  const splits: Split[] = []
  let currentKm = 0
  let splitStartIdx = 0

  for (let i = 1; i < streams.length; i++) {
    const dist = (streams[i].distance ?? 0) / 1000
    const nextKm = currentKm + 1

    if (dist >= nextKm || i === streams.length - 1) {
      const isLast = i === streams.length - 1
      const isPartial = isLast && dist < nextKm

      // Gather points for this split
      const splitPoints = streams.slice(splitStartIdx, i + 1)
      const startDist = streams[splitStartIdx].distance ?? 0
      const endDist = streams[i].distance ?? 0
      const startTime = streams[splitStartIdx].time ?? 0
      const endTime = streams[i].time ?? 0
      const splitDistance = endDist - startDist
      const time = endTime - startTime

      // Average pace/speed from velocity_smooth
      let speedSum = 0
      let speedCount = 0
      let gapSpeedSum = 0
      let gapSpeedCount = 0
      let hrSum = 0
      let hrCount = 0
      let cadSum = 0
      let cadCount = 0
      let elevGain = 0
      let elevLoss = 0

      for (let j = 0; j < splitPoints.length; j++) {
        const pt = splitPoints[j]
        const globalIdx = splitStartIdx + j
        if (pt.velocity_smooth != null && pt.velocity_smooth > 0.3) {
          speedSum += pt.velocity_smooth
          speedCount++
          if (isRunning && gapSpeeds && gapSpeeds[globalIdx] > 0) {
            gapSpeedSum += gapSpeeds[globalIdx]
            gapSpeedCount++
          }
        }
        if (pt.heartrate != null && pt.heartrate > 0) {
          hrSum += pt.heartrate
          hrCount++
        }
        if (pt.cadence != null && pt.cadence > 0) {
          cadSum += pt.cadence
          cadCount++
        }
        if (j > 0 && pt.altitude != null && splitPoints[j - 1].altitude != null) {
          const diff = pt.altitude! - splitPoints[j - 1].altitude!
          if (diff > 0) elevGain += diff
          else elevLoss += Math.abs(diff)
        }
      }

      const avgSpeedMs = speedCount > 0 ? speedSum / speedCount : (splitDistance / time || 0)
      const { value: avgPace } = convertSpeed(avgSpeedMs, sportType)

      let gapPace: number | null = null
      if (isRunning && gapSpeedCount > 0) {
        const avgGapSpeed = gapSpeedSum / gapSpeedCount
        const { value } = convertSpeed(avgGapSpeed, sportType)
        gapPace = value
      }

      splits.push({
        km: currentKm + 1,
        isPartial: isPartial,
        splitDistance,
        time,
        avgPace,
        gapPace,
        avgHR: hrCount > 0 ? Math.round(hrSum / hrCount) : null,
        avgCadence: cadCount > 0 ? Math.round((cadSum / cadCount) * (cat === 'running' ? 2 : 1)) : null,
        elevGain: Math.round(elevGain),
        elevLoss: Math.round(elevLoss),
      })

      // A GPS gap can cross several km boundaries in one step — skip to the last one crossed
      currentKm = Math.max(currentKm + 1, Math.floor(dist))
      // Start after the boundary sample so it isn't averaged into both splits
      splitStartIdx = i + 1
    }
  }

  return splits
}

// A single slow sample gap (tight turn, GPS jitter) isn't worth flagging.
export const MIN_STOPPED_S_SHOWN = 10
export const STOP_COLOR = '#f59e0b'

/** The unit `convertSpeed` reports for a sport: min/km, km/h or min/100m. */
export function paceUnitOf(sportType: string | undefined): string {
  return convertSpeed(1, sportType).unit
}

interface SeriesPoint {
  distance: number
  value: number
}

export interface StreamSeries {
  elevation: SeriesPoint[]
  pace: SeriesPoint[]
  gap: SeriesPoint[]
  heartrate: SeriesPoint[]
  cadence: SeriesPoint[]
}

export interface StreamData {
  positions: [number, number][]
  /** One per position, for the map's pace gradient. */
  velocities: number[]
  streamSeries: StreamSeries
  gapSpeeds: number[]
  overallGap: number | null
}

/** Map positions and per-distance chart series from the streams, with GAP for runs. */
export function buildStreamData(activity: ActivityDetail | undefined): StreamData {
  const pos: [number, number][] = []
  const vels: number[] = []
  const series: StreamSeries = { elevation: [], pace: [], gap: [], heartrate: [], cadence: [] }
  let gSpeeds: number[] = []
  let avgGap: number | null = null

  if (activity?.streams && Array.isArray(activity.streams)) {
    const streams = activity.streams
    const isRunning = getSportCategory(activity?.sport_type) === 'running'

    // Compute GAP speeds for running
    if (isRunning) {
      gSpeeds = computeGapSpeeds(streams)
    }

    let gapSum = 0
    let gapCount = 0

    for (let idx = 0; idx < streams.length; idx++) {
      const pt = streams[idx]
      const dist = (pt.distance ?? 0) / 1000

      // Positions + velocities (kept in sync)
      if (pt.lat != null && pt.lng != null) {
        pos.push([pt.lat, pt.lng])
        vels.push(pt.velocity_smooth ?? 0)
      } else if (pt.latlng) {
        pos.push([pt.latlng[0], pt.latlng[1]])
        vels.push(pt.velocity_smooth ?? 0)
      }

      // Elevation
      if (pt.altitude != null) {
        series.elevation.push({ distance: dist, value: pt.altitude })
      }

      // Pace/Speed (sport-aware conversion)
      if (pt.velocity_smooth != null && pt.velocity_smooth > 0.3) {
        const { value: paceVal } = convertSpeed(pt.velocity_smooth, activity?.sport_type)
        const cat = getSportCategory(activity?.sport_type)
        const isOutlier = cat === 'swimming' ? paceVal > 5 : cat === 'cycling' ? paceVal < 1 : paceVal > 20
        if (!isOutlier) {
          series.pace.push({ distance: dist, value: paceVal })

          // GAP line for running
          if (isRunning && gSpeeds[idx] > 0) {
            const { value: gapVal } = convertSpeed(gSpeeds[idx], activity?.sport_type)
            if (gapVal <= 20) {
              series.gap.push({ distance: dist, value: gapVal })
              gapSum += gSpeeds[idx]
              gapCount++
            }
          }
        }
      }

      // Heart rate
      if (pt.heartrate != null && pt.heartrate > 0) {
        series.heartrate.push({ distance: dist, value: pt.heartrate })
      }

      // Cadence
      if (pt.cadence != null && pt.cadence > 0) {
        series.cadence.push({ distance: dist, value: pt.cadence })
      }
    }

    if (gapCount > 0) {
      const { value } = convertSpeed(gapSum / gapCount, activity?.sport_type)
      avgGap = value
    }
  }

  // Fallback to summary_polyline for map
  if (pos.length === 0 && activity?.summary_polyline) {
    try {
      const decoded = polyline.decode(activity.summary_polyline)
      pos.push(...decoded)
    } catch { /* ignore */ }
  }

  return { positions: pos, velocities: vels, streamSeries: series, gapSpeeds: gSpeeds, overallGap: avgGap }
}

/** Strava's metric splits when the detail carries them, else splits computed from the streams. */
export function buildSplits(activity: ActivityDetail | undefined, gapSpeeds: number[]): Split[] {
  // Prefer splits_metric from detail endpoint when available
  if (activity?.splits_metric && Array.isArray(activity.splits_metric) && activity.splits_metric.length > 0) {
    const splitsMetric = activity.splits_metric
    const cat = getSportCategory(activity.sport_type)
    const isRunning = cat === 'running'
    return splitsMetric.map((sm, i) => {
      const avgSpeedMs = sm.average_speed as number || 0
      const { value: avgPace } = convertSpeed(avgSpeedMs, activity.sport_type)
      const gapSpeedMs = sm.average_grade_adjusted_speed as number | null
      let gapPace: number | null = null
      if (isRunning && gapSpeedMs && gapSpeedMs > 0) {
        const { value } = convertSpeed(gapSpeedMs, activity.sport_type)
        gapPace = value
      }
      return {
        km: i + 1,
        isPartial: i === splitsMetric.length - 1 && (sm.distance as number || 0) < 900,
        splitDistance: sm.distance as number || 1000,
        time: sm.moving_time as number || sm.elapsed_time as number || 0,
        avgPace,
        gapPace,
        avgHR: sm.average_heartrate ? Math.round(sm.average_heartrate as number) : null,
        avgCadence: null,
        elevGain: Math.round(sm.elevation_difference as number || 0),
        elevLoss: 0,
      } as Split
    })
  }
  // Fallback to stream-computed splits
  if (!activity?.streams || !Array.isArray(activity.streams)) return []
  return computeSplits(activity.streams, activity.sport_type, gapSpeeds.length > 0 ? gapSpeeds : undefined)
}
