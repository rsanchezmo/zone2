import type { ReactNode } from 'react'
import type { ActivityDrift, DriftVerdict } from '../../api/hooks'
import StatusPill, { type PillTone } from '../shared/StatusPill'

const VERDICT_META: Record<DriftVerdict, { label: string; tone: PillTone }> = {
  steady: { label: 'Steady', tone: 'good' },
  drifting: { label: 'Drifting', tone: 'warn' },
  high: { label: 'High drift', tone: 'bad' },
}

function signed(v: number, digits = 0): string {
  return `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(digits)}`
}

function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 min-w-0">
      <span className="text-[10px] text-gray-500 uppercase tracking-wider">{label}</span>
      {children}
    </div>
  )
}

/** Drift figures under the heart rate chart, or why the run has none. */
export default function HeartRateDrift({ drift }: {
  drift: Exclude<ActivityDrift, { status: 'no_heart_rate' }>
}) {
  if (drift.status === 'unsteady') {
    return (
      <p className="mt-3 pt-3 border-t border-surface-600 text-[11px] text-gray-500">
        Drift not measured: the pace varied {drift.pace_cv_pct.toFixed(1)}% minute to minute (limit {drift.max_pace_cv_pct}%), as in intervals or fartlek.
      </p>
    )
  }
  if (drift.status === 'too_short') {
    return (
      <p className="mt-3 pt-3 border-t border-surface-600 text-[11px] text-gray-500">
        Drift not measured: only {drift.minutes} min left after skipping the first {drift.skipped_min} (needs {drift.min_minutes}).
      </p>
    )
  }

  const verdict = VERDICT_META[drift.verdict]
  return (
    <div className="mt-3 pt-3 border-t border-surface-600 space-y-2">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <Stat label="Drift">
          <span className="font-mono tabular-nums text-gray-100">
            <span className="text-lg font-bold">{signed(drift.drift_bpm_per_10min, 1)}</span>
            <span className="text-[11px] text-gray-400"> bpm every 10 min</span>
          </span>
          <span className="text-[10px] text-gray-500 font-mono tabular-nums">
            {signed(drift.rise_bpm)} bpm over the {drift.minutes} min measured
          </span>
        </Stat>
        <Stat label="Decoupling">
          <span className="flex items-center gap-2">
            <span className="text-lg font-bold font-mono tabular-nums text-gray-100">{drift.decoupling_pct.toFixed(1)}%</span>
            <StatusPill tone={verdict.tone}>{verdict.label}</StatusPill>
          </span>
          <span className="text-[10px] text-gray-500">under {drift.steady_below_pct}% holds steady</span>
        </Stat>
        <Stat label="Per heartbeat">
          <span className="font-mono tabular-nums text-gray-100">
            <span className="text-lg font-bold">{drift.metres_per_beat[0].toFixed(2)} → {drift.metres_per_beat[1].toFixed(2)}</span>
            <span className="text-[11px] text-gray-400"> m</span>
          </span>
          <span className="text-[10px] text-gray-500">first half → second half</span>
        </Stat>
      </div>
      <p className="text-[10px] text-gray-500">
        Measured from km {drift.start_km.toFixed(1)} to {drift.end_km.toFixed(1)}, after the first {drift.skipped_min} min, with pace adjusted for hills.
        The dashed line is the HR your pace alone explains at the start's cost; the gap above it is the drift.
      </p>
    </div>
  )
}
