import clsx from 'clsx'
import ChartPanel from './ChartPanel'
import { GarminIcon, PLAN_ACCENT } from './LoopPlanner'
import { useCityGarminCourses, useSavedRoutes } from '../../api/hooks'
import { coveredPct, selectionKey, type RouteSelection } from '../../hooks/useLoopPlanner'
import { useTheme } from '../../hooks/useTheme'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "2026-09-30 06:11:04" (or any timestamp starting YYYY-MM-DD) -> "30 Sep '26" */
function dayLabel(timestamp: string | null): string {
  if (!timestamp) return ''
  const [y, m, d] = timestamp.slice(0, 10).split('-')
  return `${Number(d)} ${MONTHS[Number(m) - 1]} '${y.slice(2)}`
}

/** The loops saved from the planner and the Garmin courses starting in the
 *  city, with how much of each is run; picking one draws it on the map. */
export default function RoutesPanel({ slug, accent, activeKey, onShow }: {
  slug?: string
  /** Colour of the covered share, the map's covered streets */
  accent: string
  activeKey: string | null
  onShow: (selection: RouteSelection) => void
}) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const { data: saved } = useSavedRoutes(slug)
  const { data: courses } = useCityGarminCourses(slug)

  // A saved loop sent to Garmin is listed once, as the saved loop
  const sentIds = new Set((saved ?? []).map(r => r.garmin_course_id))
  const garmin = (courses ?? []).filter(c => !sentIds.has(c.course_id))
  if (!saved?.length && !garmin.length) return null

  // cityKm: what the covered share is of (a Garmin course's part in the city)
  const rows: {
    selection: RouteSelection; name: string; km: number; cityKm: number | null; newKm: number | null; date: string; onGarmin: boolean
  }[] = [
    ...(saved ?? []).map(route => ({
      selection: { kind: 'saved' as const, route }, name: route.name, km: route.distance_km, cityKm: route.distance_km,
      newKm: route.new_km_now, date: route.created_at, onGarmin: route.garmin_course_id !== null,
    })),
    ...garmin.map(course => ({
      selection: { kind: 'garmin' as const, course }, name: course.name, km: course.distance_km, cityKm: course.city_km,
      newKm: course.new_km, date: course.created_at ?? '', onGarmin: true,
    })),
  ]

  return (
    <ChartPanel title="Routes" sublabel="loops you saved and your Garmin courses here" accent={PLAN_ACCENT}>
      <ul className={clsx('divide-y text-xs', isLight ? 'divide-gray-100' : 'divide-surface-700')}>
        {rows.map(row => {
          const key = selectionKey(row.selection)
          const pct = row.newKm === null || !row.cityKm ? null : coveredPct(row.cityKm, row.newKm)
          return (
            <li key={key}>
              <button
                onClick={() => onShow(row.selection)}
                className={clsx(
                  'w-full flex items-center gap-3 px-1 py-2 text-left rounded transition-colors',
                  key === activeKey
                    ? (isLight ? 'bg-cyan-50' : 'bg-cyan-500/10')
                    : (isLight ? 'hover:bg-gray-50' : 'hover:bg-surface-700/60'),
                )}
              >
                <span className={clsx('w-3 shrink-0', row.onGarmin ? 'text-gray-400' : 'text-transparent')}
                      title={row.onGarmin ? 'On Garmin Connect' : undefined}>
                  <GarminIcon />
                </span>
                <span className={clsx('flex-1 min-w-0 truncate', isLight ? 'text-gray-800' : 'text-gray-200')}>{row.name}</span>
                <span className="font-mono tabular-nums text-gray-500 w-14 text-right">{row.km.toFixed(1)} km</span>
                <span className="font-mono tabular-nums w-16 text-right hidden sm:inline" style={{ color: PLAN_ACCENT }}>
                  {row.newKm ? `${row.newKm.toFixed(1)} new` : ''}
                </span>
                <span className="flex items-center gap-1.5 w-24 justify-end" title={pct === null ? undefined : `${pct}% of it already run${row.cityKm !== null && row.cityKm < 0.8 * row.km ? ` (of its ${row.cityKm.toFixed(1)} km in this city)` : ''}`}>
                  {pct !== null && (
                    <>
                      <span className={clsx('h-1.5 w-12 rounded-full overflow-hidden', isLight ? 'bg-gray-200' : 'bg-surface-600')}>
                        <span className="block h-full rounded-full" style={{ width: `${pct}%`, background: accent }} />
                      </span>
                      <span className={clsx('font-mono tabular-nums w-9 text-right', pct === 100 ? 'text-emerald-400' : 'text-gray-400')}>
                        {pct}%
                      </span>
                    </>
                  )}
                </span>
                <span className="text-gray-500 w-16 text-right hidden sm:inline">{dayLabel(row.date)}</span>
              </button>
            </li>
          )
        })}
      </ul>
    </ChartPanel>
  )
}
