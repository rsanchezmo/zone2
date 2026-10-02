import { useMemo } from 'react'
import clsx from 'clsx'
import type { ActivityDetail, ActivityRoute } from '../../api/hooks'
import { getSportColor } from '../../constants/sportColors'
import { useTheme } from '../../hooks/useTheme'
import {
  getSportCategory, convertSpeed, formatPace, formatClockDuration, isSpeedSport,
} from '../../utils/formatSpeed'
import MapView, { type KmMarker } from '../shared/MapView'
import type { Split } from './activityData'

/** The track on the map, coloured by pace, with km markers and the street route it was matched to. */
export default function RouteMap({ activity, positions, velocities, splits, matched }: {
  activity: ActivityDetail
  positions: [number, number][]
  velocities: number[]
  splits: Split[]
  matched: ActivityRoute | null | undefined
}) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const sportCategory = getSportCategory(activity.sport_type)
  const useSpeedUnit = isSpeedSport(activity.sport_type)
  const sportAccent = getSportColor(activity.sport_type)

  // GeoJSON is [lon, lat]; Leaflet wants [lat, lon]
  const matchedRoute = useMemo(
    () => matched?.features.flatMap(f => f.geometry.coordinates.map(line => line.map(([lon, lat]) => [lat, lon] as [number, number]))),
    [matched],
  )

  // Compute gradient legend labels (fast/slow pace or speed at p5/p95)
  const { gradientFastLabel, gradientSlowLabel } = useMemo(() => {
    if (!velocities || velocities.length === 0) return { gradientFastLabel: undefined, gradientSlowLabel: undefined }
    const valid = velocities.filter(v => v > 0.3)
    if (valid.length === 0) return { gradientFastLabel: undefined, gradientSlowLabel: undefined }
    const sorted = [...valid].sort((a, b) => a - b)
    const p5 = sorted[Math.floor(sorted.length * 0.05)]
    const p95 = sorted[Math.floor(sorted.length * 0.95)]
    const fmt = (ms: number) => {
      const { value, unit } = convertSpeed(ms, activity.sport_type)
      return `${formatPace(value, useSpeedUnit)} ${unit}`
    }
    return { gradientFastLabel: fmt(p95), gradientSlowLabel: fmt(p5) }
  }, [velocities, activity.sport_type, useSpeedUnit])

  // Compute km markers for the map
  const kmMarkers: KmMarker[] = useMemo(() => {
    if (!activity.streams || !Array.isArray(activity.streams) || positions.length === 0 || splits.length === 0) return []
    const streams = activity.streams
    const markers: KmMarker[] = []
    const { unit: pu } = convertSpeed(1, activity.sport_type)

    for (const split of splits) {
      if (split.isPartial) continue
      // Find the stream point closest to this km boundary
      const targetDist = split.km * 1000
      let bestIdx = 0
      let bestDiff = Infinity
      for (let i = 0; i < streams.length; i++) {
        const diff = Math.abs((streams[i].distance ?? 0) - targetDist)
        if (diff < bestDiff) { bestDiff = diff; bestIdx = i }
      }
      // Get position at that index
      const pt = streams[bestIdx]
      let pos: [number, number] | null = null
      if (pt.lat != null && pt.lng != null) pos = [pt.lat, pt.lng]
      else if (pt.latlng) pos = [pt.latlng[0], pt.latlng[1]]
      if (!pos) continue

      const tooltipLines: string[] = [
        sportCategory === 'swimming' ? `${Math.round(split.splitDistance)} m` : `Km ${split.km}`,
        `Pace: ${formatPace(split.avgPace, useSpeedUnit)} ${pu}`,
        `Time: ${formatClockDuration(split.time)}`,
      ]
      if (split.avgHR != null) tooltipLines.push(`HR: ${split.avgHR} bpm`)
      if (split.elevGain > 0 || split.elevLoss > 0) tooltipLines.push(`Elev: +${split.elevGain}m / -${split.elevLoss}m`)
      if (split.avgCadence != null) tooltipLines.push(`Cadence: ${split.avgCadence} ${sportCategory === 'running' ? 'spm' : 'rpm'}`)

      markers.push({ position: pos, km: split.km, tooltipLines })
    }
    return markers
  }, [activity, positions, splits, sportCategory, useSpeedUnit])

  if (positions.length === 0) return null

  return (
    <section>
      <div className="section-head mb-4"><span className="eyebrow">Route</span></div>
      <div className={clsx('h-[300px] md:h-[400px] rounded-xl overflow-hidden border', isLight ? 'border-gray-200' : 'border-surface-600')}>
        <MapView
          positions={positions}
          color={sportAccent}
          kmMarkers={kmMarkers}
          velocities={velocities.length === positions.length ? velocities : undefined}
          invertGradient={!useSpeedUnit}
          gradientFastLabel={gradientFastLabel}
          gradientSlowLabel={gradientSlowLabel}
          matchedRoute={matchedRoute}
          matchedLabel={matched?.features.map(f => f.properties.new_km >= 0.05
            ? `${f.properties.city_name} · +${f.properties.new_km.toFixed(1)} km new streets`
            : f.properties.city_name).join(', ')}
        />
      </div>
    </section>
  )
}
