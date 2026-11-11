import { useState, useEffect, useRef, useCallback } from 'react'
import {
  startOfMonth, endOfMonth, eachDayOfInterval, format, addMonths, subMonths,
  startOfWeek, endOfWeek, isSameMonth, isToday, parse, isValid,
} from 'date-fns'
import clsx from 'clsx'
import { useTheme } from '../../hooks/useTheme'
import { useClickOutside } from '../../hooks/useClickOutside'
import { WEEKDAYS_MIN } from '../../constants/weekdays'

/** Format a yyyy-MM-dd string to dd/MM/yyyy for display */
function toDisplay(isoDate: string): string {
  if (!isoDate) return ''
  const [y, m, d] = isoDate.split('-')
  return `${d}/${m}/${y}`
}

/** Parse dd/MM/yyyy input to yyyy-MM-dd, returns '' if invalid */
function fromDisplay(display: string): string {
  if (!display) return ''
  const cleaned = display.replace(/[^\d/]/g, '')
  const parts = cleaned.split('/')
  if (parts.length !== 3) return ''
  const [d, m, y] = parts
  if (!d || !m || !y || y.length !== 4) return ''
  const date = parse(`${y}-${m.padStart(2, '0')}-${d.padStart(2, '0')}`, 'yyyy-MM-dd', new Date())
  if (!isValid(date)) return ''
  return format(date, 'yyyy-MM-dd')
}

interface DatePickerProps {
  value: string  // yyyy-MM-dd or ''
  onChange: (v: string) => void
  label?: string
  inputClassName?: string
}

export default function DatePicker({ value, onChange, label, inputClassName }: DatePickerProps) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const [open, setOpen] = useState(false)
  const [viewMonth, setViewMonth] = useState(() =>
    value ? new Date(value + 'T00:00:00') : new Date()
  )
  const [textInput, setTextInput] = useState(() => toDisplay(value))
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setTextInput(toDisplay(value))
  }, [value])

  useEffect(() => {
    if (value) {
      setViewMonth(new Date(value + 'T00:00:00'))
    }
  }, [value])

  useClickOutside(ref, open, () => setOpen(false))

  const handleTextChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const raw = e.target.value
    setTextInput(raw)
    if (raw.length === 10) {
      const iso = fromDisplay(raw)
      if (iso) onChange(iso)
    }
  }, [onChange])

  const handleTextBlur = useCallback(() => {
    if (!textInput) {
      onChange('')
      return
    }
    const iso = fromDisplay(textInput)
    if (iso) {
      onChange(iso)
    } else {
      setTextInput(toDisplay(value))
    }
  }, [textInput, value, onChange])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      (e.target as HTMLInputElement).blur()
    }
  }, [])

  const selectDay = useCallback((d: Date) => {
    onChange(format(d, 'yyyy-MM-dd'))
    setOpen(false)
  }, [onChange])

  const monthStart = startOfMonth(viewMonth)
  const monthEnd = endOfMonth(viewMonth)
  const calStart = startOfWeek(monthStart, { weekStartsOn: 1 })
  const calEnd = endOfWeek(monthEnd, { weekStartsOn: 1 })
  const days = eachDayOfInterval({ start: calStart, end: calEnd })
  const selectedIso = value

  return (
    <div ref={ref} className="relative">
      <div className="flex items-center gap-1.5">
        {label && <span className="eyebrow text-[9px] shrink-0">{label}</span>}
        <input
          type="text"
          placeholder="dd/mm/yyyy"
          value={textInput}
          onChange={handleTextChange}
          onBlur={handleTextBlur}
          onKeyDown={handleKeyDown}
          onFocus={() => setOpen(true)}
          className={clsx('input font-mono tabular-nums', inputClassName ?? 'w-[110px]')}
          maxLength={10}
        />
        <button
          onClick={() => setOpen(o => !o)}
          className="btn p-1.5"
          type="button"
          aria-label="Open calendar"
        >
          <svg className="w-3.5 h-3.5 text-fg-dim" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
          </svg>
        </button>
      </div>

      {open && (
        <div
          className={clsx(
            'absolute top-full mt-1 z-50 border rounded-xl p-3 shadow-xl w-[250px]',
            'bg-surface-800 border-surface-600',
          )}
        >
          {/* Year nav */}
          <div className="flex items-center justify-between mb-1">
            <button onClick={() => setViewMonth(m => new Date(m.getFullYear() - 1, m.getMonth(), 1))} className="px-1 text-[11px] text-fg-subtle hover:text-fg-strong">&larr;</button>
            <span className="text-[11px] text-gray-500">{viewMonth.getFullYear()}</span>
            <button onClick={() => setViewMonth(m => new Date(m.getFullYear() + 1, m.getMonth(), 1))} className="px-1 text-[11px] text-fg-subtle hover:text-fg-strong">&rarr;</button>
          </div>
          {/* Month nav */}
          <div className="flex items-center justify-between mb-2">
            <button onClick={() => setViewMonth(m => subMonths(m, 1))} className="px-1 text-sm text-fg-dim hover:text-fg-strong">&larr;</button>
            <span className="text-xs font-medium text-fg">{format(viewMonth, 'MMMM')}</span>
            <button onClick={() => setViewMonth(m => addMonths(m, 1))} className="px-1 text-sm text-fg-dim hover:text-fg-strong">&rarr;</button>
          </div>

          {/* Weekday headers */}
          <div className="grid grid-cols-7 gap-0.5 text-center mb-1">
            {WEEKDAYS_MIN.map(d => (
              <div key={d} className="text-[9px] py-0.5 text-fg-faint">{d}</div>
            ))}
          </div>

          {/* Day grid */}
          <div className="grid grid-cols-7 gap-0.5 text-center">
            {days.map(d => {
              const ds = format(d, 'yyyy-MM-dd')
              const inMonth = isSameMonth(d, viewMonth)
              const isSelected = ds === selectedIso
              const isTodayDate = isToday(d)
              return (
                <button
                  key={ds}
                  onClick={() => selectDay(d)}
                  className={clsx(
                    'text-[11px] py-1 rounded transition-colors',
                    !inMonth && (isLight ? 'text-gray-300' : 'text-gray-700'),
                    inMonth && !isSelected && !isTodayDate && 'text-fg-muted hover:bg-surface-700',
                    isTodayDate && !isSelected && (isLight ? 'bg-surface-700 text-gray-700' : 'bg-surface-600 text-gray-300'),
                    isSelected && (isLight ? 'bg-gray-900/10 text-gray-900 font-bold' : 'bg-gray-400/20 text-gray-100 font-bold'),
                  )}
                >
                  {format(d, 'd')}
                </button>
              )
            })}
          </div>

          {/* Quick actions */}
          <div className="flex gap-1 mt-2">
            <button
              onClick={() => { selectDay(new Date()) }}
              className="flex-1 text-[11px] py-1 rounded text-fg-muted hover:text-fg-strong bg-surface-700"
            >
              Today
            </button>
            {value && (
              <button
                onClick={() => { onChange(''); setOpen(false) }}
                className="flex-1 text-[11px] py-1 rounded text-fg-muted hover:text-fg-strong bg-surface-700"
              >
                Clear
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
