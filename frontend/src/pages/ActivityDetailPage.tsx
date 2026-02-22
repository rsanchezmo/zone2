import { useMemo } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useActivity, useAthleteZones, useSimilarActivities } from '../api/hooks'
import StatCard from '../components/shared/StatCard'
import MapView from '../components/shared/MapView'
import StreamChart from '../components/shared/StreamChart'
import polyline from '@mapbox/polyline'
import ExportButton from '../components/shared/ExportButton'
import { getSportColor } from '../constants/sportColors'

interface StreamPoint {
  time?: number
  distance?: number
  altitude?: number
  velocity_smooth?: number
  heartrate?: number
  cadence?: number
  lat?: number
  lng?: number
  latlng?: [number, number]
}

const CYCLING_SPORTS = new Set([
  'ride', 'virtualride', 'ebikeride', 'handcycle', 'velomobile',
  'gravelride', 'mountainbikeride', 'emountainbikeride', 'rollerski',
])
const SWIMMING_SPORTS = new Set(['swim'])
const WATER_SPORTS = new Set([
  'canoeing', 'standuppaddling', 'kayaking', 'surfing', 'kitesurf',
  'rowing', 'windsurf', 'sail',
])
const SPEED_SPORTS = new Set([
  'squash', 'tennis', 'pickleball', 'racquetball', 'badminton', 'tabletennis', 'padel',
  'weighttraining', 'workout', 'yoga', 'pilates', 'crossfit', 'highintensityintervaltraining',
  'elliptical', 'stairstepper', 'dance', 'rockclimbing', 'alpineski', 'backcountryski',
  'nordicski', 'snowboard', 'iceskate', 'inlineskate', 'skateboard',
  'soccer', 'basketball', 'volleyball', 'cricket', 'golf',
])

function getSportCategory(sportType: string | undefined): 'cycling' | 'swimming' | 'water' | 'running' | 'speed' {
  const key = (sportType ?? '').toLowerCase().replace(/\s/g, '')
  if (CYCLING_SPORTS.has(key)) return 'cycling'
  if (SWIMMING_SPORTS.has(key)) return 'swimming'
  if (WATER_SPORTS.has(key)) return 'water'
  if (SPEED_SPORTS.has(key)) return 'speed'
  return 'running'
}

function convertSpeed(speedMs: number, sportType: string | undefined): { value: number; unit: string } {
  if (speedMs <= 0) return { value: 0, unit: 'N/A' }
  const cat = getSportCategory(sportType)
  if (cat === 'swimming') {
    return { value: (100 / speedMs) / 60, unit: 'min/100m' }
  } else if (cat === 'cycling' || cat === 'speed' || cat === 'water') {
    return { value: speedMs * 3.6, unit: 'km/h' }
  }
  return { value: (1000 / speedMs) / 60, unit: 'min/km' }
}

interface Split {
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

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function formatPace(value: number, useSpeed: boolean): string {
  if (useSpeed) return value.toFixed(1)
  const m = Math.floor(value)
  const s = Math.round((value - m) * 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function computeSplits(streams: StreamPoint[], sportType: string | undefined, gapSpeeds?: number[]): Split[] {
  if (!streams || streams.length < 2) return []

  const cat = getSportCategory(sportType)
  const useSpeed = cat === 'cycling' || cat === 'speed' || cat === 'water'
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

      currentKm++
      splitStartIdx = i
    }
  }

  return splits
}

export default function ActivityDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { data: activity, isLoading } = useActivity(Number(id))
  const { data: athleteZones } = useAthleteZones()
  const { data: similarActivities } = useSimilarActivities(Number(id))

  const sportCategory = getSportCategory(activity?.sport_type)
  const useSpeedUnit = sportCategory === 'cycling' || sportCategory === 'speed' || sportCategory === 'water'

  const { positions, streamSeries, paceUnit, gapSpeeds, overallGap } = useMemo(() => {
    const pos: [number, number][] = []
    const series: {
      elevation: { distance: number; value: number }[]
      pace: { distance: number; value: number }[]
      gap: { distance: number; value: number }[]
      heartrate: { distance: number; value: number }[]
      cadence: { distance: number; value: number }[]
    } = { elevation: [], pace: [], gap: [], heartrate: [], cadence: [] }
    let gSpeeds: number[] = []
    let avgGap: number | null = null

    if (activity?.streams && Array.isArray(activity.streams)) {
      const streams = activity.streams as StreamPoint[]
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

        // Positions
        if (pt.lat != null && pt.lng != null) {
          pos.push([pt.lat, pt.lng])
        } else if (pt.latlng) {
          pos.push([pt.latlng[0], pt.latlng[1]])
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

    // Determine pace unit from sport
    const { unit: pu } = convertSpeed(1, activity?.sport_type)
    return { positions: pos, streamSeries: series, paceUnit: pu, gapSpeeds: gSpeeds, overallGap: avgGap }
  }, [activity])

  const splits = useMemo(() => {
    if (!activity?.streams || !Array.isArray(activity.streams)) return []
    return computeSplits(activity.streams as StreamPoint[], activity.sport_type, gapSpeeds.length > 0 ? gapSpeeds : undefined)
  }, [activity, gapSpeeds])

  const hrZoneBounds = athleteZones?.heart_rate?.zones as { min: number; max: number }[] | undefined
  const hrZoneDistribution = useMemo(() => {
    if (streamSeries.heartrate.length === 0 || !hrZoneBounds || hrZoneBounds.length < 5) return null
    const boundaries = hrZoneBounds.slice(0, 4).map(z => z.max)
    const counts = [0, 0, 0, 0, 0]
    for (const pt of streamSeries.heartrate) {
      let bin = 4
      for (let i = 0; i < boundaries.length; i++) {
        if (pt.value < boundaries[i]) { bin = i; break }
      }
      counts[bin]++
    }
    const total = counts.reduce((a, b) => a + b, 0)
    if (total === 0) return null
    return counts.map(c => Math.round((c / total) * 1000) / 10)
  }, [hrZoneBounds, streamSeries.heartrate])

  if (isLoading) return <div className="text-gray-500">Loading...</div>
  if (!activity) return <div className="text-gray-500">Activity not found</div>

  const hasPace = streamSeries.pace.length > 0
  const hasHR = streamSeries.heartrate.length > 0
  const hasElevation = streamSeries.elevation.length > 0
  const hasCadence = streamSeries.cadence.length > 0
  const isRunning = sportCategory === 'running'
  const hasGap = isRunning && streamSeries.gap.length > 0

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div>
        <h2 className="text-2xl font-bold">{activity.name}</h2>
        <div className="flex items-center gap-3 mt-1">
          <span className="text-sm flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: getSportColor(activity.sport_type) }} />
            <span style={{ color: getSportColor(activity.sport_type) }}>{activity.sport_type}</span>
          </span>
          <span className="text-sm text-gray-400">
            {activity.start_date_local ? new Date(activity.start_date_local).toLocaleDateString() : ''}
          </span>
          <ExportButton
            url={`/api/exports/activity/${id}`}
            label="Export to PNG"
            filename={`activity_${id}.png`}
          />
        </div>
      </div>

      {/* Map */}
      {positions.length > 0 && (
        <div className="h-[400px] rounded-xl overflow-hidden border border-surface-600">
          <MapView positions={positions} color={getSportColor(activity.sport_type)} />
        </div>
      )}

      {/* Stats Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Distance" value={activity.distance_km?.toFixed(2)} unit="km" />
        <StatCard label="Time" value={activity.moving_time_formatted} />
        {activity.formatted_pace && <StatCard label="Pace" value={activity.formatted_pace} />}
        <StatCard label="Elevation" value={Math.round(activity.total_elevation_gain ?? 0)} unit="m" />
        {activity.average_heartrate && (
          <StatCard label="Avg HR" value={Math.round(activity.average_heartrate)} unit="bpm" color="text-neon-magenta" />
        )}
        {activity.max_heartrate && (
          <StatCard label="Max HR" value={Math.round(activity.max_heartrate)} unit="bpm" color="text-neon-magenta" />
        )}
        {activity.average_cadence && (
          <StatCard label="Cadence" value={Math.round(activity.average_cadence * 2)} unit="spm" color="text-neon-cyan" />
        )}
        {activity.suffer_score && (
          <StatCard label="Suffer Score" value={activity.suffer_score} color="text-neon-yellow" />
        )}
        {hasGap && overallGap != null && (
          <StatCard label="GAP" value={formatPace(overallGap, false)} unit={paceUnit} color="text-orange-400" />
        )}
      </div>

      {/* HR Zone Distribution */}
      {hrZoneDistribution && hrZoneDistribution.some(v => v > 0) && (
        <div className="bg-surface-800 border border-surface-600 rounded-xl p-4">
          <div className="text-xs text-gray-500 uppercase mb-3">HR Zone Distribution</div>
          <div className="flex gap-0.5 h-8 rounded overflow-hidden">
            {[1, 2, 3, 4, 5].map(z => {
              const pct = hrZoneDistribution[z - 1]
              const colors = ['bg-gray-500', 'bg-blue-500', 'bg-green-500', 'bg-yellow-500', 'bg-red-500']
              const bounds = hrZoneBounds?.[z - 1]
              const tooltip = bounds
                ? `Z${z}: ${pct}% (${bounds.min}–${bounds.max} bpm)`
                : `Z${z}: ${pct}%`
              return pct > 0 ? (
                <div
                  key={z}
                  className={`${colors[z - 1]} flex items-center justify-center text-[10px] font-bold text-white cursor-default`}
                  style={{ width: `${pct}%`, minWidth: pct > 0 ? '4px' : 0 }}
                  title={tooltip}
                >
                  {pct >= 8 ? `Z${z}: ${Math.round(pct)}%` : ''}
                </div>
              ) : null
            })}
          </div>
        </div>
      )}

      {/* Per-km Splits */}
      {splits.length > 1 && (() => {
        const fullSplits = splits.filter(s => !s.isPartial)
        const bestPace = fullSplits.length > 0
          ? (useSpeedUnit
              ? Math.max(...fullSplits.map(s => s.avgPace))
              : Math.min(...fullSplits.map(s => s.avgPace)))
          : null
        const worstPace = fullSplits.length > 0
          ? (useSpeedUnit
              ? Math.min(...fullSplits.map(s => s.avgPace))
              : Math.max(...fullSplits.map(s => s.avgPace)))
          : null

        return (
          <div className="bg-surface-800 border border-surface-600 rounded-xl p-4">
            <div className="text-xs text-gray-500 uppercase mb-3">Splits</div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-gray-500 text-xs uppercase border-b border-surface-600">
                    <th className="text-left py-2 pr-3 font-medium">KM</th>
                    <th className="text-right py-2 px-3 font-medium">{useSpeedUnit ? 'Speed' : 'Pace'}</th>
                    {hasGap && (
                      <th className="text-right py-2 px-3 font-medium">GAP</th>
                    )}
                    <th className="text-right py-2 px-3 font-medium">Time</th>
                    {splits.some(s => s.avgHR !== null) && (
                      <th className="text-right py-2 px-3 font-medium">HR</th>
                    )}
                    {splits.some(s => s.avgCadence !== null) && (
                      <th className="text-right py-2 px-3 font-medium">Cadence</th>
                    )}
                    <th className="text-right py-2 px-3 font-medium">Elev +</th>
                    <th className="text-right py-2 pl-3 font-medium">Elev −</th>
                  </tr>
                </thead>
                <tbody>
                  {splits.map(split => {
                    const isBest = !split.isPartial && bestPace !== null && split.avgPace === bestPace
                    const isWorst = !split.isPartial && worstPace !== null && split.avgPace === worstPace

                    // Pace bar width relative to range
                    const paceRange = bestPace !== null && worstPace !== null ? Math.abs(worstPace - bestPace) : 0
                    const barWidth = paceRange > 0 && !split.isPartial
                      ? useSpeedUnit
                        ? ((split.avgPace - worstPace!) / paceRange) * 100
                        : ((worstPace! - split.avgPace) / paceRange) * 100
                      : 50

                    return (
                      <tr
                        key={split.km}
                        className="border-b border-surface-700 last:border-b-0"
                      >
                        <td className="py-2 pr-3 text-gray-400 font-medium">
                          {split.isPartial
                            ? `${(split.splitDistance / 1000).toFixed(2)}`
                            : split.km}
                        </td>
                        <td className="py-2 px-3 text-right font-mono">
                          <div className="flex items-center justify-end gap-2">
                            <div className="w-16 h-1.5 rounded-full bg-surface-600 overflow-hidden hidden sm:block">
                              <div
                                className="h-full rounded-full"
                                style={{
                                  width: `${Math.max(5, barWidth)}%`,
                                  backgroundColor: isBest
                                    ? '#39ff14'
                                    : isWorst
                                      ? '#ff4444'
                                      : getSportColor(activity.sport_type),
                                }}
                              />
                            </div>
                            <span className={
                              isBest ? 'text-green-400 font-bold' :
                              isWorst ? 'text-red-400' :
                              'text-gray-200'
                            }>
                              {formatPace(split.avgPace, useSpeedUnit)}
                              <span className="text-gray-500 text-xs ml-1">{paceUnit}</span>
                            </span>
                          </div>
                        </td>
                        {hasGap && (
                          <td className="py-2 px-3 text-right text-orange-400 font-mono">
                            {split.gapPace != null ? formatPace(split.gapPace, false) : '–'}
                            <span className="text-gray-500 text-xs ml-1">{paceUnit}</span>
                          </td>
                        )}
                        <td className="py-2 px-3 text-right text-gray-300 font-mono">
                          {formatTime(split.time)}
                        </td>
                        {splits.some(s => s.avgHR !== null) && (
                          <td className="py-2 px-3 text-right text-neon-magenta font-mono">
                            {split.avgHR ?? '–'}
                          </td>
                        )}
                        {splits.some(s => s.avgCadence !== null) && (
                          <td className="py-2 px-3 text-right text-neon-cyan font-mono">
                            {split.avgCadence ?? '–'}
                          </td>
                        )}
                        <td className="py-2 px-3 text-right text-green-400/70 font-mono text-xs">
                          {split.elevGain > 0 ? `+${split.elevGain}m` : '–'}
                        </td>
                        <td className="py-2 pl-3 text-right text-red-400/70 font-mono text-xs">
                          {split.elevLoss > 0 ? `−${split.elevLoss}m` : '–'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )
      })()}

      {/* Stream Charts */}
      {hasElevation && (
        <StreamChart
          title="Elevation"
          data={streamSeries.elevation}
          color={getSportColor(activity.sport_type)}
          gradientId="elevGrad"
          unit="m"
          yDomain={['dataMin - 10', 'dataMax + 10']}
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
          formatValue={useSpeedUnit ? (v => `${v.toFixed(1)}`) : (v => {
            const m = Math.floor(v)
            const s = Math.round((v - m) * 60)
            return `${m}:${s.toString().padStart(2, '0')}`
          })}
          secondaryData={hasGap ? streamSeries.gap : undefined}
          secondaryColor="#f97316"
          secondaryLabel="GAP"
        />
      )}

      {hasHR && (
        <StreamChart
          title="Heart Rate"
          data={streamSeries.heartrate}
          color="#ff00ff"
          gradientId="hrGrad"
          unit="bpm"
        />
      )}

      {hasCadence && (
        <StreamChart
          title="Cadence"
          data={streamSeries.cadence}
          color="#39ff14"
          gradientId="cadGrad"
          unit="spm"
        />
      )}

      {/* Similar Activities */}
      {similarActivities && similarActivities.length > 0 && (
        <div className="bg-surface-800 border border-surface-600 rounded-xl p-4">
          <div className="text-xs text-gray-500 uppercase mb-3">Similar Activities</div>
          <div className="divide-y divide-surface-700">
            {similarActivities.map((sa: Record<string, unknown>) => (
              <Link
                key={sa.id as number}
                to={`/activities/${sa.id}`}
                className="flex items-center gap-3 py-2.5 px-1 -mx-1 rounded-lg hover:bg-surface-700 transition-colors group"
              >
                <span
                  className="w-2 h-2 rounded-full flex-shrink-0"
                  style={{ backgroundColor: getSportColor(sa.sport_type as string) }}
                />
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-gray-200 truncate group-hover:text-white transition-colors">
                    {sa.name as string}
                  </div>
                  <div className="text-xs text-gray-500">
                    {sa.start_date_local ? new Date(sa.start_date_local as string).toLocaleDateString() : ''}
                  </div>
                </div>
                <div className="flex items-center gap-4 text-xs text-gray-400 font-mono flex-shrink-0">
                  <span>{(sa.distance_km as number)?.toFixed(1)} km</span>
                  {sa.formatted_pace && <span>{sa.formatted_pace as string}</span>}
                  {(sa.total_elevation_gain as number) > 0 && (
                    <span className="text-green-400/70">+{Math.round(sa.total_elevation_gain as number)}m</span>
                  )}
                  <span>{sa.moving_time_formatted as string}</span>
                </div>
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
