import { useMemo, useState } from 'react'
import clsx from 'clsx'
import { useTheme } from '../hooks/useTheme'
import {
  useGarminStatus, useGarminLatest, useGarminTrends, useTriggerGarminSync, useCancelGarminSync,
} from '../api/hooks'
import PageHeader from '../components/shared/PageHeader'
import { cardValues, fmtDate, lastDays } from '../components/garmin/garmin'
import { GarminSkeleton } from '../components/garmin/GarminTiles'
import { TodaySection, VitalsSection } from '../components/garmin/GarminToday'
import MoveIqPanel from '../components/garmin/MoveIqPanel'
import WeeklyRhythm from '../components/garmin/WeeklyRhythm'
import ReadinessSection from '../components/garmin/ReadinessSection'
import SleepSection from '../components/garmin/SleepSection'
import StressSection from '../components/garmin/StressSection'
import MovementSection from '../components/garmin/MovementSection'
import BodySection from '../components/garmin/BodySection'

const RANGE_OPTIONS = [
  { label: '7d', days: 7 },
  { label: '30d', days: 30 },
  { label: '90d', days: 90 },
  { label: '365d', days: 365 },
] as const

export default function GarminPage() {
  const { theme } = useTheme()
  const isLight = theme === 'light'

  const [days, setDays] = useState<number>(30)
  const [rhythmDays, setRhythmDays] = useState<number>(90)
  const { data: status } = useGarminStatus()
  const { data: latest, isLoading: latestLoading } = useGarminLatest()
  // One fetch over the longer window serves both the charts and the weekly rhythm
  const { data: allTrends, isLoading: trendsLoading } = useGarminTrends(Math.max(days, rhythmDays))
  const trends = useMemo(() => lastDays(allTrends, days), [allTrends, days])
  const rhythmTrends = useMemo(() => lastDays(allTrends, rhythmDays), [allTrends, rhythmDays])
  const rhythmLoading = trendsLoading
  const triggerSync = useTriggerGarminSync()
  const cancelSync = useCancelGarminSync()

  const enabled = status?.enabled === true
  const syncing = status?.syncing === true
  const dataWindow = status?.earliest_date && status?.latest_date
    ? `${fmtDate(status.earliest_date)} to ${fmtDate(status.latest_date)}`
    : 'no stored data yet'
  const headerDescription = enabled
    ? `wellness dashboard · ${status?.total_days ?? 0} days · ${dataWindow}`
    : 'Garmin Connect is not configured'

  const card = useMemo(() => cardValues(latest), [latest])

  if (latestLoading || trendsLoading) return <GarminSkeleton isLight={isLight} />

  return (
    <div className="max-w-5xl mx-auto space-y-10 pb-12">
      <PageHeader
        title="Garmin"
        description={headerDescription}
        lastSyncedAt={status?.last_sync_at}
        controls={
          <div className="flex items-center gap-0.5" role="tablist">
            {RANGE_OPTIONS.map(opt => (
              <button key={opt.days} className="chip"
                data-active={opt.days === days}
                onClick={() => setDays(opt.days)}>
                {opt.label}
              </button>
            ))}
          </div>
        }
        actions={
          <>
          <button className="btn"
            disabled={!enabled || syncing || triggerSync.isPending}
            onClick={() => triggerSync.mutate({ full: false })}
            title="Refresh the last 14 days">
            {syncing ? 'Syncing…' : 'Sync recent'}
          </button>
          <button className="btn"
            disabled={!enabled || syncing || triggerSync.isPending}
            onClick={() => {
              if (confirm('Backfill full Garmin history? Can take 20–60 min in the background.')) {
                triggerSync.mutate({ full: true })
              }
            }}
            title="Walk history backwards until empty days">
            Backfill all
          </button>
          {syncing && (
            <button className="btn"
              disabled={cancelSync.isPending}
              onClick={() => cancelSync.mutate()}
              title="Stop the running sync — progress so far is saved">
              {cancelSync.isPending ? 'Cancelling…' : 'Cancel'}
            </button>
          )}
          </>
        }
      />

      {enabled && <TodaySection card={card} />}

      {/* ── Status banners ───────────────────────────────────────── */}
      {!enabled && (
        <div className={clsx(
          'rounded-xl border p-4 text-sm',
          isLight ? 'bg-amber-50/80 border-amber-200 text-amber-900' : 'bg-amber-500/5 border-amber-500/30 text-amber-300',
        )}>
          <div className="font-medium mb-1">Garmin Connect not configured</div>
          <div className="text-xs opacity-90">
            Set <code className="px-1 rounded bg-black/10">GARMIN_EMAIL</code> and{' '}
            <code className="px-1 rounded bg-black/10">GARMIN_PASSWORD</code> in <code className="px-1 rounded bg-black/10">.env</code>, then restart the backend.
            First login may need an MFA code in the server terminal.
          </div>
          {status?.client_error && (
            <div className="text-xs mt-2 opacity-75">Last error: {status.client_error}</div>
          )}
        </div>
      )}
      {status?.last_error && (
        <div className={clsx(
          'rounded-xl border p-3 text-xs',
          isLight ? 'bg-red-50/80 border-red-200 text-red-800' : 'bg-red-500/5 border-red-500/30 text-red-300',
        )}>
          Last sync error: {status.last_error}
        </div>
      )}

      <section className="space-y-4">
        <div className="section-head">
          <span className="eyebrow">Vitals & activity</span>
        </div>
        <VitalsSection card={card} />
      </section>

      {!enabled && (
        <div className={clsx('text-center text-xs py-12', isLight ? 'text-gray-400' : 'text-gray-600')}>
          Configure Garmin Connect to start collecting trends.
        </div>
      )}

      {enabled && (
        <>
          <MoveIqPanel />
          <WeeklyRhythm trends={rhythmTrends} days={rhythmDays} onDaysChange={setRhythmDays} loading={rhythmLoading} />
          <ReadinessSection trends={trends} days={days} card={card} />
          <SleepSection trends={trends} days={days} card={card} />
          <StressSection trends={trends} days={days} />
          <MovementSection trends={trends} days={days} />
          <BodySection trends={trends} days={days} />
        </>
      )}
    </div>
  )
}
