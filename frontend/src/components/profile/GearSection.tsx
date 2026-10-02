import { Fragment } from 'react'
import { Link } from 'react-router-dom'
import clsx from 'clsx'
import type { GearSummary } from '../../api/hooks'
import ChartPanel from '../shared/ChartPanel'
import { getSportColor } from '../../constants/sportColors'
import { WEAR_SPENT_COLOR, shoeWear } from '../../constants/gear'
import { parseLocalDate } from '../../utils/dates'
import { useTheme } from '../../hooks/useTheme'

export default function GearSection({ gear: allGear }: { gear: GearSummary[] }) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  if (allGear.length === 0) return null
  const shoes = allGear.filter(g => g.kind === 'shoes')
  const bikes = allGear.filter(g => g.kind === 'bikes')

  return (
    <ChartPanel title="Gear" glow={false}>
      <div className="space-y-6">
        <GearTimeline items={allGear} isLight={isLight} />
        {shoes.length > 0 && (
          <GearGroup title="Shoes" items={shoes} isLight={isLight} accent={getSportColor('Run')} />
        )}
        {bikes.length > 0 && (
          <GearGroup title="Bikes" items={bikes} isLight={isLight} accent={getSportColor('Ride')} />
        )}
      </div>
    </ChartPanel>
  )
}

// ────────────────────────────────────────────────────────
// GearTimeline — when each item was in rotation, one row per
// piece of gear across a shared time axis
// ────────────────────────────────────────────────────────

function GearTimeline({ items, isLight }: { items: GearSummary[]; isLight: boolean }) {
  const dated = items.filter(g => g.first_activity && g.last_activity)
  if (dated.length < 2) return null

  const startYear = Math.min(...dated.map(g => parseLocalDate(g.first_activity!).getFullYear()))
  const endYear = Math.max(...dated.map(g => parseLocalDate(g.last_activity!).getFullYear()))
  const span = { from: new Date(startYear, 0, 1).getTime(), to: new Date(endYear + 1, 0, 1).getTime() }
  const width = span.to - span.from
  const pct = (ts: number) => ((ts - span.from) / width) * 100

  const years = Array.from({ length: endYear - startYear + 1 }, (_, i) => startYear + i)
  const heaviest = Math.max(...dated.map(g => g.distance_km), 1)
  const rows = dated.slice().sort((a, b) => (a.first_activity! < b.first_activity! ? -1 : 1))

  return (
    <div>
      <div className={clsx('text-[11px] uppercase tracking-[0.15em] mb-3', isLight ? 'text-gray-400' : 'text-gray-500')}>
        Rotation
      </div>

      <div className="grid gap-y-1" style={{ gridTemplateColumns: 'minmax(0, 140px) 1fr' }}>
        {rows.map(g => {
          const color = getSportColor(g.kind === 'bikes' ? 'Ride' : 'Run')
          const left = pct(parseLocalDate(g.first_activity!).getTime())
          const right = pct(parseLocalDate(g.last_activity!).getTime())
          return (
            <Fragment key={g.id}>
              <Link
                to={`/gear/${g.id}`}
                className={clsx(
                  // Padded below md so the row clears the 24px touch target;
                  // desktop keeps the tighter timeline rhythm.
                  'text-[11px] truncate pr-3 self-center py-1 md:py-0 transition-colors',
                  g.retired && 'opacity-60',
                  isLight ? 'text-gray-600 hover:text-gray-900' : 'text-gray-400 hover:text-gray-100',
                )}
                title={g.label}
              >
                {g.label}
              </Link>
              <Link to={`/gear/${g.id}`} className="relative h-6 md:h-5 flex items-center group">
                <div className={clsx('absolute inset-x-0 h-px', isLight ? 'bg-gray-100' : 'bg-surface-700')} aria-hidden="true" />
                <div
                  className="absolute h-2.5 rounded-full transition-all duration-200 group-hover:h-3.5"
                  style={{
                    left: `${left}%`,
                    // Single-day gear would otherwise render as a hairline.
                    width: `max(3px, ${right - left}%)`,
                    background: `linear-gradient(90deg, ${color}55, ${color})`,
                    opacity: 0.45 + 0.55 * (g.distance_km / heaviest),
                  }}
                  title={`${g.label} · ${g.distance_km.toLocaleString(undefined, { maximumFractionDigits: 0 })} km · ${g.activities} activities`}
                />
              </Link>
            </Fragment>
          )
        })}

        <div aria-hidden="true" />
        <div className={clsx('relative h-4 mt-1 text-[10px] font-mono', isLight ? 'text-gray-400' : 'text-gray-600')}>
          {years.map(year => (
            <span key={year} className="absolute top-0" style={{ left: `${pct(new Date(year, 0, 1).getTime())}%` }}>
              {years.length > 8 ? `'${String(year).slice(2)}` : year}
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}

// ────────────────────────────────────────────────────────
// GearGroup — list of gear items (shoes or bikes) from Strava
// ────────────────────────────────────────────────────────

function GearGroup({ title, items, isLight, accent }: { title: string; items: GearSummary[]; isLight: boolean; accent: string }) {
  // Shoes are gauged against their expected life; bikes against each other.
  const isShoes = items[0]?.kind === 'shoes'
  const heaviest = Math.max(...items.map(g => g.distance_km), 1)

  return (
    <div>
      <div className={clsx('text-[11px] uppercase tracking-[0.15em] mb-2 flex items-center gap-2', isLight ? 'text-gray-400' : 'text-gray-500')}>
        <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: accent }} aria-hidden="true" />
        {title}
      </div>
      <div className="space-y-1.5">
        {items.map(g => {
          const secondary = g.nickname && g.nickname !== g.name ? g.name : null
          const wear = isShoes ? shoeWear(g.distance_km) : null
          const fill = wear ? wear.fill : g.distance_km / heaviest
          return (
            <Link
              key={g.id}
              to={`/gear/${g.id}`}
              className={clsx(
                'block py-1.5 px-2 -mx-2 rounded-lg transition-colors',
                g.retired && 'opacity-50',
                isLight ? 'hover:bg-gray-50' : 'hover:bg-surface-700',
              )}
            >
              <div className="flex items-baseline gap-3">
                <div className="flex-1 min-w-0 flex items-baseline gap-2 flex-wrap">
                  <span className={clsx('text-sm font-medium truncate', isLight ? 'text-gray-900' : 'text-gray-100')}>{g.label}</span>
                  {secondary && (
                    <span className={clsx('text-[11px] truncate', isLight ? 'text-gray-500' : 'text-gray-500')}>{secondary}</span>
                  )}
                  {g.primary && (
                    <span
                      className="text-[9px] uppercase tracking-[0.15em] px-1.5 py-0.5 rounded border"
                      style={{ color: accent, borderColor: `${accent}40`, backgroundColor: `${accent}15` }}
                    >
                      Primary
                    </span>
                  )}
                  {g.retired && (
                    <span className={clsx('text-[9px] uppercase tracking-[0.15em] px-1.5 py-0.5 rounded border', isLight ? 'border-gray-300 text-gray-400' : 'border-gray-700 text-gray-500')}>Retired</span>
                  )}
                </div>
                <span className={clsx('text-sm font-mono tabular-nums shrink-0', isLight ? 'text-gray-700' : 'text-gray-300')}>
                  {g.strava_distance_km.toLocaleString(undefined, { maximumFractionDigits: 1 })}
                  <span className={clsx('ml-1 text-[11px]', isLight ? 'text-gray-400' : 'text-gray-500')}>km</span>
                </span>
              </div>

              <div className="flex items-center gap-3 mt-1.5">
                {/* Without a fixed target a lone item always fills the track. */}
                {(wear || items.length > 1) && (
                  <div className={clsx('flex-1 h-1 rounded-full overflow-hidden', isLight ? 'bg-gray-100' : 'bg-surface-700')}>
                    <div
                      className="h-full rounded-full"
                      style={{ width: `${fill * 100}%`, backgroundColor: wear?.spent ? WEAR_SPENT_COLOR : accent, opacity: 0.75 }}
                    />
                  </div>
                )}
                <span className={clsx('text-[10px] font-mono tabular-nums shrink-0', wear || items.length > 1 ? '' : 'ml-auto', isLight ? 'text-gray-400' : 'text-gray-600')}>
                  {wear ? `${wear.caption} · ` : ''}{g.activities} act
                </span>
              </div>
            </Link>
          )
        })}
      </div>
    </div>
  )
}
