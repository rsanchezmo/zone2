import { useState, useRef, useEffect } from 'react'
import { SPORT_COLORS_HEX, getSportColor } from '../../constants/sportColors'
import clsx from 'clsx'

const SORTED_SPORTS = [...Object.keys(SPORT_COLORS_HEX).sort(), 'Other']

interface Props {
  value: string
  onChange: (value: string) => void
  className?: string
  isLight?: boolean
}

export default function SportTypeCombobox({ value, onChange, className, isLight = false }: Props) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const [highlightIndex, setHighlightIndex] = useState(0)

  const filtered = search
    ? SORTED_SPORTS.filter(s => s.toLowerCase().includes(search.toLowerCase()))
    : SORTED_SPORTS

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
        setSearch('')
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  // Scroll highlighted item into view
  useEffect(() => {
    if (open && listRef.current) {
      const item = listRef.current.children[highlightIndex] as HTMLElement | undefined
      item?.scrollIntoView({ block: 'nearest' })
    }
  }, [highlightIndex, open])

  const handleSelect = (sport: string) => {
    onChange(sport)
    setOpen(false)
    setSearch('')
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!open) {
      if (e.key === 'ArrowDown' || e.key === 'Enter') {
        setOpen(true)
        e.preventDefault()
      }
      return
    }
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault()
        setHighlightIndex(i => Math.min(i + 1, filtered.length - 1))
        break
      case 'ArrowUp':
        e.preventDefault()
        setHighlightIndex(i => Math.max(i - 1, 0))
        break
      case 'Enter':
        e.preventDefault()
        if (filtered[highlightIndex]) handleSelect(filtered[highlightIndex])
        break
      case 'Escape':
        setOpen(false)
        setSearch('')
        break
    }
  }

  return (
    <div ref={containerRef} className="relative">
      <div
        className={clsx('flex items-center cursor-pointer', className)}
        style={{ color: getSportColor(value) }}
        onClick={() => {
          setOpen(true)
          setHighlightIndex(0)
          setTimeout(() => inputRef.current?.focus(), 0)
        }}
      >
        {open ? (
          <input
            ref={inputRef}
            value={search}
            onChange={e => {
              setSearch(e.target.value)
              setHighlightIndex(0)
            }}
            onKeyDown={handleKeyDown}
            placeholder="Type to search..."
            className="w-full bg-transparent outline-none placeholder-gray-500 text-sm"
            autoFocus
          />
        ) : (
          <span className="text-sm truncate">{value}</span>
        )}
        <svg className="w-3.5 h-3.5 ml-auto shrink-0 opacity-50" viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
        </svg>
      </div>

      {open && (
        <div
          ref={listRef}
          className={clsx(
            'absolute z-50 left-0 right-0 mt-1 max-h-52 overflow-y-auto rounded-lg border shadow-lg',
            isLight ? 'bg-white border-gray-200' : 'bg-surface-700 border-surface-600',
          )}
        >
          {filtered.length === 0 ? (
            <div className="px-3 py-2 text-xs text-gray-500">No matches</div>
          ) : (
            filtered.map((s, i) => (
              <div
                key={s}
                onClick={() => handleSelect(s)}
                onMouseEnter={() => setHighlightIndex(i)}
                className={clsx(
                  'px-3 py-1.5 text-sm cursor-pointer transition-colors',
                  i === highlightIndex
                    ? (isLight ? 'bg-gray-100' : 'bg-surface-600')
                    : '',
                )}
                style={{ color: getSportColor(s) }}
              >
                {s}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}
