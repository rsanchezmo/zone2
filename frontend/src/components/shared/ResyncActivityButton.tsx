import clsx from 'clsx'
import { useResyncActivity } from '../../api/hooks'
import { useToast } from '../../hooks/useToast'

interface ResyncActivityButtonProps {
  activityId: number | string
  label?: string
  includeStreams?: boolean
}

export default function ResyncActivityButton({
  activityId,
  label = 'Resync',
  includeStreams = false,
}: ResyncActivityButtonProps) {
  const { toast } = useToast()
  const resync = useResyncActivity()
  const loading = resync.isPending

  async function handleClick() {
    try {
      const data = await resync.mutateAsync({ id: activityId, includeStreams })
      if (data?.status === 'already_running') {
        toast('Sync already running — try again shortly', 'info')
      } else {
        toast('Activity refreshed from Strava', 'success')
      }
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast(detail || 'Resync failed', 'error')
    }
  }

  return (
    <button
      onClick={handleClick}
      disabled={loading}
      className={clsx(
        'btn inline-flex items-center gap-1.5 !text-[10px] uppercase',
        loading && 'opacity-50',
      )}
      style={{ letterSpacing: '0.15em' }}
      aria-label={loading ? 'Resyncing' : `Resync activity from Strava`}
      title="Re-fetch this activity from Strava (e.g. to pick up a renamed activity)"
    >
      {loading ? (
        <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      ) : (
        <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M2.5 8a5.5 5.5 0 0 1 9.546-3.74M13.5 8a5.5 5.5 0 0 1-9.546 3.74" />
          <path d="M12 1.5V5h-3.5M4 14.5V11h3.5" />
        </svg>
      )}
      <span className="font-semibold">{loading ? 'Resyncing' : label}</span>
    </button>
  )
}
