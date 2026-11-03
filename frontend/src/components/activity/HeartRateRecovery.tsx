import type { ReactNode } from 'react'
import clsx from 'clsx'
import type { RepRecovery } from '../../api/hooks'
import { formatPace, formatSpeed } from '../../utils/formatSpeed'
import { dropKey, formatDrop, type MeasuredHrRecovery } from './activityData'

function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 min-w-0">
      <span className="text-[10px] text-gray-500 uppercase tracking-wider">{label}</span>
      {children}
    </div>
  )
}

function RepTile({ rep, n }: { rep: RepRecovery; n: number }) {
  return (
    <div className={clsx('flex flex-col items-center gap-0.5 rounded-lg bg-surface-700/60 py-1.5 font-mono tabular-nums', !rep.jogged && 'opacity-70')}>
      <span className="text-[9px] text-gray-500">{n}{rep.jogged ? '' : ' °'}</span>
      <span className="text-[11px] text-gray-200">{formatPace(1000 / 60 / rep.speed_ms, false)}</span>
      <span className="text-[10px] text-pink-400">{rep.peak_hr ?? '—'}</span>
      <span className="text-[10px] text-gray-400">{formatDrop(rep.drop_30)} · {formatDrop(rep.drop_60)}</span>
    </div>
  )
}

/** HR drop after each rep of an interval session, under the heart rate chart. */
export default function HeartRateRecovery({ recovery }: { recovery: MeasuredHrRecovery }) {
  const key = dropKey(recovery)
  const mean = key === 'drop_60' ? recovery.drop_60_mean : recovery.drop_30_mean
  const measured = recovery.reps.filter(r => r[key] != null)
  const walked = recovery.reps.filter(r => !r.jogged).length
  const window = key === 'drop_60' ? '60 s' : '30 s'
  return (
    <div className="mt-3 pt-3 border-t border-surface-600 space-y-3">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <Stat label={`HR drop in ${window}`}>
          <span className="font-mono tabular-nums text-gray-100">
            <span className="text-lg font-bold">{formatDrop(mean == null ? null : Math.round(mean))}</span>
            <span className="text-[11px] text-gray-400"> bpm</span>
          </span>
          <span className="text-[10px] text-gray-500">average over {measured.length} of {recovery.reps.length} reps</span>
        </Stat>
        <Stat label="First → last rep">
          <span className="text-lg font-bold font-mono tabular-nums text-gray-100">
            {measured.length > 1 ? `${formatDrop(measured[0][key])} → ${formatDrop(measured[measured.length - 1][key])}` : '—'}
          </span>
          <span className="text-[10px] text-gray-500">a shrinking drop is fatigue building</span>
        </Stat>
        <Stat label="Recoveries">
          <span className="text-lg font-bold text-gray-100">{walked === 0 ? 'Jogged' : `${walked} of ${recovery.reps.length} walked`}</span>
          <span className="text-[10px] text-gray-500">jogging is {formatSpeed(recovery.jog_speed_ms, 'Run')} or faster</span>
        </Stat>
      </div>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(56px,1fr))] gap-1.5" aria-label="Pace, peak HR and HR drop after 30 and 60 s, per rep">
        {recovery.reps.map((rep, i) => <RepTile key={rep.start_km} rep={rep} n={i + 1} />)}
      </div>
      <p className="text-[10px] text-gray-500">
        Per rep: pace, peak HR, then how far HR fell 30 and 60 s after the rep ended (— when the next rep had started).
        A bigger drop is a quicker recovery. Compare sessions with the same reps and jogged recoveries: walking or standing (°) drops HR faster.
      </p>
    </div>
  )
}
