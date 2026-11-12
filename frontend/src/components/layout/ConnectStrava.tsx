import clsx from 'clsx'
import { useConnectStrava } from '../../api/athlete'
import { errorDetail } from '../../api/client'
import HaloButton from '../shared/HaloButton'

const STRAVA_ORANGE = '#fc4c02'

export function ConnectStravaButton({ className }: { className?: string }) {
  const connect = useConnectStrava()
  return (
    <div className={clsx('space-y-1', className)}>
      <HaloButton color={STRAVA_ORANGE} className="w-full" onClick={() => connect.mutate()} disabled={connect.isPending}>
        {connect.isPending ? 'Opening Strava…' : 'Connect Strava'}
      </HaloButton>
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
