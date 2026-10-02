import { format, parseISO, differenceInCalendarDays } from 'date-fns'
import { Link } from 'react-router-dom'
import clsx from 'clsx'
import type { RaceEvent } from '../../api/hooks'
import { useTheme } from '../../hooks/useTheme'
import { formatDistExact } from '../../utils/formatSpeed'
import { parseLocalDate } from '../../utils/dates'
import { FlagIcon } from '../icons'

/** The next race's countdown, with the few after it alongside on desktop. */
export default function RaceCountdown({ races }: { races: RaceEvent[] | undefined }) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  if (!races || races.length === 0) return null
  const nextRace = races[0]
  const daysUntil = differenceInCalendarDays(parseLocalDate(nextRace.date), new Date())
  return (
    <Link
      to="/races"
      className={clsx(
        'panel flex items-center gap-4 px-4 py-3 transition-colors group',
        isLight ? 'bg-amber-50 border-amber-200 hover:border-amber-300' : 'bg-amber-500/5 border-amber-500/20 hover:border-amber-500/40',
      )}
      style={{ ['--card-accent' as string]: '#eab308' }}
    >
      <div
        className="flex flex-col items-center justify-center rounded-lg px-3 py-1.5 shrink-0 min-w-[58px] border"
        style={{ backgroundColor: '#eab30810', borderColor: '#eab30830' }}
      >
        {daysUntil === 0 ? (
          <div className="text-sm font-mono font-bold leading-none py-1.5" style={{ color: '#eab308' }}>
            Today
          </div>
        ) : (
          <>
            <div
              className="text-xl font-mono tabular-nums font-bold leading-none"
              style={{ color: '#eab308', letterSpacing: '-0.02em' }}
            >
              {daysUntil}
            </div>
            <div className="eyebrow mt-0.5 text-[9px]" style={{ color: '#eab308cc' }}>
              day{daysUntil !== 1 ? 's' : ''}
            </div>
          </>
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <span style={{ color: '#eab308' }}><FlagIcon size={11} /></span>
          <span className={clsx('text-sm font-semibold tracking-tight truncate', isLight ? 'text-gray-900' : 'text-gray-100')}>
            {nextRace.name}
          </span>
        </div>
        <div className="flex items-center gap-3 text-[11px] text-gray-500 flex-wrap font-mono tabular-nums">
          <span>{nextRace.sport_type}</span>
          {nextRace.distance_km != null && <span>{formatDistExact(nextRace.distance_km, nextRace.sport_type)}</span>}
          {nextRace.location && <span className="normal-case">{nextRace.location}</span>}
          <span>{format(parseISO(nextRace.date), 'MMM d, yyyy')}</span>
        </div>
      </div>
      {races.length > 1 && (
        <div className="hidden md:flex items-center gap-1 shrink-0">
          {races.slice(1, 4).map(r => {
            const d = differenceInCalendarDays(parseLocalDate(r.date), new Date())
            return (
              <div
                key={r.id}
                className={clsx(
                  'flex items-center gap-1 border rounded-lg px-2 py-0.5',
                  isLight ? 'bg-white border-amber-200' : 'bg-surface-800 border-amber-500/20',
                )}
                title={`${r.name}: ${format(parseISO(r.date), 'MMM d, yyyy')}`}
              >
                <span className="text-[11px] font-mono tabular-nums font-semibold text-amber-500">{d === 0 ? 'Today' : `${d}d`}</span>
                <span className="text-[10px] text-gray-500 truncate max-w-[72px]">{r.name}</span>
              </div>
            )
          })}
        </div>
      )}
    </Link>
  )
}
