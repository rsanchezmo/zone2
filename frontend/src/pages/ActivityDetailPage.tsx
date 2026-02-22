import { useMemo } from 'react'
import { useParams } from 'react-router-dom'
import { useActivity, useAthleteZones } from '../api/hooks'
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

export default function ActivityDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { data: activity, isLoading } = useActivity(Number(id))
  const { data: athleteZones } = useAthleteZones()

  const sportCategory = getSportCategory(activity?.sport_type)
  const useSpeedUnit = sportCategory === 'cycling' || sportCategory === 'speed' || sportCategory === 'water'

  const { positions, streamSeries, paceUnit } = useMemo(() => {
    const pos: [number, number][] = []
    const series: {
      elevation: { distance: number; value: number }[]
      pace: { distance: number; value: number }[]
      heartrate: { distance: number; value: number }[]
      cadence: { distance: number; value: number }[]
    } = { elevation: [], pace: [], heartrate: [], cadence: [] }

    if (activity?.streams && Array.isArray(activity.streams)) {
      const streams = activity.streams as StreamPoint[]

      for (const pt of streams) {
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
          // Filter outliers based on sport
          const cat = getSportCategory(activity?.sport_type)
          const isOutlier = cat === 'swimming' ? paceVal > 5 : cat === 'cycling' ? paceVal < 1 : paceVal > 20
          if (!isOutlier) {
            series.pace.push({ distance: dist, value: paceVal })
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
    return { positions: pos, streamSeries: series, paceUnit: pu }
  }, [activity])

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
    </div>
  )
}
