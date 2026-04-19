import { useMemo, useState, useCallback, useEffect, Component, type ReactNode } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { useActivity, useAthleteZones, useSimilarActivities, useActivityScore } from '../api/hooks'
import StatCard from '../components/shared/StatCard'
import MapView from '../components/shared/MapView'
import type { KmMarker } from '../components/shared/MapView'
import StreamChart from '../components/shared/StreamChart'
import type { ChartZone } from '../components/shared/StreamChart'
import polyline from '@mapbox/polyline'
import ExportButton from '../components/shared/ExportButton'
import ChartPanel from '../components/shared/ChartPanel'
import {
  DeviceIcon, ShoeIcon, ThermometerIcon, ClockIcon, DumbbellIcon, MedalIcon, TrophyIcon,
  DistanceIcon, TimerIcon, BoltIcon, RangeIcon, HeartIcon,
} from '../components/icons'
import { getSportColor } from '../constants/sportColors'
import { getSportCategory, convertSpeed, formatPace } from '../utils/formatSpeed'
import { SegmentSummary, getSegmentColor, type Segment } from '../components/shared/SegmentListBuilder'
import { useTheme } from '../hooks/useTheme'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import clsx from 'clsx'

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


interface StravaPhoto {
  unique_id: string
  urls: Record<string, string>
  caption?: string
  location?: [number, number]
}

function PhotoGallery({ photos }: { photos: StravaPhoto[] }) {
  const [lightboxIdx, setLightboxIdx] = useState<number | null>(null)

  const getThumbUrl = (photo: StravaPhoto) => {
    const urls = photo.urls || {}
    return urls['200'] || urls['100'] || urls['400'] || urls['600'] || Object.values(urls)[0]
  }

  const getFullUrl = (photo: StravaPhoto) => {
    const urls = photo.urls || {}
    return urls['600'] || urls['400'] || urls['200'] || urls['100'] || Object.values(urls)[0]
  }

  const close = useCallback(() => setLightboxIdx(null), [])
  const prev = useCallback(() => setLightboxIdx(i => i !== null ? (i - 1 + photos.length) % photos.length : null), [photos.length])
  const next = useCallback(() => setLightboxIdx(i => i !== null ? (i + 1) % photos.length : null), [photos.length])

  useEffect(() => {
    if (lightboxIdx === null) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
      if (e.key === 'ArrowLeft') prev()
      if (e.key === 'ArrowRight') next()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [lightboxIdx, close, prev, next])

  return (
    <>
      {/* Compact horizontal thumbnail strip */}
      <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-thin">
        {photos.map((photo, idx) => (
          <button
            key={photo.unique_id}
            onClick={() => setLightboxIdx(idx)}
            className="relative flex-shrink-0 w-16 h-16 rounded-lg overflow-hidden group cursor-pointer ring-1 ring-inset ring-white/10 hover:ring-white/30 transition-all"
          >
            <img
              src={getThumbUrl(photo)}
              alt={photo.caption || `Photo ${idx + 1}`}
              className="w-full h-full object-cover transition-transform duration-200 group-hover:scale-110"
              loading="lazy"
            />
          </button>
        ))}
      </div>

      {/* Lightbox */}
      {lightboxIdx !== null && (
        <div
          className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/90 backdrop-blur-sm"
          onClick={close}
        >
          <button
            onClick={(e) => { e.stopPropagation(); close() }}
            className="absolute top-4 right-4 w-10 h-10 flex items-center justify-center rounded-full bg-white/10 hover:bg-white/20 text-white text-xl transition-colors"
          >
            &times;
          </button>
          {photos.length > 1 && (
            <>
              <button
                onClick={(e) => { e.stopPropagation(); prev() }}
                className="absolute left-4 top-1/2 -translate-y-1/2 w-10 h-10 flex items-center justify-center rounded-full bg-white/10 hover:bg-white/20 text-white text-lg transition-colors"
              >
                &#8249;
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); next() }}
                className="absolute right-4 top-1/2 -translate-y-1/2 w-10 h-10 flex items-center justify-center rounded-full bg-white/10 hover:bg-white/20 text-white text-lg transition-colors"
              >
                &#8250;
              </button>
            </>
          )}
          <img
            src={getFullUrl(photos[lightboxIdx])}
            alt={photos[lightboxIdx].caption || ''}
            className="max-h-[90vh] max-w-[90vw] object-contain rounded-lg shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          />
          {photos[lightboxIdx].caption && (
            <div className="absolute bottom-6 left-1/2 -translate-x-1/2 text-white/80 text-sm bg-black/50 px-4 py-2 rounded-lg">
              {photos[lightboxIdx].caption}
            </div>
          )}
          {/* Thumbnail strip in lightbox */}
          <div className="absolute bottom-4 left-1/2 -translate-x-1/2 flex gap-1.5">
            {photos.map((photo, idx) => (
              <button
                key={photo.unique_id}
                onClick={(e) => { e.stopPropagation(); setLightboxIdx(idx) }}
                className={clsx(
                  'w-10 h-10 rounded overflow-hidden transition-all flex-shrink-0',
                  idx === lightboxIdx ? 'ring-2 ring-white opacity-100' : 'opacity-50 hover:opacity-80',
                )}
              >
                <img src={getThumbUrl(photo)} alt="" className="w-full h-full object-cover" />
              </button>
            ))}
          </div>
        </div>
      )}
    </>
  )
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

      currentKm++
      splitStartIdx = i
    }
  }

  return splits
}

/* Collapsible execution score section */
function ExecutionScoreCollapsible({
  overall, isSegmented, session, sessionSegments, segmentScores, metrics,
  sc, metricConfig, formatGoal, formatActual, segTypeLabels, formatSegDist, formatDetected, hasBreakdown, isSwim,
}: {
  overall: number
  isSegmented: boolean
  session: Record<string, unknown> | undefined
  sessionSegments: Segment[] | undefined
  segmentScores: Record<string, unknown>[] | undefined
  metrics: Record<string, Record<string, unknown>> | undefined
  sc: (s: number) => string
  metricConfig: Record<string, { label: string; icon: ReactNode; color: string }>
  formatGoal: (key: string, m: Record<string, unknown>) => string
  formatActual: (key: string, m: Record<string, unknown>) => string
  segTypeLabels: Record<string, string>
  formatSegDist: (km: number | null | undefined) => string
  formatDetected: (km: number | null | undefined, mins: number | null | undefined, pace?: number | null, paceUnit?: string) => string | null
  hasBreakdown: boolean
  isSwim: boolean
}) {
  const [expanded, setExpanded] = useState(!isSegmented)
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const cardClass = clsx('rounded-xl p-4 border', isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600')

  return (
    <div className={cardClass}>
      {/* Header — always visible */}
      <div
        className="flex items-center justify-between cursor-pointer select-none"
        onClick={() => hasBreakdown && setExpanded(e => !e)}
      >
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-500 uppercase">Execution Score</span>
          <span className="text-2xl font-bold font-mono" style={{ color: sc(overall) }}>{overall}</span>
          {isSegmented && (
            <span className={clsx('text-[10px] text-gray-500 border rounded-full px-2 py-0.5', isLight ? 'border-gray-300' : 'border-surface-600')}>structured</span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {!!session?.description && (
            <span className="text-xs text-gray-400 italic truncate">{String(session.description)}</span>
          )}
          {hasBreakdown && (
            <span className="text-gray-500 text-xs transition-transform" style={{ transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)' }}>
              {'\u25BC'}
            </span>
          )}
        </div>
      </div>

      {/* Collapsible breakdown */}
      {expanded && (
        <div className="mt-4">
          {/* Segment summary bar */}
          {isSegmented && sessionSegments && sessionSegments.length > 0 && (
            <div className="mb-3">
              <SegmentSummary segments={sessionSegments} />
            </div>
          )}

          {/* Segmented score: per-segment breakdown */}
          {isSegmented && segmentScores && segmentScores.length > 0 && (
            <div className="grid gap-2">
              {segmentScores.map((ss, i) => {
                const segColor = getSegmentColor(ss.type as string)
                const segScore = ss.overall_score as number | null
                const isRecovery = ss.is_recovery as boolean
                const segMetrics = ss.metrics as Record<string, Record<string, unknown>> | undefined
                const typeLabel = segTypeLabels[ss.type as string] ?? (ss.type as string)
                const distLabel = formatSegDist(ss.distance_km as number | null)
                const durLabel = ss.duration_mins ? `${ss.duration_mins}'` : ''
                const repLabel = (ss.rep as number) > 0 ? ` #${ss.rep}` : ''
                const headerLabel = `${isRecovery ? 'Recovery' : typeLabel}${distLabel ? ` ${distLabel}` : ''}${durLabel ? ` ${durLabel}` : ''}${repLabel}`
                const detected = formatDetected(ss.actual_distance_km as number | null, ss.actual_duration_mins as number | null, ss.actual_pace as number | null, ss.pace_unit as string | undefined)
                const startKm = ss.start_km as number | undefined
                const endKm = ss.end_km as number | undefined
                const kmRange = startKm != null && endKm != null
                  ? (isSwim
                      ? `${Math.round(startKm * 1000)} – ${Math.round(endKm * 1000)} m`
                      : `${startKm.toFixed(2)} – ${endKm.toFixed(2)} km`)
                  : null
                const hasScore = segScore != null

                return (
                  <div key={i} className="flex rounded-lg overflow-hidden border" style={{ borderColor: `${segColor}20` }}>
                    <div className="w-1 shrink-0" style={{ backgroundColor: segColor }} />
                    <div className="flex-1 p-3" style={{ backgroundColor: `${segColor}08` }}>
                      <div className="flex items-center justify-between mb-1">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-medium" style={{ color: segColor }}>
                            {headerLabel}
                          </span>
                          {kmRange && (
                            <span className="text-[10px] text-gray-500 font-mono">{kmRange}</span>
                          )}
                          {detected && (
                            <span className="text-[10px] text-gray-500 font-mono">
                              ({detected})
                            </span>
                          )}
                        </div>
                        {hasScore ? (
                          <span className="text-sm font-bold font-mono" style={{ color: sc(segScore) }}>
                            {segScore}
                          </span>
                        ) : (
                          <span className="text-[10px] text-gray-600 italic">no targets</span>
                        )}
                      </div>
                      {/* Per-metric details within this segment */}
                      {segMetrics && Object.keys(segMetrics).length > 0 && (
                        <div className="flex flex-wrap gap-x-4 gap-y-1 mt-1">
                          {Object.entries(segMetrics).map(([key, m]) => {
                            const cfg = metricConfig[key] ?? { label: key, icon: null, color: '#9ca3af' }
                            const metricScore = m.score as number
                            return (
                              <div key={key} className="flex items-center gap-1.5 text-[11px]">
                                <span style={{ color: cfg.color }}>{cfg.icon}</span>
                                <span className="text-gray-500">{formatGoal(key, m)}</span>
                                <span className="text-gray-600">{'\u2192'}</span>
                                <span className={clsx('font-mono', isLight ? 'text-gray-700' : 'text-gray-300')}>{formatActual(key, m)}</span>
                                <span className="font-bold font-mono" style={{ color: sc(metricScore) }}>{metricScore}</span>
                              </div>
                            )
                          })}
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          )}

          {/* Flat score: per-metric breakdown (non-segmented) */}
          {!isSegmented && metrics && (
            <div className="grid gap-2">
              {Object.entries(metrics).map(([key, m]) => {
                const s = m.score as number
                const cfg = metricConfig[key] ?? { label: key, icon: null, color: '#9ca3af' }
                return (
                  <div key={key} className="flex rounded-lg overflow-hidden border" style={{ borderColor: `${cfg.color}20` }}>
                    <div className="w-1 shrink-0" style={{ backgroundColor: cfg.color }} />
                    <div className="flex-1 p-3" style={{ backgroundColor: `${cfg.color}08` }}>
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-xs font-medium flex items-center gap-1.5" style={{ color: cfg.color }}>
                          <span>{cfg.icon}</span> {cfg.label}
                        </span>
                        <span className="text-sm font-bold font-mono" style={{ color: sc(s) }}>{s}</span>
                      </div>
                      <div className="flex items-center gap-3 text-xs">
                        <div className="flex-1">
                          <div className="text-[10px] text-gray-500 uppercase mb-0.5">Goal</div>
                          <div className={clsx('font-mono', isLight ? 'text-gray-600' : 'text-gray-400')}>{formatGoal(key, m)}</div>
                        </div>
                        <div className="text-gray-600 text-lg">{'\u2192'}</div>
                        <div className="flex-1">
                          <div className="text-[10px] text-gray-500 uppercase mb-0.5">Actual</div>
                          <div className={clsx('font-mono', isLight ? 'text-gray-900' : 'text-white')}>{formatActual(key, m)}</div>
                        </div>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

class PageErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  constructor(props: { children: ReactNode }) {
    super(props)
    this.state = { error: null }
  }
  static getDerivedStateFromError(error: Error) {
    return { error }
  }
  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('ActivityDetailPage crash:', error, info.componentStack)
  }
  render() {
    if (this.state.error) {
      return (
        <div className="max-w-6xl mx-auto p-8">
          <h2 className="text-xl font-bold text-red-400 mb-2">Page crashed</h2>
          <pre className="text-sm text-gray-400 bg-surface-800 p-4 rounded-xl overflow-auto whitespace-pre-wrap">
            {this.state.error.message}
            {'\n'}
            {this.state.error.stack}
          </pre>
          <button
            className="mt-4 px-4 py-2 bg-surface-700 border border-surface-600 rounded-lg text-sm hover:bg-surface-600 transition-colors"
            onClick={() => this.setState({ error: null })}
          >
            Try again
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

export default function ActivityDetailPage() {
  return (
    <PageErrorBoundary>
      <ActivityDetailPageInner />
    </PageErrorBoundary>
  )
}

function ActivityDetailPageInner() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { data: activity, isLoading } = useActivity(Number(id))
  const { data: athleteZones } = useAthleteZones()
  const { data: similarActivities } = useSimilarActivities(Number(id))
  const { data: activityScore } = useActivityScore(Number(id))
  const { theme, colors } = useTheme()
  const isLight = theme === 'light'

  const sportCategory = getSportCategory(activity?.sport_type)
  const useSpeedUnit = sportCategory === 'cycling' || sportCategory === 'speed' || sportCategory === 'water'

  const { positions, velocities, streamSeries, paceUnit, gapSpeeds, overallGap } = useMemo(() => {
    const pos: [number, number][] = []
    const vels: number[] = []
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

    // Determine pace unit from sport
    const { unit: pu } = convertSpeed(1, activity?.sport_type)
    return { positions: pos, velocities: vels, streamSeries: series, paceUnit: pu, gapSpeeds: gSpeeds, overallGap: avgGap }
  }, [activity])

  const splits = useMemo(() => {
    // Prefer splits_metric from detail endpoint when available
    if (activity?.splits_metric && Array.isArray(activity.splits_metric) && activity.splits_metric.length > 0) {
      const cat = getSportCategory(activity.sport_type)
      const isRunning = cat === 'running'
      return activity.splits_metric.map((sm: Record<string, unknown>, i: number) => {
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
          isPartial: i === activity.splits_metric.length - 1 && (sm.distance as number || 0) < 900,
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
    return computeSplits(activity.streams as StreamPoint[], activity.sport_type, gapSpeeds.length > 0 ? gapSpeeds : undefined)
  }, [activity, gapSpeeds])

  // Compute gradient legend labels (fast/slow pace or speed at p5/p95)
  const { gradientFastLabel, gradientSlowLabel } = useMemo(() => {
    if (!velocities || velocities.length === 0) return { gradientFastLabel: undefined, gradientSlowLabel: undefined }
    const valid = velocities.filter(v => v > 0.3)
    if (valid.length === 0) return { gradientFastLabel: undefined, gradientSlowLabel: undefined }
    const sorted = [...valid].sort((a, b) => a - b)
    const p5 = sorted[Math.floor(sorted.length * 0.05)]
    const p95 = sorted[Math.floor(sorted.length * 0.95)]
    const fmt = (ms: number) => {
      const { value, unit } = convertSpeed(ms, activity?.sport_type)
      return `${formatPace(value, useSpeedUnit)} ${unit}`
    }
    return { gradientFastLabel: fmt(p95), gradientSlowLabel: fmt(p5) }
  }, [velocities, activity?.sport_type, useSpeedUnit])

  // Compute km markers for the map
  const kmMarkers: KmMarker[] = useMemo(() => {
    if (!activity?.streams || !Array.isArray(activity.streams) || positions.length === 0 || splits.length === 0) return []
    const streams = activity.streams as StreamPoint[]
    const markers: KmMarker[] = []
    const { unit: pu } = convertSpeed(1, activity?.sport_type)

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

      // Format time
      const mins = Math.floor(split.time / 60)
      const secs = Math.round(split.time % 60)
      const timeStr = `${mins}:${secs.toString().padStart(2, '0')}`

      // Format pace
      const paceMin = Math.floor(split.avgPace)
      const paceSec = Math.round((split.avgPace - paceMin) * 60)
      const paceStr = pu.includes('min') ? `${paceMin}:${paceSec.toString().padStart(2, '0')} ${pu}` : `${split.avgPace.toFixed(1)} ${pu}`

      let tooltip = sportCategory === 'swimming' ? `<b>${Math.round(split.splitDistance)} m</b><br/>` : `<b>Km ${split.km}</b><br/>`
      tooltip += `Pace: ${paceStr}<br/>`
      tooltip += `Time: ${timeStr}`
      if (split.avgHR != null) tooltip += `<br/>HR: ${split.avgHR} bpm`
      if (split.elevGain > 0 || split.elevLoss > 0) tooltip += `<br/>Elev: +${split.elevGain}m / -${split.elevLoss}m`
      if (split.avgCadence != null) tooltip += `<br/>Cadence: ${split.avgCadence} spm`

      markers.push({ position: pos, km: split.km, tooltip })
    }
    return markers
  }, [activity, positions, splits])

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

  // Build segment zones for charts from execution score data
  // NOTE: must be before early returns to avoid hooks-order violation
  const segmentZones = useMemo<ChartZone[]>(() => {
    if (!activityScore?.score) return []
    const segScores = activityScore.score.segment_scores as { type: string; start_km?: number; end_km?: number; actual_distance_km: number; is_recovery: boolean }[] | undefined
    if (!segScores || segScores.length === 0) return []

    const typeLabels: Record<string, string> = {
      warmup: 'Warmup', work: 'Work', recovery: 'Recovery', cooldown: 'Cooldown', rest: 'Rest',
    }

    return segScores
      .filter(seg => seg.start_km != null && seg.end_km != null && seg.end_km > seg.start_km)
      .map(seg => {
        const segType = seg.is_recovery ? 'recovery' : (seg.type || 'work')
        return {
          x1: seg.start_km!,
          x2: seg.end_km!,
          color: getSegmentColor(segType),
          label: typeLabels[segType] || segType,
          opacity: segType === 'work' ? 0.15 : 0.08,
        }
      })
  }, [activityScore])

  if (isLoading) return <div className="text-gray-500">Loading...</div>
  if (!activity) return <div className="text-gray-500">Activity not found</div>

  const hasPace = streamSeries.pace.length > 0
  const hasHR = streamSeries.heartrate.length > 0
  const hasElevation = streamSeries.elevation.length > 0
  const hasCadence = streamSeries.cadence.length > 0
  const isRunning = sportCategory === 'running'
  const hasGap = isRunning && streamSeries.gap.length > 0

  const sportAccent = getSportColor(activity.sport_type)

  return (
    <div className="max-w-6xl mx-auto space-y-10 pb-12">
      {/* ── Header ───────────────────────────────────── */}
      <header>
        <button
          onClick={() => navigate(-1)}
          className={clsx(
            'group inline-flex items-center gap-1.5 text-[11px] uppercase tracking-[0.18em] mb-4 transition-colors duration-150',
            isLight ? 'text-gray-500 hover:text-gray-900' : 'text-gray-500 hover:text-gray-100',
          )}
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 16 16"
            fill="currentColor"
            className="w-3 h-3 transition-transform duration-150 group-hover:-translate-x-0.5"
            aria-hidden="true"
          >
            <path fillRule="evenodd" d="M9.78 4.22a.75.75 0 0 1 0 1.06L7.06 8l2.72 2.72a.75.75 0 1 1-1.06 1.06L5.47 8.53a.75.75 0 0 1 0-1.06l3.25-3.25a.75.75 0 0 1 1.06 0Z" clipRule="evenodd" />
          </svg>
          Back
        </button>

        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-3 flex-wrap mb-2">
              <span
                className="inline-flex items-center gap-1.5 text-[10px] uppercase tracking-[0.18em] font-semibold px-2 py-1 rounded-full border"
                style={{
                  backgroundColor: `${sportAccent}15`,
                  color: sportAccent,
                  borderColor: `${sportAccent}40`,
                }}
              >
                <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: sportAccent }} aria-hidden="true" />
                {activity.sport_type}
              </span>
              <span className={clsx('text-[11px] font-mono tabular-nums', isLight ? 'text-gray-500' : 'text-gray-500')}>
                {activity.start_date_local ? new Date(activity.start_date_local).toLocaleDateString(undefined, { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric' }) : ''}
              </span>
            </div>
            <h2
              className={clsx('text-2xl md:text-3xl font-semibold tracking-tight leading-tight', isLight ? 'text-gray-900' : 'text-gray-100')}
              style={{ letterSpacing: '-0.02em' }}
            >
              {activity.name}
            </h2>
          </div>
          <div className="shrink-0">
            <ExportButton
              url={`/api/exports/activity/${id}`}
              label="PNG"
              filename={`activity_${id}.png`}
              exportType="activity"
            />
          </div>
        </div>

        {activity.description && (
          <p className={clsx('text-sm mt-4 whitespace-pre-line max-w-3xl', isLight ? 'text-gray-600' : 'text-gray-400')}>
            {activity.description}
          </p>
        )}
        {activity.photos && activity.photos.length > 0 && (
          <div className="mt-5">
            <PhotoGallery photos={activity.photos} />
          </div>
        )}

        {/* Metadata pills — hairline-bordered, sport-agnostic */}
        {(activity.device_name || activity.gear || activity.average_temp != null || activity.timezone || activity.workout_type != null || activity.pr_count > 0 || activity.achievement_count > 0) && (
          <div className="flex flex-wrap gap-1.5 mt-5">
            {activity.device_name && <MetaPill icon={<DeviceIcon size={11} />} text={activity.device_name} />}
            {activity.gear && (
              <MetaPill
                icon={<ShoeIcon size={11} />}
                text={activity.gear.nickname || activity.gear.name}
                suffix={activity.gear.converted_distance != null ? `${Math.round(activity.gear.converted_distance)} km` : undefined}
              />
            )}
            {activity.average_temp != null && <MetaPill icon={<ThermometerIcon size={11} />} text={`${Math.round(activity.average_temp)}°C`} />}
            {activity.timezone && <MetaPill icon={<ClockIcon size={11} />} text={activity.timezone.replace(/^\(.*?\)\s*/, '')} />}
            {activity.workout_type != null && <MetaPill icon={<DumbbellIcon size={11} />} text={String(activity.workout_type)} />}
            {activity.pr_count > 0 && (
              <MetaPill icon={<MedalIcon size={11} />} text={`${activity.pr_count} PR${activity.pr_count > 1 ? 's' : ''}`} tone="amber" />
            )}
            {activity.achievement_count > 0 && (
              <MetaPill icon={<TrophyIcon size={11} />} text={`${activity.achievement_count} achievement${activity.achievement_count > 1 ? 's' : ''}`} tone="green" />
            )}
          </div>
        )}
      </header>

      {/* ── Map ──────────────────────────────────────── */}
      {positions.length > 0 && (
        <section>
          <div className="section-head mb-4"><span className="eyebrow">Route</span></div>
          <div className={clsx('h-[300px] md:h-[400px] rounded-xl overflow-hidden border', isLight ? 'border-gray-200' : 'border-surface-600')}>
            <MapView
              positions={positions}
              color={sportAccent}
              kmMarkers={kmMarkers}
              velocities={velocities.length === positions.length ? velocities : undefined}
              invertGradient={sportCategory !== 'cycling' && sportCategory !== 'speed' && sportCategory !== 'water'}
              gradientFastLabel={gradientFastLabel}
              gradientSlowLabel={gradientSlowLabel}
            />
          </div>
        </section>
      )}

      {/* ── Metrics ─────────────────────────────────── */}
      <section>
        <div className="section-head mb-4"><span className="eyebrow">Metrics</span></div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 stagger-children">
        <StatCard label="Distance" value={sportCategory === 'swimming' ? Math.round((activity.distance_km ?? 0) * 1000) : activity.distance_km?.toFixed(2)} unit={sportCategory === 'swimming' ? 'm' : 'km'} />
        <StatCard label="Moving Time" value={activity.moving_time_formatted} />
        {activity.elapsed_time_formatted && activity.elapsed_time !== activity.moving_time && (
          <StatCard label="Elapsed Time" value={activity.elapsed_time_formatted} />
        )}
        {activity.formatted_pace && <StatCard label="Pace" value={activity.formatted_pace} />}
        {activity.formatted_max_speed && <StatCard label="Max Speed" value={activity.formatted_max_speed} />}
        <StatCard label="Elevation" value={Math.round(activity.total_elevation_gain ?? 0)} unit="m" />
        {activity.average_heartrate && (
          <StatCard label="Avg HR" value={Math.round(activity.average_heartrate)} unit="bpm" color="text-pink-400" />
        )}
        {activity.max_heartrate && (
          <StatCard label="Max HR" value={Math.round(activity.max_heartrate)} unit="bpm" color="text-pink-400" />
        )}
        {activity.average_cadence && (
          <StatCard label="Cadence" value={Math.round(activity.average_cadence * 2)} unit="spm" color="text-blue-400" />
        )}
        {activity.suffer_score && (
          <StatCard label="Suffer Score" value={activity.suffer_score} color="text-amber-400" />
        )}
        {hasGap && overallGap != null && (
          <StatCard label="GAP" value={formatPace(overallGap, false)} unit={paceUnit} color="text-orange-400" />
        )}
        {activity.calories && (
          <StatCard label="Calories" value={Math.round(activity.calories)} unit="kcal" color="text-orange-400" />
        )}
        {activity.average_watts && (
          <StatCard label="Avg Power" value={Math.round(activity.average_watts)} unit="W" color="text-purple-400" />
        )}
        {activity.weighted_average_watts && (
          <StatCard label="NP" value={Math.round(activity.weighted_average_watts)} unit="W" color="text-purple-400" />
        )}
        {activity.max_watts && (
          <StatCard label="Max Power" value={Math.round(activity.max_watts)} unit="W" color="text-purple-400" />
        )}
        </div>
      </section>

      {/* ── Best Efforts ────────────────────────────── */}
      {activity.best_efforts && activity.best_efforts.length > 0 && (
        <ChartPanel title="Best efforts" accent={sportAccent} glow={false}>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
            {activity.best_efforts.map((effort: Record<string, unknown>, i: number) => {
              const prRank = effort.pr_rank as number | null
              return (
                <div
                  key={i}
                  className={clsx(
                    'flex items-center justify-between px-3 py-2 rounded-lg border text-sm font-mono tabular-nums',
                    prRank === 1
                      ? (isLight ? 'border-amber-300 bg-amber-50' : 'border-amber-500/40 bg-amber-500/10')
                      : prRank === 2
                        ? (isLight ? 'border-gray-300 bg-gray-50' : 'border-gray-400/30 bg-gray-400/10')
                        : prRank === 3
                          ? (isLight ? 'border-orange-300 bg-orange-50' : 'border-orange-500/30 bg-orange-500/10')
                          : (isLight ? 'border-gray-200' : 'border-surface-600'),
                  )}
                >
                  <span className={clsx('text-xs', isLight ? 'text-gray-600' : 'text-gray-400')}>
                    {effort.name as string}
                  </span>
                  <div className="flex items-center gap-1.5">
                    <span className={isLight ? 'text-gray-800' : 'text-gray-200'}>
                      {formatTime(effort.elapsed_time as number)}
                    </span>
                    {prRank === 1 && <span className="text-amber-400 text-xs font-bold">PR</span>}
                    {prRank === 2 && <span className="text-gray-400 text-[10px]">2nd</span>}
                    {prRank === 3 && <span className="text-orange-400 text-[10px]">3rd</span>}
                  </div>
                </div>
              )
            })}
          </div>
        </ChartPanel>
      )}

      {/* Execution Score */}
      {activityScore?.score && (() => {
        const overall = activityScore.score.overall_score as number
        const metrics = activityScore.score.metrics as Record<string, Record<string, unknown>> | undefined
        const segmentScores = activityScore.score.segment_scores as Record<string, unknown>[] | undefined
        const isSegmented = activityScore.score.mode === 'segmented'
        const session = activityScore.session as Record<string, unknown> | undefined
        const sessionSegments = session?.segments as Segment[] | undefined
        const sc = (s: number) => s >= 80 ? '#22c55e' : s >= 50 ? '#eab308' : '#ef4444'

        const metricConfig: Record<string, { label: string; icon: ReactNode; color: string }> = {
          distance: { label: 'Distance', icon: <DistanceIcon size={11} />, color: '#3b82f6' },
          duration: { label: 'Duration', icon: <TimerIcon size={11} />, color: '#22c55e' },
          avg_pace: { label: 'Avg Pace', icon: <BoltIcon size={11} />, color: '#f97316' },
          pace: { label: 'Pace Range', icon: <RangeIcon size={11} />, color: '#a855f7' },
          hr_zone: { label: 'HR Zone', icon: <HeartIcon size={11} />, color: '#ef4444' },
        }

        const formatPaceVal = (pace: number, unit: string) => {
          if (unit === 'min/km' || unit === 'min/100m') {
            const mins = Math.floor(pace)
            const secs = Math.round((pace - mins) * 60)
            return `${mins}:${secs.toString().padStart(2, '0')} ${unit}`
          }
          return `${Math.round(pace * 10) / 10} ${unit}`
        }

        const isSwim = getSportCategory(activity.sport_type) === 'swimming'
        const formatDistVal = (km: number) => isSwim ? `${Math.round(km * 1000)} m` : `${km} km`

        const formatGoal = (key: string, m: Record<string, unknown>) => {
          if (key === 'distance') return formatDistVal(m.target as number)
          if (key === 'duration') return `${m.target} ${m.unit}`
          if (key === 'avg_pace') return formatPaceVal(m.target as number, m.unit as string)
          if (key === 'pace') {
            const parts = []
            if (m.target_min != null) parts.push(formatPaceVal(m.target_min as number, m.unit as string))
            if (m.target_max != null) parts.push(formatPaceVal(m.target_max as number, m.unit as string))
            return parts.join(' \u2013 ')
          }
          if (key === 'hr_zone') return `Zone ${(m as any).target_zone} @ ${(m as any).target_pct}%`
          return ''
        }

        const formatActual = (key: string, m: Record<string, unknown>) => {
          if (key === 'distance') return formatDistVal(m.actual as number)
          if (key === 'duration') return `${m.actual} ${m.unit}`
          if (key === 'avg_pace') return formatPaceVal(m.actual as number, m.unit as string)
          if (key === 'pace') return formatPaceVal(m.actual as number, m.unit as string)
          if (key === 'hr_zone') return `${(m as any).actual_pct}%`
          return ''
        }

        const segTypeLabels: Record<string, string> = {
          warmup: 'Warmup', work: 'Work', recovery: 'Recovery', cooldown: 'Cooldown', rest: 'Rest',
        }

        const formatSegDist = (km: number | null | undefined) => {
          if (!km) return ''
          if (isSwim) return `${Math.round(km * 1000)}m`
          return km >= 1 ? `${km}km` : `${Math.round(km * 1000)}m`
        }

        const formatDetected = (km: number | null | undefined, mins: number | null | undefined, pace?: number | null, paceUnit?: string) => {
          const parts: string[] = []
          if (km && km > 0) {
            if (isSwim) parts.push(`${Math.round(km * 1000)}m`)
            else parts.push(km >= 1 ? `${Math.round(km * 1000) / 1000}km` : `${Math.round(km * 1000)}m`)
          }
          if (mins && mins > 0) parts.push(`${Math.round(mins * 10) / 10}'`)
          if (pace && paceUnit) parts.push(formatPaceVal(pace, paceUnit))
          return parts.length > 0 ? parts.join(' / ') : null
        }

        const hasBreakdown = isSegmented
          ? (segmentScores && segmentScores.length > 0)
          : (metrics && Object.keys(metrics).length > 0)

        return (
          <ExecutionScoreCollapsible
            overall={overall}
            isSegmented={isSegmented}
            session={session}
            sessionSegments={sessionSegments}
            segmentScores={segmentScores}
            metrics={metrics}
            sc={sc}
            metricConfig={metricConfig}
            formatGoal={formatGoal}
            formatActual={formatActual}
            segTypeLabels={segTypeLabels}
            formatSegDist={formatSegDist}
            formatDetected={formatDetected}
            hasBreakdown={!!hasBreakdown}
            isSwim={isSwim}
          />
        )
      })()}

      {/* ── HR Zone Distribution ────────────────────── */}
      {hrZoneDistribution && hrZoneDistribution.some(v => v > 0) && (
        <ChartPanel title="HR zone distribution" glow={false}>
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
                  className={`${colors[z - 1]} flex items-center justify-center text-[10px] font-bold text-white cursor-default tabular-nums`}
                  style={{ width: `${pct}%`, minWidth: pct > 0 ? '4px' : 0 }}
                  title={tooltip}
                >
                  {pct >= 8 ? `Z${z} · ${Math.round(pct)}%` : ''}
                </div>
              ) : null
            })}
          </div>
        </ChartPanel>
      )}

      {/* ── Garmin Laps ────────────────────────────── */}
      {activity.laps && activity.laps.length > 1 && (() => {
        const laps = activity.laps as Record<string, unknown>[]
        return (
          <ChartPanel title="Laps" accent={sportAccent} glow={false}>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-gray-500 text-xs uppercase border-b border-surface-600/50">
                    <th className="text-left py-2 pr-3 font-medium">#</th>
                    <th className="text-right py-2 px-3 font-medium">Distance</th>
                    <th className="text-right py-2 px-3 font-medium">Time</th>
                    <th className="text-right py-2 px-3 font-medium">{useSpeedUnit ? 'Speed' : 'Pace'}</th>
                    {laps.some(l => l.average_heartrate) && (
                      <th className="text-right py-2 px-3 font-medium">Avg HR</th>
                    )}
                    {laps.some(l => l.max_heartrate) && (
                      <th className="text-right py-2 px-3 font-medium">Max HR</th>
                    )}
                    {laps.some(l => l.average_cadence) && (
                      <th className="text-right py-2 px-3 font-medium">Cadence</th>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {laps.map((lap, i) => {
                    const lapSpeed = lap.average_speed as number || 0
                    const { value: paceVal } = convertSpeed(lapSpeed, activity.sport_type)
                    const lapDistRaw = lap.distance as number || 0
                    const isSwim = sportCategory === 'swimming'
                    const lapDist = isSwim ? lapDistRaw : lapDistRaw / 1000

                    return (
                      <tr
                        key={i}
                        className="border-b border-surface-600/30 last:border-b-0"
                      >
                        <td className="py-2 pr-3 text-gray-400 font-medium">
                          {i + 1}
                        </td>
                        <td className={clsx('py-2 px-3 text-right font-mono', isLight ? 'text-gray-600' : 'text-gray-300')}>
                          {isSwim ? `${Math.round(lapDist)} m` : `${lapDist.toFixed(2)} km`}
                        </td>
                        <td className={clsx('py-2 px-3 text-right font-mono', isLight ? 'text-gray-600' : 'text-gray-300')}>
                          {formatTime(lap.moving_time as number || lap.elapsed_time as number || 0)}
                        </td>
                        <td className="py-2 px-3 text-right font-mono">
                          {lapSpeed > 0 ? (
                            <>
                              {formatPace(paceVal, useSpeedUnit)}
                              <span className="text-gray-500 text-xs ml-1">{paceUnit}</span>
                            </>
                          ) : '–'}
                        </td>
                        {laps.some(l => l.average_heartrate) && (
                          <td className="py-2 px-3 text-right text-pink-400 font-mono">
                            {lap.average_heartrate ? Math.round(lap.average_heartrate as number) : '–'}
                          </td>
                        )}
                        {laps.some(l => l.max_heartrate) && (
                          <td className="py-2 px-3 text-right text-pink-400/70 font-mono">
                            {lap.max_heartrate ? Math.round(lap.max_heartrate as number) : '–'}
                          </td>
                        )}
                        {laps.some(l => l.average_cadence) && (
                          <td className="py-2 px-3 text-right text-blue-400 font-mono">
                            {lap.average_cadence ? Math.round((lap.average_cadence as number) * (sportCategory === 'running' ? 2 : 1)) : '–'}
                          </td>
                        )}
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </ChartPanel>
        )
      })()}

      {/* ── Per-km Splits ──────────────────────────── */}
      {splits.length > 1 && (() => {
        const fullSplits = splits.filter((s: Split) => !s.isPartial)
        const bestPace = fullSplits.length > 0
          ? (useSpeedUnit
              ? Math.max(...fullSplits.map((s: Split) => s.avgPace))
              : Math.min(...fullSplits.map((s: Split) => s.avgPace)))
          : null
        const worstPace = fullSplits.length > 0
          ? (useSpeedUnit
              ? Math.min(...fullSplits.map((s: Split) => s.avgPace))
              : Math.max(...fullSplits.map((s: Split) => s.avgPace)))
          : null

        return (
          <ChartPanel title="Splits" accent={sportAccent} glow={false}>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-gray-500 text-xs uppercase border-b border-surface-600/50">
                    <th className="text-left py-2 pr-3 font-medium">{sportCategory === 'swimming' ? '#' : 'KM'}</th>
                    <th className="text-right py-2 px-3 font-medium">{useSpeedUnit ? 'Speed' : 'Pace'}</th>
                    {hasGap && (
                      <th className="text-right py-2 px-3 font-medium">GAP</th>
                    )}
                    <th className="text-right py-2 px-3 font-medium">Time</th>
                    {splits.some((s: Split) => s.avgHR !== null) && (
                      <th className="text-right py-2 px-3 font-medium">HR</th>
                    )}
                    {splits.some((s: Split) => s.avgCadence !== null) && (
                      <th className="text-right py-2 px-3 font-medium">Cadence</th>
                    )}
                    <th className="text-right py-2 px-3 font-medium">Elev +</th>
                    <th className="text-right py-2 pl-3 font-medium">Elev −</th>
                  </tr>
                </thead>
                <tbody>
                  {splits.map((split: Split) => {
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
                        className="border-b border-surface-600/30 last:border-b-0"
                      >
                        <td className="py-2 pr-3 text-gray-400 font-medium">
                          {split.isPartial
                            ? (sportCategory === 'swimming' ? `${Math.round(split.splitDistance)} m` : `${(split.splitDistance / 1000).toFixed(2)}`)
                            : (sportCategory === 'swimming' ? `${Math.round(split.splitDistance)} m` : split.km)}
                        </td>
                        <td className="py-2 px-3 text-right font-mono">
                          <div className="flex items-center justify-end gap-2">
                            <div className={clsx('w-16 h-1.5 rounded-full overflow-hidden hidden sm:block', isLight ? 'bg-gray-200' : 'bg-surface-600')}>
                              <div
                                className="h-full rounded-full"
                                style={{
                                  width: `${Math.max(5, barWidth)}%`,
                                  backgroundColor: isBest
                                    ? '#22c55e'
                                    : isWorst
                                      ? '#ff4444'
                                      : getSportColor(activity.sport_type),
                                }}
                              />
                            </div>
                            <span className={
                              isBest ? 'text-green-400 font-bold' :
                              isWorst ? 'text-red-400' :
                              ''
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
                        <td className={clsx('py-2 px-3 text-right font-mono', isLight ? 'text-gray-600' : 'text-gray-300')}>
                          {formatTime(split.time)}
                        </td>
                        {splits.some((s: Split) => s.avgHR !== null) && (
                          <td className="py-2 px-3 text-right text-pink-400 font-mono">
                            {split.avgHR ?? '–'}
                          </td>
                        )}
                        {splits.some((s: Split) => s.avgCadence !== null) && (
                          <td className="py-2 px-3 text-right text-blue-400 font-mono">
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
          </ChartPanel>
        )
      })()}

      {/* ── Stream Charts ──────────────────────────── */}
      {(() => {
        const isSwimStream = sportCategory === 'swimming'
        const streamXUnit = isSwimStream ? 'm' : 'km'
        const streamXFormatter = isSwimStream
          ? (v: number) => String(Math.round(v * 1000))
          : undefined
        return (
          <>
            {hasElevation && (
              <StreamChart
                title="Elevation"
                data={streamSeries.elevation}
                color={getSportColor(activity.sport_type)}
                gradientId="elevGrad"
                unit="m"
                yDomain={['dataMin - 10', 'dataMax + 10']}
                zones={segmentZones.length > 0 ? segmentZones : undefined}
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
                formatValue={useSpeedUnit ? (v => `${v.toFixed(1)}`) : (v => {
                  const m = Math.floor(v)
                  const s = Math.round((v - m) * 60)
                  return `${m}:${s.toString().padStart(2, '0')}`
                })}
                secondaryData={hasGap ? streamSeries.gap : undefined}
                secondaryColor="#f97316"
                secondaryLabel="GAP"
                zones={segmentZones.length > 0 ? segmentZones : undefined}
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
                xUnit={streamXUnit}
                xFormatter={streamXFormatter}
              />
            )}
          </>
        )
      })()}

      {/* Route Performance (Strava similar_activities) */}
      {activity.similar_activities && activity.similar_activities.effort_count > 1 && (() => {
        const sa = activity.similar_activities as {
          effort_count: number
          average_speed: number
          min_average_speed: number
          mid_average_speed: number
          max_average_speed: number
          pr_rank: number | null
          trend: {
            speeds: number[]
            current_activity_index: number
            min_speed: number
            mid_speed: number
            max_speed: number
            direction: number
          } | null
        }
        const trend = sa.trend
        const currentSpeed = activity.average_speed as number
        const sportColor = getSportColor(activity.sport_type)
        const isPaceSport = !useSpeedUnit

        const fmtPaceValue = (v: number) => formatPace(v, useSpeedUnit)

        const trendDir = trend?.direction ?? 0
        const trendLabel = trendDir > 0 ? 'Faster' : trendDir < 0 ? 'Slower' : 'Stable'
        const trendArrow = trendDir > 0 ? '↗' : trendDir < 0 ? '↘' : '→'
        const trendPillClass = trendDir > 0
          ? (isLight ? 'bg-green-50 text-green-700 border-green-200' : 'bg-green-500/10 text-green-400 border-green-500/30')
          : trendDir < 0
            ? (isLight ? 'bg-red-50 text-red-700 border-red-200' : 'bg-red-500/10 text-red-400 border-red-500/30')
            : (isLight ? 'bg-gray-100 text-gray-600 border-gray-200' : 'bg-surface-700 text-gray-400 border-surface-600')

        // Chart data: convert speed (m/s) → pace/speed display values, with labels
        const chartData = trend && trend.speeds.length > 1
          ? trend.speeds.map((s, i) => {
              const speed = i === trend.current_activity_index ? currentSpeed : s
              const { value } = convertSpeed(speed, activity.sport_type)
              return {
                effort: i + 1,
                value: Math.round(value * 100) / 100,
                label: fmtPaceValue(Math.round(value * 100) / 100),
                isCurrent: i === trend.current_activity_index,
              }
            })
          : []
        const statusPills = (
          <div className="flex items-center gap-1.5 flex-wrap">
            {sa.pr_rank === 1 && (
              <span className={clsx('text-[10px] font-bold px-2 py-0.5 rounded-full border', isLight ? 'bg-amber-50 text-amber-600 border-amber-200' : 'bg-amber-500/15 text-amber-400 border-amber-500/30')}>
                PR
              </span>
            )}
            {sa.pr_rank != null && sa.pr_rank > 1 && (
              <span className={clsx('text-[10px] px-2 py-0.5 rounded-full', isLight ? 'bg-gray-100 text-gray-500' : 'bg-surface-700 text-gray-500')}>
                #{sa.pr_rank}/{sa.effort_count}
              </span>
            )}
            {trend && (
              <span className={clsx('text-[10px] font-medium px-2 py-0.5 rounded-full border', trendPillClass)}>
                {trendArrow} {trendLabel}
              </span>
            )}
          </div>
        )
        return (
          <ChartPanel
            title="Route performance"
            accent={sportAccent}
            status={statusPills}
            toolbar={
              <span className={clsx('text-[10px] uppercase tracking-[0.15em]', isLight ? 'text-gray-400' : 'text-gray-500')}>
                {sa.effort_count} efforts
              </span>
            }
            glow={false}
          >
            {chartData.length > 0 && (
              <div className="h-[150px]">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={chartData} margin={{ top: 16, right: 4, bottom: 0, left: 0 }}>
                    <defs>
                      <linearGradient id="routePerfGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor={sportColor} stopOpacity={0.3} />
                        <stop offset="95%" stopColor={sportColor} stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <XAxis
                      dataKey="effort"
                      type="number"
                      domain={[0.5, chartData.length + 0.5]}
                      hide
                    />
                    <YAxis
                      hide
                      domain={(() => {
                        const vals = chartData.map(d => d.value)
                        const min = Math.min(...vals)
                        const max = Math.max(...vals)
                        const range = max - min || 0.2
                        return isPaceSport
                          ? [max + range, min - range]
                          : [min - range, max + range]
                      })()}
                      allowDataOverflow
                    />
                    <Tooltip
                      contentStyle={{ background: colors.tooltipBg, border: `1px solid ${colors.tooltipBorder}`, borderRadius: 8 }}
                      labelStyle={{ color: colors.labelColor }}
                      labelFormatter={v => `Effort #${v}`}
                      formatter={(v: number | undefined) => [fmtPaceValue(v ?? 0) + ` ${paceUnit}`, isPaceSport ? 'Pace' : 'Speed']}
                    />
                    <Area
                      type="monotone"
                      dataKey="value"
                      stroke={sportColor}
                      fill="url(#routePerfGrad)"
                      strokeWidth={1.5}
                      baseValue={isPaceSport ? 'dataMax' : 'dataMin'}
                      dot={({ cx, cy, index, payload }: { cx?: number; cy?: number; index?: number; payload?: { isCurrent: boolean }; [key: string]: unknown }) => {
                        const isCurrent = payload?.isCurrent
                        return (
                          <circle
                            key={index}
                            cx={cx} cy={cy}
                            r={isCurrent ? 5 : 3}
                            fill={isCurrent ? (sa.pr_rank === 1 ? '#f59e0b' : sportColor) : (isLight ? '#d1d5db' : '#4b5563')}
                            stroke={isCurrent ? (isLight ? '#fff' : '#111') : 'none'}
                            strokeWidth={isCurrent ? 2 : 0}
                          />
                        )
                      }}
                      label={((props: unknown) => {
                        const { x, y, index, value } = props as { x: number; y: number; index: number; value: number }
                        const isCurrent = index != null ? chartData[index]?.isCurrent : false
                        return (
                          <text
                            key={index}
                            x={x}
                            y={y - 8}
                            textAnchor="middle"
                            fontSize={9}
                            fontFamily="ui-monospace, monospace"
                            fontWeight={isCurrent ? 'bold' : 'normal'}
                            fill={isCurrent
                              ? (sa.pr_rank === 1 ? '#f59e0b' : sportColor)
                              : colors.tickFill}
                          >
                            {fmtPaceValue(value)}
                          </text>
                        )
                      }) as any}
                      activeDot={false}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
          </ChartPanel>
        )
      })()}

      {/* ── Similar Activities ─────────────────────── */}
      {similarActivities && similarActivities.length > 0 && (
        <ChartPanel title="Similar activities" accent={sportAccent} glow={false}>
          <div className={clsx('divide-y', isLight ? 'divide-gray-100' : 'divide-surface-700')}>
            {similarActivities.map((sa: Record<string, unknown>) => (
              <Link
                key={sa.id as number}
                to={`/activities/${sa.id}`}
                className={clsx('flex items-center gap-3 py-2.5 px-1 -mx-1 rounded-lg transition-colors group', isLight ? 'hover:bg-gray-50' : 'hover:bg-surface-700')}
              >
                <span
                  className="w-2 h-2 rounded-full flex-shrink-0"
                  style={{ backgroundColor: getSportColor(sa.sport_type as string) }}
                />
                <div className="flex-1 min-w-0">
                  <div className={clsx('text-sm truncate transition-colors', isLight ? 'text-gray-800 group-hover:text-gray-900' : 'text-gray-200 group-hover:text-white')}>
                    {String(sa.name)}
                  </div>
                  <div className="text-xs text-gray-500">
                    {sa.start_date_local ? new Date(String(sa.start_date_local)).toLocaleDateString() : ''}
                  </div>
                </div>
                <div className="flex items-center gap-4 text-xs text-gray-400 font-mono flex-shrink-0">
                  <span>{getSportCategory(sa.sport_type as string) === 'swimming' ? `${Math.round(((sa.distance_km as number) ?? 0) * 1000)} m` : `${(sa.distance_km as number)?.toFixed(1)} km`}</span>
                  {!!sa.formatted_pace && <span>{String(sa.formatted_pace)}</span>}
                  {(sa.total_elevation_gain as number) > 0 && (
                    <span className="text-green-400/70">+{Math.round(sa.total_elevation_gain as number)}m</span>
                  )}
                  <span>{String(sa.moving_time_formatted)}</span>
                </div>
              </Link>
            ))}
          </div>
        </ChartPanel>
      )}

      {/* ── Strava Segments ───────────────────────── */}
      {activity.segment_efforts && activity.segment_efforts.length > 0 && (() => {
        const efforts = activity.segment_efforts as Record<string, unknown>[]
        return (
          <details
            className={clsx('panel p-5 group', isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600')}
            open
          >
            <summary className="eyebrow cursor-pointer select-none list-none flex items-center justify-between">
              <span>Strava segments · {efforts.length}</span>
              <span className={clsx('text-[10px] transition-transform group-open:rotate-180', isLight ? 'text-gray-400' : 'text-gray-600')}>▼</span>
            </summary>
            <div className="space-y-3 mt-4">
              {efforts.map((effort, i) => {
                const segment = effort.segment as Record<string, unknown> | undefined
                const name = (effort.name as string) || (segment?.name as string) || `Segment ${i + 1}`
                const elapsed = effort.elapsed_time as number || 0
                const distance = (effort.distance as number || 0)
                const isSwimSeg = sportCategory === 'swimming'
                const distKm = distance / 1000
                const prRank = effort.pr_rank as number | null
                const avgHR = effort.average_heartrate as number | null
                const maxHR = effort.max_heartrate as number | null
                const avgCadence = effort.average_cadence as number | null
                const avgWatts = effort.average_watts as number | null
                const avgGrade = segment?.average_grade as number | null
                const city = segment?.city as string | null

                // Compute pace
                const speedMs = elapsed > 0 ? distance / elapsed : 0
                const { value: paceVal } = convertSpeed(speedMs, activity.sport_type)
                const paceStr = formatPace(paceVal, useSpeedUnit)

                return (
                  <div
                    key={i}
                    className={clsx(
                      'rounded-lg border p-3',
                      prRank === 1
                        ? (isLight ? 'border-amber-300 bg-amber-50/50' : 'border-amber-500/40 bg-amber-500/5')
                        : (isLight ? 'border-gray-200' : 'border-surface-600/60'),
                    )}
                  >
                    {/* Top row: name + badges + time */}
                    <div className="flex items-center justify-between gap-2 mb-2">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className={clsx('text-sm font-medium truncate', isLight ? 'text-gray-800' : 'text-gray-200')}>{name}</span>
                        {prRank === 1 && (
                          <span className={clsx('text-[10px] font-bold px-1.5 py-0.5 rounded-full flex-shrink-0', isLight ? 'bg-amber-100 text-amber-700' : 'bg-amber-500/15 text-amber-400')}>
                            PR
                          </span>
                        )}
                        {prRank != null && prRank > 1 && prRank <= 3 && (
                          <span className={clsx('text-[10px] px-1.5 py-0.5 rounded-full flex-shrink-0', isLight ? 'bg-gray-100 text-gray-500' : 'bg-surface-700 text-gray-400')}>
                            {prRank === 2 ? '2nd' : '3rd'}
                          </span>
                        )}
                      </div>
                      <span className={clsx('text-sm font-mono font-medium flex-shrink-0', isLight ? 'text-gray-800' : 'text-gray-200')}>
                        {formatTime(elapsed)}
                      </span>
                    </div>

                    {/* Stats row */}
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
                      <span className={clsx('font-mono', isLight ? 'text-gray-600' : 'text-gray-400')}>
                        {isSwimSeg ? `${Math.round(distance)} m` : (distKm >= 1 ? `${distKm.toFixed(2)} km` : `${Math.round(distance)} m`)}
                      </span>
                      <span className={clsx('font-mono', isLight ? 'text-gray-600' : 'text-gray-400')}>
                        {paceStr} <span className="text-gray-500">{paceUnit}</span>
                      </span>
                      {avgGrade != null && avgGrade !== 0 && (
                        <span className={clsx('font-mono', avgGrade > 0 ? 'text-green-400/80' : 'text-blue-400/80')}>
                          {avgGrade > 0 ? '+' : ''}{avgGrade.toFixed(1)}%
                        </span>
                      )}
                      {avgHR != null && (
                        <span className="font-mono text-pink-400/80">
                          {Math.round(avgHR)} bpm
                          {maxHR != null && <span className="text-gray-500"> / {Math.round(maxHR)}</span>}
                        </span>
                      )}
                      {avgCadence != null && (
                        <span className="font-mono text-blue-400/80">
                          {Math.round(avgCadence * 2)} spm
                        </span>
                      )}
                      {avgWatts != null && (
                        <span className="font-mono text-purple-400/80">
                          {Math.round(avgWatts)} W
                        </span>
                      )}
                      {city && (
                        <span className="text-gray-500">{city}</span>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </details>
        )
      })()}
    </div>
  )
}

// ────────────────────────────────────────────────────────
// MetaPill — compact header-level metadata chip
// ────────────────────────────────────────────────────────

function MetaPill({
  icon,
  text,
  suffix,
  tone = 'neutral',
}: {
  icon: ReactNode
  text: string
  suffix?: string
  tone?: 'neutral' | 'amber' | 'green'
}) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const palette =
    tone === 'amber'
      ? (isLight ? 'bg-amber-50 text-amber-700 border-amber-200' : 'bg-amber-500/10 text-amber-400 border-amber-500/30')
      : tone === 'green'
        ? (isLight ? 'bg-green-50 text-green-700 border-green-200' : 'bg-green-500/10 text-green-400 border-green-500/30')
        : (isLight ? 'bg-gray-50 text-gray-600 border-gray-200' : 'bg-surface-700/60 text-gray-400 border-surface-600')
  return (
    <span className={clsx(
      'inline-flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-full border font-medium',
      palette,
    )}>
      <span className="opacity-70 shrink-0" aria-hidden="true">{icon}</span>
      <span>{text}</span>
      {suffix && <span className="opacity-50 tabular-nums">· {suffix}</span>}
    </span>
  )
}
