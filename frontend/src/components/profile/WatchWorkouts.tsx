import clsx from 'clsx'
import { useSetWatchWorkouts, useWatchWorkouts } from '../../api/hooks'
import { useTheme } from '../../hooks/useTheme'
import { useToast } from '../../hooks/useToast'

/** The switch for sending planned runs to the Garmin watch; hidden without Garmin. */
export default function WatchWorkouts() {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const { toast } = useToast()
  const { data } = useWatchWorkouts()
  const setEnabled = useSetWatchWorkouts()
  if (!data?.available) return null
  const on = setEnabled.isPending ? setEnabled.variables : data.enabled

  function toggle() {
    setEnabled.mutate(!on, {
      onSuccess: d => toast(d.enabled ? 'Sending upcoming runs to your watch' : 'Removing upcoming runs from your watch', 'success'),
    })
  }

  return (
    <section>
      <div className="eyebrow mb-3">Garmin watch</div>
      <div className={clsx('rounded-lg border px-4 py-3 flex items-center justify-between gap-4', isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600')}>
        <div className="min-w-0 space-y-0.5">
          <div className="text-sm">Send planned workouts to my watch</div>
          <p className="text-[11px] text-gray-500 leading-relaxed">
            Your saved run workouts go to your Garmin library, so the watch can start them any day, and runs you plan
            from them go on Garmin's calendar on their day. Turning this off removes upcoming entries and keeps the workouts.
          </p>
        </div>
        <button
          role="switch"
          aria-checked={on}
          aria-label="Send planned workouts to my watch"
          onClick={toggle}
          disabled={setEnabled.isPending}
          className={clsx(
            'relative w-9 h-5 rounded-full shrink-0 transition-colors disabled:opacity-60',
            on ? 'bg-blue-500' : isLight ? 'bg-gray-300' : 'bg-surface-600',
          )}
        >
          <span className={clsx('absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform', on && 'translate-x-4')} />
        </button>
      </div>
    </section>
  )
}
