import clsx from 'clsx'
import type { TrainingSession } from '../../api/hooks'
import { todayLocalStr } from '../../utils/dates'
import { DeviceIcon } from '../icons'

type Session = Pick<TrainingSession, 'date' | 'garmin_sync_state' | 'garmin_sync_error'>

const STATUS = {
  synced: { text: 'On your watch', className: 'text-emerald-500' },
  pending: { text: 'Updating your watch…', className: 'text-gray-500 animate-pulse' },
  failed: { text: 'Not on your watch', className: 'text-amber-500' },
} as const

/** Whether an upcoming run is on the Garmin watch. `label` adds the words
 *  (and the error) next to the icon. */
export default function WatchStatus({ session, size = 11, label = false, className }: {
  session: Session
  size?: number
  label?: boolean
  className?: string
}) {
  const state = session.garmin_sync_state
  // Past sessions keep whatever they had on the watch, so their state says nothing new
  if (!state || session.date < todayLocalStr()) return null
  const { text, className: tone } = STATUS[state]
  const detail = state === 'failed' && session.garmin_sync_error
    ? `${text}: ${session.garmin_sync_error}. Retried after the next Garmin sync.`
    : text
  return (
    <span className={clsx('inline-flex gap-1 shrink-0 min-w-0', label ? 'items-start' : 'items-center', tone, className)} title={detail}>
      <DeviceIcon size={size} className={clsx('shrink-0', label && 'mt-px')} />
      {label && <span className="text-[11px] leading-snug">{detail}</span>}
    </span>
  )
}
