import { useState, useEffect, useRef } from 'react'
import { NavLink } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useSyncStatus, useTriggerSync, useBackfillStreams } from '../../api/hooks'
import { useTheme } from '../../hooks/useTheme'
import clsx from 'clsx'

const NAV_ITEMS: { to: string; label: string; color: string; icon: React.ReactNode }[] = [
  { to: '/calendar', label: 'Calendar', color: '#60a5fa', icon: (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="3" width="12" height="11" rx="1.5" /><path d="M5 1v3M11 1v3M2 7h12" />
    </svg>
  )},
  { to: '/activities', label: 'Activities', color: '#34d399', icon: (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 4h12M2 8h12M2 12h8" />
    </svg>
  )},
  { to: '/aggregations', label: 'World Footprint', color: '#a78bfa', icon: (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="8" cy="8" r="6" /><path d="M2 8h12M8 2c-2 2-2 10 0 12M8 2c2 2 2 10 0 12" />
    </svg>
  )},
  { to: '/dashboard', label: 'Year in Sport', color: '#fbbf24', icon: (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M8 1.5l2.5 5 5.5.8-4 3.9.9 5.3L8 13.8l-4.9 2.7.9-5.3-4-3.9 5.5-.8z" />
    </svg>
  )},
  { to: '/records', label: 'Personal Records', color: '#f87171', icon: (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 14V9M8 14V6M12 14V3" />
    </svg>
  )},
  { to: '/workouts', label: 'Workouts', color: '#22d3ee', icon: (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="1" y="6" width="3" height="4" rx="0.5" /><rect x="12" y="6" width="3" height="4" rx="0.5" /><rect x="4" y="4" width="3" height="8" rx="0.5" /><rect x="9" y="4" width="3" height="8" rx="0.5" /><line x1="7" y1="8" x2="9" y2="8" />
    </svg>
  )},
  { to: '/profile', label: 'Profile', color: '#94a3b8', icon: (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="8" cy="5" r="2.5" /><path d="M3 14c0-2.8 2.2-5 5-5s5 2.2 5 5" />
    </svg>
  )},
]

export default function AppShell({ children }: { children: React.ReactNode }) {
  const { data: syncStatus } = useSyncStatus()
  const triggerSync = useTriggerSync()
  const backfillStreams = useBackfillStreams()
  const { theme, toggleTheme } = useTheme()
  const [collapsed, setCollapsed] = useState(false)
  const isLight = theme === 'light'

  const qc = useQueryClient()
  const wasSyncing = useRef(false)

  // Auto-sync on session start when data is stale
  useEffect(() => {
    if (syncStatus?.needs_sync && !syncStatus?.syncing && !triggerSync.isPending) {
      triggerSync.mutate({ include_streams: true })
    }
  }, [syncStatus?.needs_sync])

  // Invalidate all data queries when sync completes
  useEffect(() => {
    if (wasSyncing.current && syncStatus?.syncing === false) {
      qc.invalidateQueries({ queryKey: ['activities'] })
      qc.invalidateQueries({ queryKey: ['activities-range'] })
      qc.invalidateQueries({ queryKey: ['calendar-sessions'] })
      qc.invalidateQueries({ queryKey: ['calendar-sessions-range'] })
      qc.invalidateQueries({ queryKey: ['session-scores'] })
      qc.invalidateQueries({ queryKey: ['stats'] })
      qc.invalidateQueries({ queryKey: ['records'] })
      qc.invalidateQueries({ queryKey: ['goals'] })
    }
    wasSyncing.current = syncStatus?.syncing ?? false
  }, [syncStatus?.syncing])

  return (
    <div className="flex h-screen">
      {/* Sidebar */}
      <aside
        className={clsx(
          'shrink-0 bg-surface-800/80 backdrop-blur-sm flex flex-col transition-all duration-200 ease-in-out border-r',
          isLight ? 'border-black/10' : 'border-white/5',
          collapsed ? 'w-16' : 'w-52'
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-3 h-14">
          {!collapsed && (
            <span className="text-sm font-semibold text-gray-300 tracking-wide">
              Strava Intelligence
            </span>
          )}
          <button
            onClick={() => setCollapsed(c => !c)}
            className={clsx(
              'p-1.5 rounded-md text-gray-500 transition-colors',
              isLight ? 'hover:text-gray-700 hover:bg-black/5' : 'hover:text-gray-300 hover:bg-white/5',
              collapsed && 'mx-auto'
            )}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
              {collapsed ? (
                <path d="M4 4h8M4 8h8M4 12h8" />
              ) : (
                <path d="M10 4l-4 4 4 4" />
              )}
            </svg>
          </button>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-2 py-1 space-y-0.5">
          {NAV_ITEMS.map(item => (
            <NavLink
              key={item.to}
              to={item.to}
              title={collapsed ? item.label : undefined}
              className={({ isActive }) =>
                clsx(
                  'flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-[13px] transition-colors',
                  collapsed && 'justify-center',
                  isActive
                    ? isLight ? 'bg-black/[0.06] text-gray-900' : 'bg-white/[0.08] text-white'
                    : isLight ? 'text-gray-500 hover:text-gray-700 hover:bg-black/[0.04]' : 'text-gray-500 hover:text-gray-300 hover:bg-white/[0.04]'
                )
              }
            >
              {({ isActive }) => (
                <>
                  <span className="w-4 h-4 shrink-0" style={{ color: isActive ? item.color : undefined }}>{item.icon}</span>
                  {!collapsed && <span>{item.label}</span>}
                </>
              )}
            </NavLink>
          ))}
        </nav>

        {/* Sync section */}
        <div className={clsx('px-2 py-3 border-t space-y-2', isLight ? 'border-black/10' : 'border-white/5')}>
          {!collapsed && (
            <div className="text-[11px] text-gray-600 px-1 space-y-0.5">
              {syncStatus?.athlete_name && (
                <div className="text-gray-400 font-medium">{syncStatus.athlete_name}</div>
              )}
              <div>{syncStatus?.total_activities ?? '...'} activities</div>
            </div>
          )}
          <button
            onClick={() => triggerSync.mutate({ include_streams: true })}
            disabled={syncStatus?.syncing || triggerSync.isPending}
            title={collapsed ? (syncStatus?.syncing ? 'Syncing...' : 'Sync') : undefined}
            className={clsx(
              'w-full rounded-lg text-xs font-medium transition-colors',
              collapsed ? 'px-2 py-2' : 'px-3 py-1.5',
              syncStatus?.syncing
                ? 'bg-yellow-500/10 text-yellow-500 animate-pulse'
                : isLight
                  ? 'bg-black/[0.04] text-gray-500 hover:bg-black/[0.08] hover:text-gray-700'
                  : 'bg-white/[0.04] text-gray-500 hover:bg-white/[0.08] hover:text-gray-300'
            )}
          >
            {collapsed ? (
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="mx-auto">
                <path d="M2 8a6 6 0 0110.5-4M14 8a6 6 0 01-10.5 4" /><path d="M12.5 1v3h-3M3.5 15v-3h3" />
              </svg>
            ) : syncStatus?.syncing ? 'Syncing...' : 'Sync'}
          </button>
          <button
            onClick={() => backfillStreams.mutate()}
            disabled={syncStatus?.syncing || backfillStreams.isPending}
            title="Fetch GPS/HR streams for activities that are missing them (e.g. synced before streams were enabled)"
            className={clsx(
              'w-full rounded-lg text-xs font-medium transition-colors',
              collapsed ? 'px-2 py-2' : 'px-3 py-1.5',
              isLight
                ? 'bg-black/[0.04] text-gray-500 hover:bg-black/[0.08] hover:text-gray-700'
                : 'bg-white/[0.04] text-gray-500 hover:bg-white/[0.08] hover:text-gray-300'
            )}
          >
            {collapsed ? (
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="mx-auto">
                <path d="M8 2v9M4.5 8.5L8 12l3.5-3.5M3 14h10" />
              </svg>
            ) : 'Backfill Streams'}
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto p-6 relative">
        <button
          onClick={toggleTheme}
          className={clsx(
            'fixed top-3 right-3 z-50 p-2 rounded-lg text-gray-500 transition-colors',
            isLight ? 'hover:text-gray-700 hover:bg-black/5' : 'hover:text-gray-300 hover:bg-white/5'
          )}
          title={isLight ? 'Switch to dark mode' : 'Switch to light mode'}
        >
          {isLight ? (
            <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
              <circle cx="8" cy="8" r="3" />
              <path d="M8 1v2M8 13v2M1 8h2M13 8h2M3.05 3.05l1.41 1.41M11.54 11.54l1.41 1.41M3.05 12.95l1.41-1.41M11.54 4.46l1.41-1.41" />
            </svg>
          ) : (
            <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
              <path d="M13.5 8.5a5.5 5.5 0 01-7-7 5.5 5.5 0 107 7z" />
            </svg>
          )}
        </button>
        {children}
      </main>
    </div>
  )
}
