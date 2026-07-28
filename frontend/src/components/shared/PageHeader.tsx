import type { ReactNode } from 'react'
import clsx from 'clsx'

interface PageHeaderProps {
  title: string
  description?: string
  lastSyncedAt?: string | null
  controls?: ReactNode
  actions?: ReactNode
}

function formatSyncTime(timestamp?: string | null): string | null {
  if (!timestamp) return null
  const normalized = timestamp.includes(' ') ? timestamp.replace(' ', 'T') : timestamp
  const d = new Date(normalized)
  if (Number.isNaN(d.getTime())) return null
  return d.toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
  })
}

export default function PageHeader({
  title,
  description,
  lastSyncedAt,
  controls,
  actions,
}: PageHeaderProps) {
  const syncTime = formatSyncTime(lastSyncedAt)

  return (
    <header className="flex items-center justify-between flex-wrap gap-3">
      <div className="flex items-baseline gap-2 min-w-0 flex-wrap">
        <span className="eyebrow shrink-0">{title}</span>
        {(description || syncTime) && (
          <>
            <span className="text-[11px] text-gray-700">·</span>
            <span className="text-[11px] text-gray-500 normal-case tracking-normal font-mono">
              {description}
              {description && syncTime && <span className="mx-1.5 text-gray-700">·</span>}
              {syncTime && <>synced {syncTime}</>}
            </span>
          </>
        )}
      </div>

      {(controls || actions) && (
        <div className="flex items-center justify-end gap-2 flex-wrap">
          {controls && (
            <div className={clsx('flex items-center gap-2 flex-wrap')}>
              {controls}
            </div>
          )}
          {actions && (
            <div className={clsx('flex items-center gap-2 flex-wrap')}>
              {actions}
            </div>
          )}
        </div>
      )}
    </header>
  )
}
