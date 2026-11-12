import { useCallback, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import clsx from 'clsx'
import { useTheme } from '../hooks/useTheme'
import {
  useGarminStatus, useGarminLatest, useGarminTrends, useTriggerGarminSync, useCancelGarminSync,
} from '../api/garmin'
import PageHeader from '../components/shared/PageHeader'
import { GarminDayContext, cardValues, fmtDate, lastDays } from '../components/garmin/garmin'
import DayTimeline from '../components/garmin/DayTimeline'
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
    : 'Garmin Connect is not connected'

  const card = useMemo(() => cardValues(latest), [latest])

  // The day in the timeline, in the URL so an activity can link to its day
  const [searchParams, setSearchParams] = useSearchParams()
  const day = searchParams.get('day') ?? status?.latest_date ?? null
  const timelineRef = useRef<HTMLElement>(null)
  const showDay = useCallback((next: string) => {
    setSearchParams(prev => {
      const params = new URLSearchParams(prev)
      params.set('day', next)
      return params
    }, { replace: true })
  }, [setSearchParams])
  const openDay = useCallback((next: string) => {
    showDay(next)
    timelineRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [showDay])

  if (latestLoading || trendsLoading) return <GarminSkeleton />

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
      {status && !enabled && (
        <div className="panel p-4 flex items-center justify-between gap-3 flex-wrap text-sm">
          <span className="text-gray-400">
            {status.configured && status.client_error ? status.client_error : "Garmin Connect isn't connected."}
          </span>
          <Link to="/profile" className="text-xs font-medium text-[#06b6d4] hover:underline">Connect it on Profile</Link>
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

      {enabled && day && (
        <section ref={timelineRef} className="scroll-mt-6">
          <DayTimeline day={day} latest={status?.latest_date ?? null} onDayChange={showDay} />
        </section>
      )}

      {enabled && (
        <GarminDayContext.Provider value={openDay}>
          <MoveIqPanel />
          <WeeklyRhythm trends={rhythmTrends} days={rhythmDays} onDaysChange={setRhythmDays} loading={rhythmLoading} />
          <ReadinessSection trends={trends} days={days} card={card} />
          <SleepSection trends={trends} days={days} card={card} />
          <StressSection trends={trends} days={days} />
          <MovementSection trends={trends} days={days} />
          <BodySection trends={trends} days={days} />
        </GarminDayContext.Provider>
      )}
    </div>
  )
}
