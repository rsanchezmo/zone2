import { useState } from 'react'
import { useGarminSignOut, useGarminStatus } from '../../api/garmin'
import ConnectGarminDialog from './ConnectGarminDialog'

const ABOUT = 'Sleep, HRV, readiness and body battery sync every few hours, and planned runs can go to your watch.'

/** Garmin Connect's row on Profile: whether it is connected, with Connect (a sign-in dialog) or Disconnect. */
export default function GarminConnection() {
  const { data: status } = useGarminStatus()
  const signOut = useGarminSignOut()
  const [signingIn, setSigningIn] = useState(false)
  if (!status) return null

  // Signed in before, but Garmin no longer accepts the session
  const lost = status.configured && !status.enabled
  const title = status.enabled ? 'Connected' : lost ? 'Signed out' : 'Not connected'
  const about = status.enabled && status.from_env ? 'Signed in with the Garmin account in .env.'
    : lost && status.client_error ? status.client_error : ABOUT

  return (
    <section>
      <div className="eyebrow mb-3">Garmin Connect</div>
      <div className="rounded-lg border px-4 py-3 flex items-center justify-between gap-4 bg-surface-800 border-surface-600">
        <div className="min-w-0 space-y-0.5">
          <div className="text-sm">{title}</div>
          <p className="text-[11px] text-gray-500 leading-relaxed">{about}</p>
        </div>
        {status.enabled ? (
          !status.from_env && (
            <button className="btn shrink-0" disabled={status.syncing || signOut.isPending}
              onClick={() => {
                if (confirm('Disconnect Garmin? The data already synced stays.')) signOut.mutate()
              }}>
              Disconnect
            </button>
          )
        ) : (
          <button className="btn shrink-0" onClick={() => setSigningIn(true)}>
            {lost ? 'Reconnect' : 'Connect'}
          </button>
        )}
      </div>
      {signingIn && <ConnectGarminDialog onClose={() => setSigningIn(false)} />}
    </section>
  )
}
