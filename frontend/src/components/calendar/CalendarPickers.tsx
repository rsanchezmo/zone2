import { useState, useRef } from 'react'
import {
  startOfMonth, endOfMonth, eachDayOfInterval, format, addMonths, subMonths, isSameMonth,
  startOfWeek, endOfWeek, isSameWeek, parseISO,
} from 'date-fns'
import clsx from 'clsx'
import { WEEKDAYS_MIN } from '../../constants/weekdays'
import { useTheme } from '../../hooks/useTheme'
import { useClickOutside } from '../../hooks/useClickOutside'

/* ── Week Picker ──────────────────────────────────── */
export function WeekPicker({ currentWeekStart, onSelect, onClose }: {
  currentWeekStart: string
  onSelect: (weekStart: string) => void
  onClose: () => void
}) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const ref = useRef<HTMLDivElement>(null)
  const [viewMonth, setViewMonth] = useState(() => {
    try { return startOfMonth(parseISO(currentWeekStart)) }
    catch { return startOfMonth(new Date()) }
  })

  useClickOutside(ref, true, onClose)

  const mStart = startOfMonth(viewMonth)
  const mEnd = endOfMonth(viewMonth)
  const calStart = startOfWeek(mStart, { weekStartsOn: 1 })
  const calEnd = endOfWeek(mEnd, { weekStartsOn: 1 })
  const days = eachDayOfInterval({ start: calStart, end: calEnd })

  const selectedMonday = (() => {
    try { return parseISO(currentWeekStart) }
    catch { return startOfWeek(new Date(), { weekStartsOn: 1 }) }
  })()

  return (
    <div ref={ref} className={clsx(
      'absolute top-full mt-1 z-50 rounded-xl p-3 shadow-xl w-[260px] border',
      isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600',
    )}>
      <div className="flex items-center justify-between mb-2">
        <button onClick={() => setViewMonth(m => subMonths(m, 1))} className={clsx('px-1', isLight ? 'text-gray-400 hover:text-gray-700' : 'text-gray-400 hover:text-gray-100')}>&larr;</button>
        <span className={clsx('text-xs font-medium', isLight ? 'text-gray-700' : 'text-gray-300')}>{format(viewMonth, 'MMMM yyyy')}</span>
        <button onClick={() => setViewMonth(m => addMonths(m, 1))} className={clsx('px-1', isLight ? 'text-gray-400 hover:text-gray-700' : 'text-gray-400 hover:text-gray-100')}>&rarr;</button>
      </div>
      <div className="grid grid-cols-7 text-center mb-1 gap-px">
        {WEEKDAYS_MIN.map(d => <span key={d} className="eyebrow text-[9px]">{d}</span>)}
      </div>
      <div className="grid grid-cols-7 gap-px">
        {days.map(day => {
          const monday = startOfWeek(day, { weekStartsOn: 1 })
          const isSelected = isSameWeek(day, selectedMonday, { weekStartsOn: 1 })
          const isCurrent = isSameWeek(day, new Date(), { weekStartsOn: 1 })
          const inMonth = isSameMonth(day, viewMonth)
          return (
            <button
              key={day.toISOString()}
              onClick={() => {
                onSelect(format(monday, 'yyyy-MM-dd'))
                onClose()
              }}
              className={clsx(
                'text-[11px] py-1 rounded transition-colors',
                isSelected
                  ? isLight ? 'bg-gray-900/10 text-gray-900 font-bold' : 'bg-gray-400/20 text-gray-100 font-bold'
                  : isCurrent
                    ? isLight ? 'bg-gray-100 text-gray-700' : 'bg-surface-600 text-gray-300'
                    : inMonth
                      ? isLight ? 'text-gray-600 hover:bg-gray-100' : 'text-gray-400 hover:bg-surface-700'
                      : isLight ? 'text-gray-300 hover:bg-gray-50' : 'text-gray-600 hover:bg-surface-700',
              )}
            >
              {format(day, 'd')}
            </button>
          )
        })}
      </div>
      <button
        onClick={() => {
          onSelect(format(startOfWeek(new Date(), { weekStartsOn: 1 }), 'yyyy-MM-dd'))
          onClose()
        }}
        className={clsx(
          'mt-2 w-full text-[11px] py-1 rounded transition-colors',
          isLight ? 'text-gray-500 hover:text-gray-800 bg-gray-100 hover:bg-gray-200' : 'text-gray-400 hover:text-gray-100 bg-surface-700',
        )}
      >
        This week
      </button>
    </div>
  )
}

/* ── Month Picker ─────────────────────────────────── */
const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export function MonthPicker({ current, onSelect, onClose }: {
  current: Date
  onSelect: (d: Date) => void
  onClose: () => void
}) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const ref = useRef<HTMLDivElement>(null)
  const [viewYear, setViewYear] = useState(current.getFullYear())
  const nowMonth = new Date().getMonth()
  const nowYear = new Date().getFullYear()

  useClickOutside(ref, true, onClose)

  return (
    <div ref={ref} className={clsx(
      'absolute top-full mt-1 z-50 rounded-xl p-3 shadow-xl w-[220px] border',
      isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600',
    )}>
      <div className="flex items-center justify-between mb-2">
        <button onClick={() => setViewYear(y => y - 1)} className={clsx('px-1', isLight ? 'text-gray-400 hover:text-gray-700' : 'text-gray-400 hover:text-gray-100')}>&larr;</button>
        <span className={clsx('text-xs font-medium', isLight ? 'text-gray-700' : 'text-gray-300')}>{viewYear}</span>
        <button onClick={() => setViewYear(y => y + 1)} className={clsx('px-1', isLight ? 'text-gray-400 hover:text-gray-700' : 'text-gray-400 hover:text-gray-100')}>&rarr;</button>
      </div>
      <div className="grid grid-cols-3 gap-1">
        {MONTH_NAMES.map((name, i) => {
          const isSelected = current.getFullYear() === viewYear && current.getMonth() === i
          const isCurrent = nowYear === viewYear && nowMonth === i
          return (
            <button
              key={name}
              onClick={() => { onSelect(new Date(viewYear, i, 1)); onClose() }}
              className={clsx(
                'text-[11px] py-1.5 rounded transition-colors',
                isSelected
                  ? isLight ? 'bg-gray-900/10 text-gray-900 font-bold' : 'bg-gray-400/20 text-gray-100 font-bold'
                  : isCurrent
                    ? isLight ? 'bg-gray-100 text-gray-700' : 'bg-surface-600 text-gray-300'
                    : isLight ? 'text-gray-600 hover:bg-gray-100' : 'text-gray-400 hover:bg-surface-700',
              )}
            >
              {name}
            </button>
          )
        })}
      </div>
      <button
        onClick={() => { onSelect(new Date(nowYear, nowMonth, 1)); onClose() }}
        className={clsx(
          'mt-2 w-full text-[11px] py-1 rounded transition-colors',
          isLight ? 'text-gray-500 hover:text-gray-800 bg-gray-100 hover:bg-gray-200' : 'text-gray-400 hover:text-gray-100 bg-surface-700',
        )}
      >
        This month
      </button>
    </div>
  )
}
