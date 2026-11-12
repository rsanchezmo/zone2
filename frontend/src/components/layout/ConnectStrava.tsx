import clsx from 'clsx'
import { useConnectStrava } from '../../api/athlete'
import { errorDetail } from '../../api/client'

const STRAVA_ORANGE = '#fc4c02'

export function ConnectStravaButton({ className }: { className?: string }) {
  const connect = useConnectStrava()
  return (
    <div className={clsx('space-y-1', className)}>
      <button
        onClick={() => connect.mutate()}
        disabled={connect.isPending}
        className="w-full inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-full border px-3 py-1.5 text-[11px] uppercase tracking-[0.15em] font-semibold transition-colors hover:brightness-125 disabled:opacity-60"
        style={{ color: STRAVA_ORANGE, borderColor: `${STRAVA_ORANGE}50`, backgroundColor: `${STRAVA_ORANGE}15` }}
      >
        <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: STRAVA_ORANGE }} aria-hidden="true" />
        {connect.isPending ? 'Opening Strava…' : 'Connect Strava'}
      </button>
      {connect.isError && (
        <div className="text-[11px] text-red-400">{errorDetail(connect.error, 'Could not reach the backend')}</div>
      )}
    </div>
  )
}

/** Shown on every page until Strava is connected: nothing syncs without it. */
export function ConnectStravaBanner({ error }: { error: string | null }) {
  return (
    <div className="panel mb-6 p-4 flex flex-col sm:flex-row sm:items-center gap-3">
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-fg">Connect your Strava account</div>
        <div className="text-xs text-gray-500">
          z2 syncs your activities from Strava and keeps them on this machine.
        </div>
        {error && <div className="text-xs text-red-400 mt-1">{error}</div>}
      </div>
      <ConnectStravaButton className="shrink-0 self-start sm:self-auto" />
    </div>
  )
}
