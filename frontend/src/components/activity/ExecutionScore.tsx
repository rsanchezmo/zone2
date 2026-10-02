import { useState, type ReactNode } from 'react'
import clsx from 'clsx'
import type { ActivityScoreResponse, ScoreMetric, SegmentScore, TrainingSession } from '../../api/hooks'
import { SESSION_GOALS, type SessionGoalKey } from '../../constants/sessionGoals'
import { useTheme } from '../../hooks/useTheme'
import {
  getSportCategory, formatPace, formatClockDuration, formatDist,
} from '../../utils/formatSpeed'
import { scoreColor } from '../../utils/scoreColor'
import { SegmentSummary, type Segment } from '../shared/SegmentListBuilder'
import { getSegmentColor } from '../shared/segmentUtils'
import { MIN_STOPPED_S_SHOWN, SEG_TYPE_LABELS, STOP_COLOR } from './activityData'

/** How well the activity executed its planned session, overall and per target or segment. */
export default function ExecutionScore({ result, sportType }: { result: ActivityScoreResponse; sportType: string }) {
  const overall = result.score.overall_score
  const metrics = result.score.metrics
  const segmentScores = result.score.segment_scores
  const isSegmented = result.score.mode === 'segmented'
  const session = result.session
  const sessionSegments = session?.segments ?? undefined

  // Score metric keys, as the backend names them, to the session goal they measure
  const metricGoals: Record<string, SessionGoalKey> = {
    distance: 'distance', duration: 'duration', avg_pace: 'avg_pace', pace: 'pace_range', hr_zone: 'hr_zone',
  }
  const metricConfig: Record<string, { label: string; icon: ReactNode; color: string }> = Object.fromEntries(
    Object.entries(metricGoals).map(([metric, goal]) => {
      const { label, color, Icon } = SESSION_GOALS[goal]
      return [metric, { label, color, icon: Icon && <Icon size={11} /> }]
    }),
  )

  const formatPaceVal = (pace: number, unit: string) => {
    const isPaceUnit = unit === 'min/km' || unit === 'min/100m'
    return `${formatPace(pace, !isPaceUnit)} ${unit}`
  }

  const isSwim = getSportCategory(sportType) === 'swimming'

  const formatGoal = (key: string, m: ScoreMetric) => {
    if (key === 'distance') return formatDist(m.target as number, sportType, 1)
    if (key === 'duration') return `${m.target} ${m.unit}`
    if (key === 'avg_pace') return formatPaceVal(m.target as number, m.unit as string)
    if (key === 'pace') {
      const parts = []
      if (m.target_min != null) parts.push(formatPaceVal(m.target_min as number, m.unit as string))
      if (m.target_max != null) parts.push(formatPaceVal(m.target_max as number, m.unit as string))
      return parts.join(' \u2013 ')
    }
    if (key === 'hr_zone') return `Zone ${m.target_zone} @ ${m.target_pct}%`
    return ''
  }

  const formatActual = (key: string, m: ScoreMetric) => {
    if (key === 'distance') return formatDist(m.actual as number, sportType, 1)
    if (key === 'duration') return `${m.actual} ${m.unit}`
    if (key === 'avg_pace') return formatPaceVal(m.actual as number, m.unit as string)
    if (key === 'pace') return formatPaceVal(m.actual as number, m.unit as string)
    if (key === 'hr_zone') return `${m.actual_pct}%`
    return ''
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
      metricConfig={metricConfig}
      formatGoal={formatGoal}
      formatActual={formatActual}
      formatSegDist={formatSegDist}
      formatDetected={formatDetected}
      hasBreakdown={!!hasBreakdown}
      isSwim={isSwim}
    />
  )
}

/* Collapsible execution score section */
function ExecutionScoreCollapsible({
  overall, isSegmented, session, sessionSegments, segmentScores, metrics,
  metricConfig, formatGoal, formatActual, formatSegDist, formatDetected, hasBreakdown, isSwim,
}: {
  overall: number
  isSegmented: boolean
  session: TrainingSession | undefined
  sessionSegments: Segment[] | undefined
  segmentScores: SegmentScore[] | undefined
  metrics: Record<string, ScoreMetric> | undefined
  metricConfig: Record<string, { label: string; icon: ReactNode; color: string }>
  formatGoal: (key: string, m: ScoreMetric) => string
  formatActual: (key: string, m: ScoreMetric) => string
  formatSegDist: (km: number | null | undefined) => string
  formatDetected: (km: number | null | undefined, mins: number | null | undefined, pace?: number | null, paceUnit?: string) => string | null
  hasBreakdown: boolean
  isSwim: boolean
}) {
  const [expanded, setExpanded] = useState(!isSegmented)
  const { theme } = useTheme()
  const isLight = theme === 'light'

  return (
    <div className="panel p-4">
      {/* Header — always visible */}
      <div
        className="flex items-center justify-between cursor-pointer select-none"
        onClick={() => hasBreakdown && setExpanded(e => !e)}
      >
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-500 uppercase">Execution Score</span>
          <span className="text-2xl font-bold font-mono" style={{ color: scoreColor(overall) }}>{overall}</span>
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
                const segColor = getSegmentColor(ss.type)
                const segScore = ss.overall_score
                const isRecovery = ss.is_recovery
                const segMetrics = ss.metrics
                const typeLabel = SEG_TYPE_LABELS[ss.type] ?? ss.type
                const distLabel = formatSegDist(ss.distance_km)
                const durLabel = ss.duration_mins ? `${ss.duration_mins}'` : ''
                const repLabel = ss.rep > 0 ? ` #${ss.rep}` : ''
                const headerLabel = `${isRecovery ? 'Recovery' : typeLabel}${distLabel ? ` ${distLabel}` : ''}${durLabel ? ` ${durLabel}` : ''}${repLabel}`
                const detected = formatDetected(ss.actual_distance_km, ss.actual_duration_mins, ss.actual_pace, ss.pace_unit)
                const startKm = ss.start_km
                const endKm = ss.end_km
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
                          {ss.stopped_s >= MIN_STOPPED_S_SHOWN && (
                            <span
                              className="text-[10px] font-mono"
                              style={{ color: STOP_COLOR }}
                              title="Stopped inside this segment — excluded from its pace"
                            >
                              ⏸ {formatClockDuration(ss.stopped_s)} stopped
                            </span>
                          )}
                        </div>
                        {hasScore ? (
                          <span className="text-sm font-bold font-mono" style={{ color: scoreColor(segScore) }}>
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
                            const metricScore = m.score
                            return (
                              <div key={key} className="flex items-center gap-1.5 text-[11px]">
                                <span style={{ color: cfg.color }}>{cfg.icon}</span>
                                <span className="text-gray-500">{formatGoal(key, m)}</span>
                                <span className="text-gray-600">{'\u2192'}</span>
                                <span className={clsx('font-mono', isLight ? 'text-gray-700' : 'text-gray-300')}>{formatActual(key, m)}</span>
                                <span className="font-bold font-mono" style={{ color: scoreColor(metricScore) }}>{metricScore}</span>
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
                const s = m.score
                const cfg = metricConfig[key] ?? { label: key, icon: null, color: '#9ca3af' }
                return (
                  <div key={key} className="flex rounded-lg overflow-hidden border" style={{ borderColor: `${cfg.color}20` }}>
                    <div className="w-1 shrink-0" style={{ backgroundColor: cfg.color }} />
                    <div className="flex-1 p-3" style={{ backgroundColor: `${cfg.color}08` }}>
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-xs font-medium flex items-center gap-1.5" style={{ color: cfg.color }}>
                          <span>{cfg.icon}</span> {cfg.label}
                        </span>
                        <span className="text-sm font-bold font-mono" style={{ color: scoreColor(s) }}>{s}</span>
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
