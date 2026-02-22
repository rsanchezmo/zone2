import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import { useSyncStatus, useTriggerSync, useBackfillStreams } from '../../api/hooks'
import { useTheme } from '../../hooks/useTheme'
import clsx from 'clsx'

const NAV_ITEMS = [
  { to: '/calendar', label: 'Calendar', icon: '📅' },
  { to: '/activities', label: 'Activities', icon: '🏃' },
  { to: '/aggregations', label: 'World Footprint', icon: '🌍' },
  { to: '/dashboard', label: 'Year in Sport', icon: '⚡' },
  { to: '/records', label: 'Personal Records', icon: '🏆' },
  { to: '/profile', label: 'Profile', icon: '👤' },
]

export default function AppShell({ children }: { children: React.ReactNode }) {
  const { data: syncStatus } = useSyncStatus()
  const triggerSync = useTriggerSync()
  const backfillStreams = useBackfillStreams()
  const { theme, toggleTheme } = useTheme()
  const [collapsed, setCollapsed] = useState(false)
  const isLight = theme === 'light'

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
              <span className="text-base leading-none">{item.icon}</span>
              {!collapsed && <span>{item.label}</span>}
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
            {collapsed ? '↻' : syncStatus?.syncing ? 'Syncing...' : 'Sync'}
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
            {collapsed ? '⇣' : 'Backfill Streams'}
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
