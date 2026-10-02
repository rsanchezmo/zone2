import { useState } from 'react'
import clsx from 'clsx'
import {
  useBackfillStreams, type CacheCompleteness as CacheCompletenessData,
} from '../../api/hooks'
import ChartPanel from '../shared/ChartPanel'
import { useTheme } from '../../hooks/useTheme'

export default function CacheCompleteness({ completeness: cacheCompleteness, syncing }: {
  completeness: CacheCompletenessData | undefined
  syncing: boolean | undefined
}) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const backfillStreams = useBackfillStreams()
  const [showCacheDetails, setShowCacheDetails] = useState(false)
  if (!cacheCompleteness || cacheCompleteness.total === 0) return null
  const { streams, photos, detail, total } = cacheCompleteness
  const streamsPct = streams.total_expected > 0 ? (streams.complete / streams.total_expected) * 100 : 100
  const photosPct = photos.total_expected > 0 ? (photos.complete / photos.total_expected) * 100 : 100
  const detailPct = detail?.total_expected > 0 ? (detail.complete / detail.total_expected) * 100 : 100
  const allComplete = streams.missing === 0 && photos.missing === 0 && (detail?.missing ?? 0) === 0
  const missingCount = streams.missing + photos.missing + (detail?.missing ?? 0)
  return (
    <ChartPanel
      title="Cache completeness"
      glow={false}
      toolbar={
        !allComplete ? (
          <button
            onClick={() => backfillStreams.mutate()}
            disabled={backfillStreams.isPending || syncing}
            className="btn"
          >
            {backfillStreams.isPending || syncing ? 'Backfilling…' : 'Backfill missing'}
          </button>
        ) : (
          <span className="text-[10px] uppercase tracking-[0.15em] font-semibold text-green-400">Complete</span>
        )
      }
      footer={
        <div className="flex items-center justify-between">
          <span className={clsx('text-[11px]', isLight ? 'text-gray-500' : 'text-gray-500')}>
            {allComplete
              ? `All ${total.toLocaleString()} activities fully cached`
              : `${missingCount.toLocaleString()} item${missingCount !== 1 ? 's' : ''} missing · ${total.toLocaleString()} total`}
          </span>
          {!allComplete && (
            <button
              onClick={() => setShowCacheDetails(d => !d)}
              className={clsx('text-[11px] px-1 py-1 -my-1 rounded transition-colors', isLight ? 'text-gray-400 hover:text-gray-600' : 'text-gray-500 hover:text-gray-300')}
            >
              {showCacheDetails ? 'Hide details' : 'Show details'}
            </button>
          )}
        </div>
      }
    >
      <div className="space-y-3">
        {/* Streams */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <span className={clsx('text-sm', isLight ? 'text-gray-600' : 'text-gray-400')}>Streams</span>
            <span className="text-sm font-mono" style={{ color: streams.missing === 0 ? '#22c55e' : '#eab308' }}>
              {streams.complete.toLocaleString()} <span className="text-gray-500">/</span> {streams.total_expected.toLocaleString()}
            </span>
          </div>
          <div className={clsx('h-2 rounded-full overflow-hidden', isLight ? 'bg-gray-100' : 'bg-surface-700')}>
            <div
              className="h-full rounded-full transition-all"
              style={{ width: `${Math.min(streamsPct, 100)}%`, backgroundColor: streams.missing === 0 ? '#22c55e' : '#eab308' }}
            />
          </div>
        </div>
        {/* Photos */}
        {photos.total_expected > 0 && (
          <div>
            <div className="flex items-center justify-between mb-1">
              <span className={clsx('text-sm', isLight ? 'text-gray-600' : 'text-gray-400')}>Photos</span>
              <span className="text-sm font-mono" style={{ color: photos.missing === 0 ? '#22c55e' : '#eab308' }}>
                {photos.complete.toLocaleString()} <span className="text-gray-500">/</span> {photos.total_expected.toLocaleString()}
              </span>
            </div>
            <div className={clsx('h-2 rounded-full overflow-hidden', isLight ? 'bg-gray-100' : 'bg-surface-700')}>
              <div
                className="h-full rounded-full transition-all"
                style={{ width: `${Math.min(photosPct, 100)}%`, backgroundColor: photos.missing === 0 ? '#22c55e' : '#eab308' }}
              />
            </div>
          </div>
        )}
        {/* Detail */}
        {detail && detail.total_expected > 0 && (
          <div>
            <div className="flex items-center justify-between mb-1">
              <span className={clsx('text-sm', isLight ? 'text-gray-600' : 'text-gray-400')}>Detail</span>
              <span className="text-sm font-mono" style={{ color: detail.missing === 0 ? '#22c55e' : '#eab308' }}>
                {detail.complete.toLocaleString()} <span className="text-gray-500">/</span> {detail.total_expected.toLocaleString()}
              </span>
            </div>
            <div className={clsx('h-2 rounded-full overflow-hidden', isLight ? 'bg-gray-100' : 'bg-surface-700')}>
              <div
                className="h-full rounded-full transition-all"
                style={{ width: `${Math.min(detailPct, 100)}%`, backgroundColor: detail.missing === 0 ? '#22c55e' : '#eab308' }}
              />
            </div>
          </div>
        )}
      </div>
      {/* Expandable details */}
      {showCacheDetails && !allComplete && (
        <div className={clsx('mt-4 pt-4 border-t text-xs space-y-1', isLight ? 'border-gray-100' : 'border-surface-600/50')}>
          {streams.missing > 0 && (
            <div className={clsx(isLight ? 'text-gray-500' : 'text-gray-400')}>
              <span className="font-mono tabular-nums">{streams.missing}</span> activit{streams.missing !== 1 ? 'ies' : 'y'} missing streams
            </div>
          )}
          {photos.missing > 0 && (
            <div className={clsx(isLight ? 'text-gray-500' : 'text-gray-400')}>
              <span className="font-mono tabular-nums">{photos.missing}</span> activit{photos.missing !== 1 ? 'ies' : 'y'} missing photos (of {photos.total_expected} with photos)
            </div>
          )}
          {detail && detail.missing > 0 && (
            <div className={clsx(isLight ? 'text-gray-500' : 'text-gray-400')}>
              <span className="font-mono tabular-nums">{detail.missing}</span> activit{detail.missing !== 1 ? 'ies' : 'y'} missing detail (description, laps, gear, etc.)
            </div>
          )}
        </div>
      )}
    </ChartPanel>
  )
}
