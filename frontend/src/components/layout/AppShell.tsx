import { useState, useEffect, useRef, useLayoutEffect, useCallback } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { useQueryClient, useIsFetching } from '@tanstack/react-query'
import { useSyncStatus, useTriggerSync, useBackfillStreams } from '../../api/hooks'
import { useTheme } from '../../hooks/useTheme'
import { useToast } from '../../hooks/useToast'
import clsx from 'clsx'

const NAV_ITEMS: { to: string; label: string; color: string; icon: React.ReactNode }[] = [
  { to: '/calendar', label: 'Calendar', color: '#60a5fa', icon: (
    <svg width="22" height="22" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="3" width="12" height="11" rx="1.5" /><path d="M5 1v3M11 1v3M2 7h12" />
    </svg>
  )},
  { to: '/activities', label: 'Activities', color: '#34d399', icon: (
    <svg width="22" height="22" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 4h12M2 8h12M2 12h8" />
    </svg>
  )},
  { to: '/aggregations', label: 'Map', color: '#a78bfa', icon: (
    <svg width="22" height="22" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="8" cy="8" r="6" /><path d="M2 8h12M8 2c-2 2-2 10 0 12M8 2c2 2 2 10 0 12" />
    </svg>
  )},
  { to: '/dashboard', label: 'Year', color: '#fbbf24', icon: (
    <svg width="22" height="22" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M8 1.5l2.5 5 5.5.8-4 3.9.9 5.3L8 13.8l-4.9 2.7.9-5.3-4-3.9 5.5-.8z" />
    </svg>
  )},
  { to: '/records', label: 'Records', color: '#f87171', icon: (
    <svg width="22" height="22" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 14V9M8 14V6M12 14V3" />
    </svg>
  )},
  // { to: '/training', label: 'Training', color: '#fb923c', icon: (
  //   <svg width="22" height="22" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
  //     <path d="M2 12l3-4 3 2 4-6" /><circle cx="13" cy="3.5" r="1" />
  //   </svg>
  // )},
  { to: '/workouts', label: 'Workouts', color: '#22d3ee', icon: (
    <svg width="22" height="22" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="1" y="6" width="3" height="4" rx="0.5" /><rect x="12" y="6" width="3" height="4" rx="0.5" /><rect x="4" y="4" width="3" height="8" rx="0.5" /><rect x="9" y="4" width="3" height="8" rx="0.5" /><line x1="7" y1="8" x2="9" y2="8" />
    </svg>
  )},
  { to: '/profile', label: 'Profile', color: '#94a3b8', icon: (
    <svg width="22" height="22" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="8" cy="5" r="2.5" /><path d="M3 14c0-2.8 2.2-5 5-5s5 2.2 5 5" />
    </svg>
  )},
]

function SyncPopover({ isLight }: { isLight: boolean }) {
  const { data: syncStatus } = useSyncStatus()
  const triggerSync = useTriggerSync()
  const backfillStreams = useBackfillStreams()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    if (open) document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        className={clsx(
          'relative w-12 h-12 flex items-center justify-center rounded-xl transition-all duration-200',
          syncStatus?.syncing && 'animate-pulse',
          isLight
            ? 'text-gray-400 hover:text-gray-600 hover:bg-black/5'
            : 'text-gray-500 hover:text-gray-300 hover:bg-white/5',
        )}
        title="Sync"
      >
        <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M2 8a6 6 0 0110.5-4M14 8a6 6 0 01-10.5 4" /><path d="M12.5 1v3h-3M3.5 15v-3h3" />
        </svg>
        {syncStatus?.syncing && (
          <span className="absolute top-1 right-1 w-2 h-2 rounded-full bg-blue-400 animate-ping" />
        )}
      </button>

      {open && (
        <div className={clsx(
          'absolute left-full ml-3 top-1/2 -translate-y-1/2 w-56 rounded-xl border p-3 space-y-2 shadow-xl',
          isLight
            ? 'bg-white/90 backdrop-blur-xl border-gray-200'
            : 'bg-surface-800/90 backdrop-blur-xl border-surface-600',
        )}>
          <div className={clsx('text-[11px] space-y-0.5', isLight ? 'text-gray-500' : 'text-gray-500')}>
            {syncStatus?.athlete_name && (
              <div className={clsx('font-medium', isLight ? 'text-gray-700' : 'text-gray-300')}>{syncStatus.athlete_name}</div>
            )}
            <div>{syncStatus?.total_activities ?? '...'} activities synced</div>
          </div>
          <button
            onClick={() => triggerSync.mutate({ include_streams: true })}
            disabled={syncStatus?.syncing || triggerSync.isPending}
            className={clsx(
              'w-full rounded-lg text-xs font-medium py-1.5 transition-colors',
              syncStatus?.syncing
                ? 'bg-blue-500/10 text-blue-400 animate-pulse'
                : isLight
                  ? 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                  : 'bg-white/[0.06] text-gray-300 hover:bg-white/[0.1]',
            )}
          >
            {syncStatus?.syncing ? 'Syncing...' : 'Sync Now'}
          </button>
          <button
            onClick={() => backfillStreams.mutate()}
            disabled={syncStatus?.syncing || backfillStreams.isPending}
            title="Fetch GPS/HR streams for activities missing them"
            className={clsx(
              'w-full rounded-lg text-xs font-medium py-1.5 transition-colors',
              isLight
                ? 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                : 'bg-white/[0.06] text-gray-300 hover:bg-white/[0.1]',
            )}
          >
            Backfill Streams
          </button>
        </div>
      )}
    </div>
  )
}

function getScale(hoveredIdx: number | null, itemIdx: number): number {
  if (hoveredIdx === null) return 1
  const distance = Math.abs(hoveredIdx - itemIdx)
  if (distance === 0) return 1.35
  if (distance === 1) return 1.15
  if (distance === 2) return 1.05
  return 1
}

function DockNav({ navRef, items, location, isLight, indicatorStyle }: {
  navRef: React.RefObject<HTMLDivElement | null>
  items: typeof NAV_ITEMS
  location: { pathname: string }
  isLight: boolean
  indicatorStyle: { top: number; height: number; color: string; opacity: number }
}) {
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null)

  return (
    <div
      ref={navRef}
      className="flex flex-col items-center gap-1 relative"
      onMouseLeave={() => setHoveredIdx(null)}
    >
      {/* Sliding background indicator */}
      <div
        className="absolute left-0 rounded-xl transition-all duration-300 ease-out pointer-events-none"
        style={{
          top: indicatorStyle.top,
          height: indicatorStyle.height,
          width: '100%',
          backgroundColor: indicatorStyle.color,
          opacity: indicatorStyle.opacity ? (isLight ? 0.12 : 0.15) : 0,
          boxShadow: indicatorStyle.opacity ? `0 0 20px ${indicatorStyle.color}25` : 'none',
        }}
      />

      {items.map((item, idx) => {
        const isActive = location.pathname.startsWith(item.to)
        const scale = getScale(hoveredIdx, idx)
        const isHovered = hoveredIdx === idx
        return (
          <NavLink
            key={item.to}
            to={item.to}
            data-active={isActive}
            data-color={item.color}
            title={item.label}
            onMouseEnter={() => setHoveredIdx(idx)}
            className={clsx(
              'relative flex items-center justify-center w-12 h-12 rounded-xl group origin-center',
              !isActive && !isHovered && (isLight ? 'hover:bg-black/[0.04]' : 'hover:bg-white/[0.04]'),
            )}
            style={{
              transform: `scale(${scale})`,
              transition: 'transform 180ms cubic-bezier(0.4, 0, 0.2, 1)',
              zIndex: isHovered ? 10 : 1,
            }}
          >
            <span
              className="relative z-[1]"
              style={{
                color: isActive ? item.color : isHovered ? item.color : isLight ? '#9ca3af' : '#6b7280',
                filter: isActive ? `drop-shadow(0 0 6px ${item.color}50)` : isHovered ? `drop-shadow(0 0 4px ${item.color}40)` : 'none',
                transition: 'color 150ms, filter 150ms',
              }}
            >
              {item.icon}
            </span>

            {/* Tooltip on hover — appears to the right */}
            <span
              className={clsx(
                'absolute left-full ml-3 px-3 py-1.5 rounded-lg text-sm font-medium whitespace-nowrap',
                'pointer-events-none transition-all duration-150',
                isHovered ? 'opacity-100 translate-x-0' : 'opacity-0 -translate-x-1',
                isLight
                  ? 'bg-gray-900 text-white shadow-lg'
                  : 'bg-white text-gray-900 shadow-lg',
              )}
            >
              {item.label}
              <span
                className={clsx(
                  'absolute right-full top-1/2 -translate-y-1/2 w-0 h-0',
                  'border-t-4 border-b-4 border-r-4 border-transparent',
                  isLight ? 'border-r-gray-900' : 'border-r-white',
                )}
              />
            </span>
          </NavLink>
        )
      })}
    </div>
  )
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  const { data: syncStatus } = useSyncStatus()
  const triggerSync = useTriggerSync()
  const { theme, toggleTheme } = useTheme()
  const isLight = theme === 'light'
  const location = useLocation()
  const { toast } = useToast()

  const qc = useQueryClient()
  const isFetching = useIsFetching()
  const wasSyncing = useRef(false)

  // Sliding indicator
  const navRef = useRef<HTMLDivElement>(null)
  const [indicatorStyle, setIndicatorStyle] = useState<{ top: number; height: number; color: string; opacity: number }>({
    top: 0, height: 0, color: '#fff', opacity: 0,
  })

  const updateIndicator = useCallback(() => {
    if (!navRef.current) return
    const activeEl = navRef.current.querySelector('[data-active="true"]') as HTMLElement | null
    if (activeEl) {
      const navRect = navRef.current.getBoundingClientRect()
      const elRect = activeEl.getBoundingClientRect()
      setIndicatorStyle({
        top: elRect.top - navRect.top,
        height: elRect.height,
        color: activeEl.dataset.color || '#fff',
        opacity: 1,
      })
    } else {
      setIndicatorStyle(s => ({ ...s, opacity: 0 }))
    }
  }, [])

  useLayoutEffect(() => {
    updateIndicator()
  }, [location.pathname, updateIndicator])

  // Auto-sync on session start when data is stale
  useEffect(() => {
    if (syncStatus?.needs_sync && !syncStatus?.syncing && !triggerSync.isPending) {
      triggerSync.mutate({ include_streams: true })
    }
  }, [syncStatus?.needs_sync])

  // Invalidate ALL queries when sync completes so every page gets fresh data
  useEffect(() => {
    if (wasSyncing.current && syncStatus?.syncing === false) {
      qc.invalidateQueries()
      toast(`Synced ${syncStatus.total_activities ?? ''} activities`, 'success')
    }
    wasSyncing.current = syncStatus?.syncing ?? false
  }, [syncStatus?.syncing])

  // Derive active color for ambient effects
  const activeItem = NAV_ITEMS.find(item => location.pathname.startsWith(item.to))
  const activeColor = activeItem?.color ?? '#60a5fa'

  return (
    <div className="min-h-screen">
      {/* Global loading bar */}
      {isFetching > 0 && (
        <div className="fixed top-0 left-0 right-0 z-[60] h-[2px]">
          <div
            className="h-full animate-loading-bar"
            style={{ background: `linear-gradient(90deg, transparent, ${activeColor}, transparent)` }}
          />
        </div>
      )}

      {/* Main content — full width with left padding for dock */}
      <main className="min-h-screen p-6">
        {children}
      </main>

      {/* Floating vertical dock — left side, vertically centered */}
      <div className="fixed left-3 top-1/2 -translate-y-1/2 z-50">
        <div
          className={clsx(
            'flex flex-col items-center py-3 px-2 rounded-2xl border shadow-2xl',
            isLight
              ? 'bg-white/80 border-gray-200/80 shadow-black/8'
              : 'bg-surface-900/70 border-white/[0.08] shadow-black/40',
            'backdrop-blur-xl backdrop-saturate-150',
          )}
        >
          {/* Nav items */}
          <DockNav
            navRef={navRef}
            items={NAV_ITEMS}
            location={location}
            isLight={isLight}
            indicatorStyle={indicatorStyle}
          />

          {/* Divider */}
          <div className={clsx('h-px w-8 my-2', isLight ? 'bg-gray-200' : 'bg-white/10')} />

          {/* Utility buttons */}
          <SyncPopover isLight={isLight} />

          <button
            onClick={toggleTheme}
            className={clsx(
              'w-12 h-12 flex items-center justify-center rounded-xl transition-all duration-200',
              isLight
                ? 'text-gray-400 hover:text-gray-600 hover:bg-black/5'
                : 'text-gray-500 hover:text-gray-300 hover:bg-white/5',
            )}
            title={isLight ? 'Dark mode' : 'Light mode'}
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
        </div>
      </div>
    </div>
  )
}
