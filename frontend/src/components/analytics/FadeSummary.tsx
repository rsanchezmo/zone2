import { Link } from 'react-router-dom'
import clsx from 'clsx'
import type { Fade, FadeAnchor, FadeVerdict } from '../../api/hooks'
import { formatClockDuration } from '../../utils/formatSpeed'
import { localDateStr, parseLocalDate } from '../../utils/dates'
import StatusPill from '../shared/StatusPill'

const VERDICT_META: Record<FadeVerdict, { label: string; text: string }> = {
  holds_pace: {
    label: 'Holds pace',
    text: 'You slow down less than most runners as races get longer: endurance is your relative strength.',
  },
  typical: {
    label: 'Typical',
    text: "Your times slow with distance like most runners', so your efforts don't single out speed or endurance.",
  },
  fades: {
    label: 'Fades',
    text: 'You slow down more than most runners as races get longer: speed is your relative strength.',
  },
}

// Enough anchors to cover most of the fit's weight without listing every effort.
const SHOWN_WEIGHT = 0.8
const MAX_SHOWN = 6

function anchorDate(value: string): string {
  const day = localDateStr(value)
  const sameYear = day.slice(0, 4) === new Date().getFullYear().toString()
  return parseLocalDate(day).toLocaleDateString(undefined, {
    month: 'short', day: 'numeric', ...(sameYear ? {} : { year: 'numeric' }),
  })
}

export default function FadeSummary({ fade, labels, accent, isLight }: {
  fade: Fade
  /** Prediction label per distance in metres. */
  labels: Map<number, string>
  accent: string
  isLight: boolean
}) {
  const meta = fade.verdict ? VERDICT_META[fade.verdict] : null
  const shown: FadeAnchor[] = []
  let covered = 0
  for (const a of fade.anchors) {
    if (covered >= SHOWN_WEIGHT || shown.length >= MAX_SHOWN) break
    shown.push(a)
    covered += a.weight_share
  }

  return (
    <div className="pt-3 border-t border-dashed space-y-2" style={{ borderColor: isLight ? '#e5e7eb' : '#334155' }}>
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-baseline gap-2">
          <span className="eyebrow">Fade</span>
          <span className={clsx('text-sm font-bold font-mono tabular-nums', isLight ? 'text-gray-900' : 'text-gray-100')}>
            {fade.exponent.toFixed(3)}
          </span>
          {fade.stderr != null && (
            <span className="text-[11px] text-gray-500 font-mono tabular-nums">± {fade.stderr.toFixed(3)}</span>
          )}
          {meta && (
            <StatusPill accent={fade.verdict !== 'typical' ? accent : undefined} className="self-center">{meta.label}</StatusPill>
          )}
        </div>
        <span className="text-[10px] text-gray-500 font-mono tabular-nums">typical {fade.typical.toFixed(2)}</span>
      </div>
      <p className="text-[11px] text-gray-500">
        {meta?.text ?? 'Too few independent efforts yet to compare with the typical runner.'}
      </p>
      <div className="flex flex-wrap gap-1.5">
        {shown.map(a => (
          <Link
            key={`${a.activity_id}-${a.distance_m}`}
            to={`/activities/${a.activity_id}`}
            className={clsx(
              'text-[10px] font-mono tabular-nums px-2 py-1 rounded-md border transition-colors max-w-full truncate',
              isLight ? 'border-gray-200 text-gray-600 hover:bg-gray-100' : 'border-surface-600 text-gray-400 hover:bg-surface-700',
            )}
            title={a.activity_name}
          >
            <span className={isLight ? 'text-gray-900' : 'text-gray-200'}>
              {labels.get(a.distance_m) ?? `${a.distance_m} m`} {formatClockDuration(a.time_s)}
            </span>
            {' · '}{a.is_race && <span style={{ color: accent }}>race · </span>}
            {anchorDate(a.date)} · {Math.round(a.weight_share * 100)}%
          </Link>
        ))}
      </div>
    </div>
  )
}
