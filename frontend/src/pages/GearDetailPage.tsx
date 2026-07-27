import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  AreaChart, Area, BarChart, Bar, ScatterChart, Scatter, ZAxis,
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine, Cell,
} from 'recharts'
import clsx from 'clsx'

import { useGearDetail, usePolylines, type GearActivityPoint, type GearDetail, type GearExtreme } from '../api/hooks'
import { getSportColor } from '../constants/sportColors'
import { SHOE_LIFE_KM, WEAR_SPENT_COLOR, shoeWear } from '../constants/gear'
import RoutesMap from '../components/shared/RoutesMap'
import { decodeRoutes, homeBounds } from '../components/shared/routes'
import { convertSpeed, formatSpeed, formatClockDuration, formatDurationHM, getPaceUnit, isSpeedSport } from '../utils/formatSpeed'
import { parseLocalDate } from '../utils/dates'
import ChartPanel from '../components/shared/ChartPanel'
import PageHeader from '../components/shared/PageHeader'
import StatCard from '../components/shared/StatCard'
import { useTheme } from '../hooks/useTheme'
import type { ThemeColors } from '../hooks/themeContext'
import { useIsMobile } from '../hooks/useIsMobile'

const KIND_LABEL: Record<string, string> = { shoes: 'Shoes', bikes: 'Bike' }

function formatMonth(month: string): string {
  const label = parseLocalDate(`${month}-01`).toLocaleString(undefined, { month: 'short' })
  return `${label} '${month.slice(2, 4)}`
}

function formatDay(date: string): string {
  return parseLocalDate(date).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

// Month strides that keep tick labels on a recognisable rhythm — a stride that
// divides 12 repeats the same months every year.
const TICK_STRIDES = [1, 2, 3, 4, 6, 12, 24, 36, 60]

const SHORT_SPAN_MS = 1000 * 60 * 60 * 24 * 120

/** Tick label that drops to day precision once the domain is a few months. */
function timeTickLabel(ts: number, spanMs: number): string {
  return new Date(ts).toLocaleDateString(
    undefined,
    spanMs < SHORT_SPAN_MS ? { day: 'numeric', month: 'short' } : { month: 'short', year: '2-digit' },
  )
}

/** Month-aligned ticks across a timestamp domain. Left to itself Recharts
 *  derives one tick per datum, which collides for same-day activities. */
function timeAxisTicks(from: number, to: number, count: number): number[] {
  if (!(to > from)) return [from]

  const start = new Date(from)
  const end = new Date(to)
  const months = (end.getFullYear() - start.getFullYear()) * 12 + end.getMonth() - start.getMonth() + 1
  const raw = Math.ceil(months / count)
  const stride = TICK_STRIDES.find(s => s >= raw) ?? raw

  const ticks: number[] = []
  const cursor = new Date(start.getFullYear(), start.getMonth(), 1)
  while (cursor.getTime() <= to) {
    if (cursor.getTime() >= from) ticks.push(cursor.getTime())
    cursor.setMonth(cursor.getMonth() + stride)
  }
  // A span shorter than a month can clear every boundary — label the ends.
  return ticks.length > 1 ? ticks : [from, to]
}

export default function GearDetailPage() {
  const { gearId } = useParams<{ gearId: string }>()
  const { theme, colors } = useTheme()
  const isLight = theme === 'light'
  const isMobile = useIsMobile()
  const { data, isLoading, isError } = useGearDetail(gearId)

  const dominantSport = data?.sport_mix[0]?.sport_type ?? 'Run'
  const accent = getSportColor(dominantSport)

  if (isLoading) {
    return (
      <div className="max-w-5xl mx-auto space-y-6 pb-12">
        <PageHeader title="Gear" />
        <div className={clsx('panel p-6 animate-pulse h-32', isLight ? 'bg-white' : 'bg-surface-800')} />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {Array.from({ length: 8 }).map((_, i) => <StatCard key={i} label="" value="" loading />)}
        </div>
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="max-w-5xl mx-auto space-y-6 pb-12">
        <PageHeader title="Gear" />
        <div className={clsx('panel p-10 text-center text-sm', isLight ? 'bg-white text-gray-500' : 'bg-surface-800 text-gray-500')}>
          Could not load this gear item.
          <Link to="/profile" className="ml-2 underline" style={{ color: accent }}>Back to profile</Link>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-5xl mx-auto space-y-6 pb-12">
      <PageHeader
        title="Gear"
        description={KIND_LABEL[data.gear.kind]?.toLowerCase()}
        actions={
          <Link
            to={`/activities?gear_id=${encodeURIComponent(data.gear.id)}`}
            className="btn"
            style={{ borderColor: `${accent}55`, color: accent }}
          >
            {data.gear.activities} activities →
          </Link>
        }
      />

      <GearHero data={data} accent={accent} isLight={isLight} />

      {data.totals && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 stagger-children">
          <StatCard label="Distance" value={data.gear.distance_km.toLocaleString(undefined, { maximumFractionDigits: 0 })} unit="km" accent={accent} />
          <StatCard label="Moving time" value={formatDurationHM(data.gear.moving_time_s)} />
          <StatCard label="Elevation" value={data.gear.elevation_m.toLocaleString()} unit="m" />
          <StatCard label="Activities" value={data.gear.activities} sublabel={data.totals.days_per_activity ? `one every ${data.totals.days_per_activity} days` : undefined} />
          <StatCard
            label="Avg pace"
            value={data.totals.avg_speed_ms ? formatSpeed(data.totals.avg_speed_ms, dominantSport) : '—'}
            sublabel="distance ÷ moving time"
          />
          <StatCard label="Avg HR" value={data.totals.avg_heartrate ?? '—'} unit={data.totals.avg_heartrate ? 'bpm' : undefined} />
          <StatCard label="Avg activity" value={data.totals.avg_distance_km.toFixed(1)} unit="km" />
          <StatCard label="PRs" value={data.totals.prs} sublabel={`${data.totals.achievements.toLocaleString()} achievements`} accent={data.totals.prs > 0 ? accent : undefined} />
        </div>
      )}

      <RouteMapPanel gearId={data.gear.id} accent={accent} isLight={isLight} />

      {data.activities.length > 0 && (
        <CumulativePanel data={data} accent={accent} colors={colors} isMobile={isMobile} />
      )}

      {data.monthly.length > 1 && (
        <MonthlyPanel data={data} accent={accent} colors={colors} isLight={isLight} isMobile={isMobile} />
      )}

      {data.activities.length > 2 && (
        <PacePanel data={data} accent={accent} colors={colors} isLight={isLight} isMobile={isMobile} />
      )}

      {data.best_efforts.length > 0 && (
        <BestEffortsPanel data={data} accent={accent} isLight={isLight} />
      )}

      <ExtremesRow data={data} accent={accent} isLight={isLight} dominantSport={dominantSport} />
    </div>
  )
}

// ────────────────────────────────────────────────────────
// Hero — identity, badges and how far this pair got relative
// to the athlete's other gear of the same kind
// ────────────────────────────────────────────────────────

function GearHero({ data, accent, isLight }: { data: GearDetail; accent: string; isLight: boolean }) {
  const { gear, peers } = data
  // Shoes wear out against a fixed budget; a bike only makes sense next to the
  // rest of the collection.
  const isShoes = gear.kind === 'shoes'
  const best = Math.max(gear.distance_km, ...peers.map(p => p.distance_km), 1)
  const wear = isShoes ? shoeWear(gear.distance_km) : null
  const fill = wear ? wear.fill : gear.distance_km / best
  const leader = peers.find(p => p.distance_km === best)
  // Strava keeps counting distance the local cache may not have (history that
  // predates the first sync), so only surface the gap when it's material.
  const untracked = gear.strava_distance_km - gear.distance_km

  return (
    <section
      className={clsx('panel chart-card p-5 md:p-6', isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600')}
      style={{ ['--card-accent' as string]: accent }}
    >
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className={clsx('text-2xl font-bold tracking-tight truncate', isLight ? 'text-gray-900' : 'text-gray-50')}>
              {gear.label}
            </h1>
            {gear.primary && (
              <span className="text-[9px] uppercase tracking-[0.15em] px-1.5 py-0.5 rounded border"
                style={{ color: accent, borderColor: `${accent}40`, backgroundColor: `${accent}15` }}>
                Primary
              </span>
            )}
            {gear.retired && (
              <span className={clsx('text-[9px] uppercase tracking-[0.15em] px-1.5 py-0.5 rounded border', isLight ? 'border-gray-300 text-gray-400' : 'border-gray-700 text-gray-500')}>
                Retired
              </span>
            )}
          </div>
          {gear.nickname && gear.name !== gear.nickname && (
            <p className={clsx('text-sm mt-1', isLight ? 'text-gray-500' : 'text-gray-500')}>{gear.name}</p>
          )}
          {gear.first_activity && gear.last_activity && (
            <p className={clsx('text-[11px] font-mono mt-2', isLight ? 'text-gray-400' : 'text-gray-600')}>
              {formatDay(gear.first_activity)} → {formatDay(gear.last_activity)} · {gear.active_days.toLocaleString()} days
            </p>
          )}
        </div>

        <div className="text-right shrink-0">
          <div className="text-3xl md:text-4xl font-bold tabular-nums tracking-tight" style={{ color: accent }}>
            {gear.distance_km.toLocaleString(undefined, { maximumFractionDigits: 0 })}
            <span className={clsx('text-sm ml-1.5 font-medium', isLight ? 'text-gray-400' : 'text-gray-600')}>km</span>
          </div>
          {untracked >= 1 && (
            <div className={clsx('text-[11px] font-mono mt-1', isLight ? 'text-gray-400' : 'text-gray-600')}>
              {gear.strava_distance_km.toLocaleString(undefined, { maximumFractionDigits: 0 })} km on Strava
            </div>
          )}
        </div>
      </div>

      <div className="mt-5">
        <div className={clsx('h-2 rounded-full overflow-hidden', isLight ? 'bg-gray-100' : 'bg-surface-700')}>
          <div
            className="h-full rounded-full transition-[width] duration-700"
            style={{
              width: `${fill * 100}%`,
              background: wear?.spent
                ? `linear-gradient(90deg, ${accent}66, ${WEAR_SPENT_COLOR})`
                : `linear-gradient(90deg, ${accent}66, ${accent})`,
            }}
          />
        </div>
        <div className={clsx('flex justify-between items-baseline mt-1.5 text-[11px]', isLight ? 'text-gray-400' : 'text-gray-600')}>
          <span style={wear?.spent ? { color: WEAR_SPENT_COLOR } : undefined}>
            {wear
              ? wear.caption
              : fill >= 0.999 ? 'your longest-serving gear' : `${Math.round(fill * 100)}% of your longest-serving gear`}
          </span>
          {wear ? (
            <span className="font-mono">
              {gear.distance_km.toLocaleString(undefined, { maximumFractionDigits: 0 })} / {SHOE_LIFE_KM} km
            </span>
          ) : leader && (
            <Link to={`/gear/${leader.id}`} className="font-mono hover:underline">
              {leader.label} · {leader.distance_km.toLocaleString(undefined, { maximumFractionDigits: 0 })} km
            </Link>
          )}
        </div>
      </div>
    </section>
  )
}

// ────────────────────────────────────────────────────────
// Every route these shoes ran — neon overlay, no basemap
// ────────────────────────────────────────────────────────

function RouteMapPanel({ gearId, accent, isLight }: { gearId: string; accent: string; isLight: boolean }) {
  const { data, isLoading } = usePolylines(undefined, undefined, true, gearId)
  const routes = useMemo(() => decodeRoutes(data), [data])
  // Open on the home network; trips further out are still there to zoom out to.
  const fitTo = useMemo(() => homeBounds(routes), [routes])

  if (!isLoading && routes.length === 0) return null

  return (
    <ChartPanel title="Where they ran" sublabel={`${routes.length} routes`} accent={accent}>
      <RoutesMap
        routes={routes}
        fitTo={fitTo}
        loading={isLoading}
        colorFor={() => accent}
        className={clsx('h-[420px] rounded-lg overflow-hidden border', isLight ? 'border-gray-200' : 'border-surface-600')}
      />
    </ChartPanel>
  )
}

// ────────────────────────────────────────────────────────
// Cumulative distance ramp
// ────────────────────────────────────────────────────────

function CumulativePanel({ data, accent, colors, isMobile }: {
  data: GearDetail; accent: string; colors: ThemeColors; isMobile: boolean
}) {
  const chartData = useMemo(
    () => data.activities.map(a => ({ ...a, ts: parseLocalDate(a.date).getTime() })),
    [data.activities],
  )
  const span = { from: chartData[0].ts, to: chartData[chartData.length - 1].ts }

  // Only the pair immediately ahead — referencing every peer would flatten the
  // curve against the biggest one.
  const nextUp = useMemo(
    () => data.peers.filter(p => p.distance_km > data.gear.distance_km).sort((a, b) => a.distance_km - b.distance_km)[0],
    [data.peers, data.gear.distance_km],
  )

  return (
    <ChartPanel
      title="Distance accrued"
      sublabel={`${data.activities.length} activities`}
      accent={accent}
    >
      <ResponsiveContainer width="100%" height={260}>
        <AreaChart data={chartData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="gearRamp" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={accent} stopOpacity={0.32} />
              <stop offset="100%" stopColor={accent} stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke={colors.gridStroke} />
          <XAxis
            dataKey="ts"
            type="number"
            scale="time"
            domain={[span.from, span.to]}
            ticks={timeAxisTicks(span.from, span.to, isMobile ? 4 : 7)}
            tick={{ fill: colors.tickFill, fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v: number) => timeTickLabel(v, span.to - span.from)}
          />
          <YAxis
            tick={{ fill: colors.tickFillSecondary, fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            width={isMobile ? 34 : 52}
            tickFormatter={(v: number) => `${Math.round(v)}`}
          />
          <Tooltip
            contentStyle={{ backgroundColor: colors.tooltipBg, border: `1px solid ${colors.tooltipBorder}`, borderRadius: 8, fontSize: 12 }}
            labelStyle={{ color: colors.labelColor }}
            itemStyle={{ color: colors.labelColor }}
            labelFormatter={(v: unknown) => new Date(Number(v)).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })}
            formatter={(value: unknown) => [`${Number(value ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 })} km`, 'Total']}
          />
          {nextUp && (
            <ReferenceLine
              y={nextUp.distance_km}
              stroke={colors.tickFill}
              strokeDasharray="5 4"
              strokeOpacity={0.5}
              label={{
                value: `${nextUp.label} · ${Math.round(nextUp.distance_km)} km`,
                position: 'insideTopLeft',
                fill: colors.tickFill,
                fontSize: 10,
              }}
            />
          )}
          <Area type="monotone" dataKey="cumulative_km" stroke={accent} strokeWidth={2.5} fill="url(#gearRamp)" dot={false} />
        </AreaChart>
      </ResponsiveContainer>
    </ChartPanel>
  )
}

// ────────────────────────────────────────────────────────
// Monthly volume
// ────────────────────────────────────────────────────────

function MonthlyPanel({ data, accent, colors, isLight, isMobile }: {
  data: GearDetail; accent: string; colors: ThemeColors; isLight: boolean; isMobile: boolean
}) {
  const peak = Math.max(...data.monthly.map(m => m.distance_km))
  const chartData = useMemo(() => data.monthly.map(m => ({ ...m, label: formatMonth(m.month) })), [data.monthly])

  return (
    <ChartPanel
      title="Monthly volume"
      sublabel={`peak ${peak.toFixed(0)} km`}
      accent={accent}
    >
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={chartData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={colors.gridStroke} vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fill: colors.tickFill, fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            interval="equidistantPreserveStart"
            minTickGap={isMobile ? 28 : 16}
          />
          <YAxis
            tick={{ fill: colors.tickFillSecondary, fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            width={isMobile ? 30 : 46}
          />
          <Tooltip
            cursor={{ fill: isLight ? 'rgba(0,0,0,0.04)' : 'rgba(255,255,255,0.04)' }}
            contentStyle={{ backgroundColor: colors.tooltipBg, border: `1px solid ${colors.tooltipBorder}`, borderRadius: 8, fontSize: 12 }}
            labelStyle={{ color: colors.labelColor }}
            itemStyle={{ color: colors.labelColor }}
            formatter={(value: unknown, _name: unknown, entry: { payload?: GearDetail['monthly'][number] }) => [
              `${Number(value ?? 0).toFixed(1)} km · ${entry.payload?.activities ?? 0} activities`,
              '',
            ]}
          />
          <Bar dataKey="distance_km" radius={[2, 2, 0, 0]}>
            {chartData.map(m => (
              <Cell key={m.month} fill={accent} fillOpacity={0.35 + 0.65 * (peak ? m.distance_km / peak : 0)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartPanel>
  )
}

// ────────────────────────────────────────────────────────
// Pace signature — one dot per activity, sized by distance
// ────────────────────────────────────────────────────────

function PacePanel({ data, accent, colors, isLight, isMobile }: {
  data: GearDetail; accent: string; colors: ThemeColors; isLight: boolean; isMobile: boolean
}) {
  const navigate = useNavigate()
  const sports = data.sport_mix.map(s => s.sport_type)
  const [sport, setSport] = useState(sports[0])
  const active = sports.includes(sport) ? sport : sports[0]

  const useSpeed = isSpeedSport(active)
  const points = data.activities
    .filter(a => a.sport_type === active && a.speed_ms)
    .map(a => ({
      ...a,
      ts: parseLocalDate(a.date).getTime(),
      pace: convertSpeed(a.speed_ms as number, a.sport_type).value,
    }))

  if (points.length < 3) return null

  const sportColor = getSportColor(active)
  const span = { from: points[0].ts, to: points[points.length - 1].ts }

  return (
    <ChartPanel
      title={useSpeed ? 'Speed signature' : 'Pace signature'}
      sublabel={`${points.length} activities · dot size = distance`}
      accent={accent}
      toolbar={sports.length > 1 ? (
        <div className="flex items-center gap-0.5 flex-wrap">
          {sports.map(s => (
            <button key={s} className="chip" data-active={s === active} onClick={() => setSport(s)}>
              {s}
            </button>
          ))}
        </div>
      ) : undefined}
    >
      <ResponsiveContainer width="100%" height={240}>
        <ScatterChart margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={colors.gridStroke} />
          <XAxis
            dataKey="ts"
            type="number"
            scale="time"
            domain={[span.from, span.to]}
            ticks={timeAxisTicks(span.from, span.to, isMobile ? 4 : 7)}
            tick={{ fill: colors.tickFill, fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v: number) => timeTickLabel(v, span.to - span.from)}
          />
          <YAxis
            dataKey="pace"
            type="number"
            domain={['dataMin - 0.2', 'dataMax + 0.2']}
            // Pace reads best with faster at the top; speed is already that way.
            reversed={!useSpeed}
            tick={{ fill: colors.tickFillSecondary, fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            width={isMobile ? 38 : 52}
            tickFormatter={(v: number) => useSpeed
              ? v.toFixed(0)
              : `${Math.floor(v)}:${Math.round((v - Math.floor(v)) * 60).toString().padStart(2, '0')}`}
          />
          <ZAxis dataKey="distance_km" range={[14, 190]} />
          <Tooltip
            cursor={{ strokeDasharray: '3 3', stroke: colors.gridStroke }}
            content={({ active: hovered, payload }) => {
              if (!hovered || !payload?.length) return null
              const p = payload[0].payload as GearActivityPoint & { pace: number }
              return (
                <div
                  className="rounded-lg px-3 py-2 text-xs"
                  style={{ backgroundColor: colors.tooltipBg, border: `1px solid ${colors.tooltipBorder}` }}
                >
                  <div className={clsx('font-medium mb-1 max-w-[220px] truncate', isLight ? 'text-gray-900' : 'text-gray-100')}>{p.name}</div>
                  <div className="font-mono tabular-nums" style={{ color: sportColor }}>
                    {formatSpeed(p.speed_ms as number, p.sport_type)} · {p.distance_km.toFixed(1)} km
                  </div>
                  <div className={clsx('font-mono text-[11px] mt-0.5', isLight ? 'text-gray-500' : 'text-gray-500')}>
                    {formatDay(p.date)}{p.heartrate ? ` · ${p.heartrate} bpm` : ''}
                  </div>
                </div>
              )
            }}
          />
          <Scatter
            data={points}
            fill={sportColor}
            fillOpacity={0.45}
            stroke={sportColor}
            strokeOpacity={0.7}
            onClick={(p: { id?: number }) => p?.id && navigate(`/activities/${p.id}`)}
            className="cursor-pointer"
          />
        </ScatterChart>
      </ResponsiveContainer>
      <p className={clsx('text-[11px] mt-2', isLight ? 'text-gray-400' : 'text-gray-600')}>
        {useSpeed ? 'km/h' : getPaceUnit(active)} · click a dot to open the activity
      </p>
    </ChartPanel>
  )
}

// ────────────────────────────────────────────────────────
// Best efforts recorded while wearing this gear
// ────────────────────────────────────────────────────────

function BestEffortsPanel({ data, accent, isLight }: { data: GearDetail; accent: string; isLight: boolean }) {
  const allTime = data.best_efforts.filter(e => e.all_time_best).length

  return (
    <ChartPanel
      title="Best efforts in these"
      sublabel={allTime > 0 ? `${allTime} all-time best${allTime > 1 ? 's' : ''}` : undefined}
      accent={accent}
      glow={false}
    >
      <div>
        {data.best_efforts.map(effort => (
          <Link
            key={effort.distance_m}
            to={`/activities/${effort.activity_id}`}
            className={clsx('telemetry-row group -mx-2 px-2 rounded-md transition-colors', isLight ? 'hover:bg-gray-50' : 'hover:bg-surface-700/40')}
          >
            <div className="flex items-center gap-3 min-w-0 flex-1">
              <span className="font-semibold text-sm tabular-nums shrink-0 w-[86px]" style={{ color: accent }}>
                {effort.name}
              </span>
              {effort.all_time_best && (
                <span className="text-[9px] uppercase tracking-[0.15em] px-1.5 py-0.5 rounded border shrink-0"
                  style={{ color: accent, borderColor: `${accent}40`, backgroundColor: `${accent}15` }}>
                  All-time
                </span>
              )}
              <span className={clsx('text-xs truncate hidden sm:inline transition-colors', isLight ? 'text-gray-400 group-hover:text-gray-700' : 'text-gray-500 group-hover:text-gray-300')}>
                {effort.activity_name}
              </span>
            </div>
            <div className="flex items-baseline gap-4 shrink-0 tabular-nums">
              <span className={clsx('font-mono font-semibold text-sm', isLight ? 'text-gray-900' : 'text-gray-100')}>
                {formatClockDuration(effort.elapsed_time)}
              </span>
              <span className={clsx('text-[11px] font-mono hidden md:inline w-[86px] text-right', isLight ? 'text-gray-400' : 'text-gray-600')}>
                {formatDay(effort.date)}
              </span>
            </div>
          </Link>
        ))}
      </div>
    </ChartPanel>
  )
}

// ────────────────────────────────────────────────────────
// Standout activities
// ────────────────────────────────────────────────────────

function ExtremesRow({ data, accent, isLight, dominantSport }: {
  data: GearDetail; accent: string; isLight: boolean; dominantSport: string
}) {
  const cards: { label: string; extreme: GearExtreme | null | undefined; value: (e: GearExtreme) => string }[] = [
    { label: 'Longest', extreme: data.extremes.longest, value: e => `${e.distance_km.toFixed(1)} km` },
    { label: 'Fastest', extreme: data.extremes.fastest, value: e => (e.speed_ms ? formatSpeed(e.speed_ms, dominantSport) : '—') },
    { label: 'Biggest climb', extreme: data.extremes.biggest_climb, value: e => `${e.elevation_m.toLocaleString()} m` },
  ]
  const present = cards.filter(c => c.extreme)
  if (present.length === 0) return null

  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
      {present.map(({ label, extreme, value }) => (
        <Link
          key={label}
          to={`/activities/${extreme!.id}`}
          className={clsx(
            'panel p-4 group transition-colors',
            isLight ? 'bg-white border-gray-200 hover:border-gray-300' : 'bg-surface-800 border-surface-600 hover:border-surface-500',
          )}
        >
          <div className="eyebrow mb-1.5">{label}</div>
          <div className="text-xl font-bold tabular-nums tracking-tight" style={{ color: accent }}>
            {value(extreme!)}
          </div>
          <div className={clsx('text-xs mt-1 truncate transition-colors', isLight ? 'text-gray-500 group-hover:text-gray-800' : 'text-gray-500 group-hover:text-gray-300')}>
            {extreme!.name}
          </div>
          <div className={clsx('text-[11px] font-mono mt-0.5', isLight ? 'text-gray-400' : 'text-gray-600')}>
            {formatDay(extreme!.date)}
          </div>
        </Link>
      ))}
    </div>
  )
}
