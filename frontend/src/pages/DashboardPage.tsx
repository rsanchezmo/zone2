import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useYearInSport, useYears, useSportTypes, useCumulativeDistance, useGoals, useWeeklyTotals, useSyncStatus } from '../api/hooks'
import { getSportColor } from '../constants/sportColors'
import { formatSpeed, formatDist, formatDistAxis, distValue, getDistUnit } from '../utils/formatSpeed'
import { parseLocalDate, todayLocalStr } from '../utils/dates'
import { WEEKDAYS_SHORT } from '../constants/weekdays'
import StatCard from '../components/shared/StatCard'
import ExportButton from '../components/shared/ExportButton'
import ChartPanel, { LegendSwatch } from '../components/shared/ChartPanel'
import RelativeEffortChart from '../components/shared/RelativeEffortChart'
import GoalRing from '../components/shared/GoalRing'
import PageHeader from '../components/shared/PageHeader'
import {
  ComposedChart, Bar, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
  AreaChart, Area, LineChart, ReferenceLine, ReferenceArea,
} from 'recharts'
import { useTheme } from '../hooks/useTheme'
import { useIsMobile } from '../hooks/useIsMobile'
import clsx from 'clsx'

const MONTH_LABELS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

type MetricMode = 'distance' | 'activities'
type WeeklyWindow = 12 | 16 | 24 | 52

export default function DashboardPage() {
  const { theme, colors } = useTheme()
  const isLight = theme === 'light'
  const isMobile = useIsMobile()
  const { data: years } = useYears()
  const { data: sportTypes } = useSportTypes()
  const [year, setYear] = useState(new Date().getFullYear())
  const [mainSport, setMainSport] = useState('Run')
  const [weeklyTotalsWeeks, setWeeklyTotalsWeeks] = useState<WeeklyWindow>(12)
  const [monthlyMetric, setMonthlyMetric] = useState<MetricMode>('distance')

  const { data: goalsData, isFetched: goalsFetched } = useGoals(year)
  const yearlyDistanceGoal = useMemo(() => {
    if (!goalsData) return undefined
    const goal = goalsData.find(g =>
      g.metric === 'distance_km' &&
      (g.sport_type === mainSport || g.sport_type === '__all__')
    )
    if (!goal) return undefined
    const target = goal.target_value
    if (goal.period === 'weekly') return Math.round(target * 52)
    if (goal.period === 'monthly') return Math.round(target * 12)
    return target
  }, [goalsData, mainSport])

  const { data: yearData, isLoading: yearLoading, isFetching: yearFetching } = useYearInSport(year, mainSport, year - 1)
  const { data: weeklyTotalsData } = useWeeklyTotals(weeklyTotalsWeeks, mainSport)
  // Wait for goals so the series isn't fetched once without the target and again with it.
  const { data: cumulativeData } = useCumulativeDistance(year, mainSport, year - 1, yearlyDistanceGoal, { enabled: goalsFetched })
  const { data: syncStatus } = useSyncStatus()

  const comp = yearData?.comparison
  const sportColor = getSportColor(mainSport)

  function yearDelta(section: 'main_sport' | 'all_sports', key: string): number | string | null {
    if (!yearData || !comp) return null
    const c = (yearData[section] as unknown as Record<string, unknown>)[key]
    const p = (comp[section] as unknown as Record<string, unknown>)[key]
    if (c == null || c === 0) return null
    if (!p || p === 0) return 'new'
    if (typeof c !== 'number' || typeof p !== 'number') return null
    return ((c - p) / p) * 100
  }

  // ── Hero derivations ─────────────────────────────────
  const today = useMemo(() => new Date(), [])
  const todayStr = useMemo(() => todayLocalStr(), [])
  const isCurrentYear = year === today.getFullYear()
  const yearStart = useMemo(() => new Date(year, 0, 1), [year])
  const yearEnd = useMemo(() => new Date(year, 11, 31), [year])
  const daysElapsed = useMemo(() => {
    const cap = isCurrentYear ? today : yearEnd
    return Math.max(1, Math.floor((cap.getTime() - yearStart.getTime()) / 86_400_000) + 1)
  }, [today, yearStart, yearEnd, isCurrentYear])
  const daysInYear = useMemo(() => {
    return Math.round((yearEnd.getTime() - yearStart.getTime()) / 86_400_000) + 1
  }, [yearStart, yearEnd])
  const yearPace = Math.min(1, daysElapsed / daysInYear)
  const daysRemaining = Math.max(0, daysInYear - daysElapsed)

  const todayKm = useMemo(() => {
    if (!cumulativeData?.data?.length) return 0
    const points = cumulativeData.data
    for (let i = points.length - 1; i >= 0; i--) {
      if (points[i].date <= todayStr) return points[i].km
    }
    return 0
  }, [cumulativeData, todayStr])

  const goalProgress = yearlyDistanceGoal ? todayKm / yearlyDistanceGoal : 0
  const goalStatus = useMemo(() => {
    if (!yearlyDistanceGoal || !cumulativeData?.data) return null
    const rawPoints = cumulativeData.data
    if (rawPoints.length === 0) return null
    let todayPoint = null
    for (let i = rawPoints.length - 1; i >= 0; i--) {
      if (rawPoints[i].date <= todayStr) { todayPoint = rawPoints[i]; break }
    }
    if (!todayPoint || !todayPoint.target) return null
    const diff = todayPoint.km - todayPoint.target
    const pct = (diff / todayPoint.target) * 100
    if (Math.abs(pct) <= 2) return { label: 'On track', tone: 'accent' as const, pct: 0 }
    if (pct > 0) return { label: 'Above target', tone: 'positive' as const, pct }
    return { label: 'Below target', tone: 'negative' as const, pct }
  }, [cumulativeData, yearlyDistanceGoal, todayStr])

  const headerDescription = useMemo(() => {
    const scope = `${year} ${mainSport}`
    if (isCurrentYear) return `${scope} · day ${daysElapsed} of ${daysInYear} · ${daysRemaining} days left`
    return `${scope} · complete year · ${daysInYear} days`
  }, [year, mainSport, isCurrentYear, daysElapsed, daysInYear, daysRemaining])

  // ETA to goal at current pace — only meaningful while the year is still running
  const etaToGoal = useMemo(() => {
    if (!isCurrentYear || !yearlyDistanceGoal || todayKm <= 0 || todayKm >= yearlyDistanceGoal) return null
    const remainingKm = yearlyDistanceGoal - todayKm
    const avgPerDay = todayKm / daysElapsed
    if (avgPerDay <= 0) return null
    const daysToGoal = remainingKm / avgPerDay
    const eta = new Date(today.getTime() + daysToGoal * 86_400_000)
    return eta
  }, [isCurrentYear, yearlyDistanceGoal, todayKm, daysElapsed, today])

  // This-week aggregates (last entry of weeklyTotalsData)
  const thisWeek = useMemo(() => {
    if (!weeklyTotalsData?.data?.length) return null
    const last = weeklyTotalsData.data[weeklyTotalsData.data.length - 1]
    return last
  }, [weeklyTotalsData])

  // ── Chart data ───────────────────────────────────────
  const monthlyChartData = useMemo(() => {
    const distMap = yearData?.main_sport?.distance_per_month_km ?? {}
    const compDistMap = comp?.main_sport?.distance_per_month_km ?? {}
    const actMap = yearData?.main_sport?.activities_per_month ?? {}
    const compActMap = comp?.main_sport?.activities_per_month ?? {}
    return MONTH_LABELS.map((label, i) => ({
      month: label,
      distance: distMap[i + 1] ?? 0,
      prevDistance: compDistMap[i + 1] ?? 0,
      activities: actMap[i + 1] ?? 0,
      prevActivities: compActMap[i + 1] ?? 0,
    }))
  }, [yearData, comp])

  const cumulativeChartData = useMemo(() => {
    if (!cumulativeData?.data) return []
    const currentPoints = cumulativeData.data as { day: number; date: string; km: number; target?: number }[]
    const compPoints = (cumulativeData.comparison?.data ?? []) as { day: number; date: string; km: number }[]
    const compMap = new Map(compPoints.map((p) => [p.day, p.km]))
    const step = Math.max(1, Math.floor(currentPoints.length / 60))
    return currentPoints
      .filter((_, i, arr) => i % step === 0 || i === arr.length - 1 || currentPoints[i].date === todayStr)
      .map(p => {
        const d = parseLocalDate(p.date)
        return {
          day: p.day,
          date: p.date,
          label: d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
          current: p.km,
          prev: compMap.get(p.day) ?? null,
          target: p.target ?? null,
        }
      })
  }, [cumulativeData, todayStr])

  const todayLabel = useMemo(() => {
    const pt = cumulativeChartData.find(p => p.date === todayStr)
    return pt?.label
  }, [cumulativeChartData, todayStr])

  const sportBars = useMemo(() => {
    const perSport = yearData?.all_sports?.activities_per_sport ?? {}
    return Object.entries(perSport)
      .sort((a, b) => (b[1] as number) - (a[1] as number))
      .map(([name, value]) => ({ name, value: value as number, color: getSportColor(name) }))
  }, [yearData])

  // ── Render ───────────────────────────────────────────

  return (
    <div
      className={clsx(
        'max-w-6xl mx-auto space-y-10 pb-12 transition-opacity duration-200',
        yearFetching && !yearLoading && 'opacity-60',
      )}
    >
      <PageHeader
        title="Dashboard"
        description={headerDescription}
        lastSyncedAt={syncStatus?.last_sync_at}
        controls={
          <>
          <select
            value={year}
            onChange={e => setYear(Number(e.target.value))}
            className="select shrink-0"
            aria-label="Year"
          >
            {(years ?? []).map((y: number) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
          <select
            value={mainSport}
            onChange={e => setMainSport(e.target.value)}
            className="select shrink-0"
            style={{ borderLeftWidth: 2, borderLeftColor: sportColor }}
            aria-label="Sport"
          >
            {(sportTypes ?? []).map((s: string) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          </>
        }
        actions={
          <div className="hidden sm:flex items-center gap-2">
          <ExportButton
            url={`/api/exports/year-in-sport?year=${year}&main_sport=${mainSport}`}
            label="PNG · Sport"
            filename={`year_in_sport_${year}_${mainSport}.png`}
            exportType="year-in-sport"
          />
          <ExportButton
            url={`/api/exports/year-in-sport?year=${year}&main_sport=${mainSport}&variant=totals`}
            label="PNG · Totals"
            filename={`year_in_sport_${year}_totals.png`}
            exportType="year-in-sport"
          />
          </div>
        }
      />

      {/* ── Hero ──────────────────────────────────────── */}
      <HeroBlock
        loading={yearLoading}
        sport={mainSport}
        sportColor={sportColor}
        hasGoal={!!yearlyDistanceGoal}
        goalTarget={yearlyDistanceGoal}
        todayKm={todayKm}
        goalProgress={goalProgress}
        yearPace={yearPace}
        goalStatus={goalStatus}
        etaToGoal={etaToGoal}
        daysElapsed={daysElapsed}
        daysInYear={daysInYear}
        daysRemaining={daysRemaining}
        isCurrentYear={isCurrentYear}
        thisWeek={thisWeek}
        totalDistanceDelta={yearDelta('main_sport', 'total_distance_km') as number | 'new' | null}
        longestActivityKm={yearData?.main_sport?.longest_activity_km ?? 0}
        activeDays={yearData?.main_sport?.active_days ?? 0}
      />

      {/* ── Primary stats (main sport) ─────────────────── */}
      {!yearLoading && yearData && (
        <section>
          <div className="section-head mb-4">
            <span className="eyebrow">{mainSport} · key metrics</span>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3 stagger-children">
            <StatCard label="Activities" value={yearData.main_sport.total_activities} delta={yearDelta('main_sport', 'total_activities')} accent={sportColor} />
            <StatCard label="Distance" value={distValue(yearData.main_sport.total_distance_km ?? 0, mainSport)} unit={getDistUnit(mainSport)} delta={yearDelta('main_sport', 'total_distance_km')} accent={sportColor} />
            <StatCard label="Time" value={yearData.main_sport.total_time_hours?.toFixed(1)} unit="hrs" delta={yearDelta('main_sport', 'total_time_hours')} accent={sportColor} />
            <StatCard label="Elevation" value={Math.round(yearData.main_sport.total_elevation_m ?? 0)} unit="m" delta={yearDelta('main_sport', 'total_elevation_m')} accent={sportColor} />
            <StatCard label="Avg / Week" value={yearData.main_sport.activities_per_week?.toFixed(1)} delta={yearDelta('main_sport', 'activities_per_week')} accent={sportColor} />
          </div>
        </section>
      )}

      {/* ── Secondary: all-sports telemetry strip ──────── */}
      {!yearLoading && yearData && (
        <section>
          <div className="section-head mb-4">
            <span className="eyebrow">All-sport totals</span>
          </div>
          <div className={clsx(
            'panel px-5 py-4 grid grid-cols-2 md:grid-cols-4 divide-y md:divide-y-0 md:divide-x',
            isLight ? 'divide-gray-200' : 'divide-surface-600',
          )}>
            <TelemetryCell
              label="Total activities"
              value={String(yearData.all_sports.total_activities ?? 0)}
              delta={yearDelta('all_sports', 'total_activities') as number | 'new' | null}
            />
            <TelemetryCell
              label="Total distance"
              value={(yearData.all_sports.total_distance_km ?? 0).toFixed(1)}
              unit="km"
              delta={yearDelta('all_sports', 'total_distance_km') as number | 'new' | null}
            />
            <TelemetryCell
              label="Total time"
              value={(yearData.all_sports.total_time_hours ?? 0).toFixed(1)}
              unit="hrs"
              delta={yearDelta('all_sports', 'total_time_hours') as number | 'new' | null}
            />
            <TelemetryCell
              label="Active days"
              value={String(yearData.all_sports.active_days ?? 0)}
              delta={yearDelta('all_sports', 'active_days') as number | 'new' | null}
            />
          </div>
        </section>
      )}

      {/* ── Cumulative distance (hero chart) ──────────── */}
      {cumulativeChartData.length > 0 && (
        <section className="space-y-4">
          <div className="section-head">
            <span className="eyebrow">Progress</span>
          </div>
          <ChartPanel
            title="Cumulative distance"
            sublabel={mainSport}
            accent={sportColor}
            status={goalStatus ? (
              <span
                className="inline-flex items-center gap-1.5 text-[10px] uppercase font-semibold tracking-[0.15em] px-2 py-0.5 rounded-full border"
                style={{
                  backgroundColor: goalStatus.tone === 'positive' ? 'rgba(34, 197, 94, 0.12)'
                    : goalStatus.tone === 'negative' ? 'rgba(239, 68, 68, 0.12)'
                    : `${sportColor}22`,
                  color: goalStatus.tone === 'positive' ? '#4ade80'
                    : goalStatus.tone === 'negative' ? '#f87171'
                    : sportColor,
                  borderColor: goalStatus.tone === 'positive' ? 'rgba(34, 197, 94, 0.3)'
                    : goalStatus.tone === 'negative' ? 'rgba(239, 68, 68, 0.3)'
                    : `${sportColor}55`,
                }}
              >
                <span
                  className="inline-block w-1.5 h-1.5 rounded-full"
                  style={{
                    backgroundColor: goalStatus.tone === 'positive' ? '#4ade80'
                      : goalStatus.tone === 'negative' ? '#f87171'
                      : sportColor,
                  }}
                />
                {goalStatus.label}{goalStatus.pct !== 0 && ` · ${goalStatus.pct > 0 ? '+' : ''}${goalStatus.pct.toFixed(1)}%`}
              </span>
            ) : undefined}
            legend={
              <>
                <LegendSwatch color={sportColor} label={`${year}`} variant="solid" />
                {comp && <LegendSwatch color={sportColor} label={`${year - 1}`} variant="dashed" />}
                {yearlyDistanceGoal && <LegendSwatch color={isLight ? '#6b7280' : '#9ca3af'} label={`Target · ${formatDist(yearlyDistanceGoal, mainSport)}`} variant="dashed" />}
              </>
            }
          >
            <ResponsiveContainer width="100%" height={280}>
              <AreaChart data={cumulativeChartData} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="cumulGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={sportColor} stopOpacity={0.3} />
                    <stop offset="100%" stopColor={sportColor} stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke={colors.gridStroke} />
                <XAxis dataKey="label" tick={{ fill: colors.tickFill, fontSize: 10 }} axisLine={false} tickLine={false} interval="equidistantPreserveStart" />
                <YAxis tick={{ fill: colors.tickFillSecondary, fontSize: 10 }} axisLine={false} tickLine={false} width={isMobile ? 32 : 55} tickFormatter={(v: number) => formatDistAxis(v, mainSport)} />
                <Tooltip
                  contentStyle={{ backgroundColor: colors.tooltipBg, border: `1px solid ${colors.tooltipBorder}`, borderRadius: 8, fontSize: 12 }}
                  labelStyle={{ color: colors.labelColor }}
                  itemStyle={{ color: colors.labelColor }}
                  formatter={(value: unknown, name: unknown) => [
                    formatDist(Number(value ?? 0), mainSport),
                    name === 'prev' ? `${year - 1}` : name === 'target' ? 'Target' : `${year}`,
                  ]}
                />
                {comp && (
                  <Area type="monotone" dataKey="prev" stroke={sportColor} strokeWidth={1.5} strokeDasharray="6 3" strokeOpacity={0.4} fill="none" dot={false} connectNulls />
                )}
                <Area type="monotone" dataKey="current" stroke={sportColor} strokeWidth={2.5} fill="url(#cumulGrad)" dot={false} />
                {yearlyDistanceGoal && (
                  <Line type="monotone" dataKey="target" stroke={isLight ? '#6b7280' : '#9ca3af'} strokeWidth={1.5} strokeDasharray="6 4" dot={false} connectNulls />
                )}
                {todayLabel && isCurrentYear && (
                  <>
                    <ReferenceArea x1={todayLabel} x2={cumulativeChartData[cumulativeChartData.length - 1]?.label} fill={isLight ? '#000' : '#fff'} fillOpacity={0.03} />
                    <ReferenceLine x={todayLabel} stroke={sportColor} strokeWidth={1.5} strokeDasharray="4 3" strokeOpacity={0.6} label={{ value: 'Today', position: 'insideTopRight', fill: sportColor, fontSize: 11, fontWeight: 600, dy: 10 }} />
                  </>
                )}
              </AreaChart>
            </ResponsiveContainer>
          </ChartPanel>
        </section>
      )}

      {/* ── Monthly — merged with metric toggle ─────────── */}
      {!yearLoading && yearData && (
        <ChartPanel
          title="Monthly"
          sublabel={mainSport}
          accent={sportColor}
          toolbar={
            <div className="flex items-center gap-0.5" role="tablist">
              <button className="chip" data-active={monthlyMetric === 'distance'} onClick={() => setMonthlyMetric('distance')}>
                {getDistUnit(mainSport)}
              </button>
              <button className="chip" data-active={monthlyMetric === 'activities'} onClick={() => setMonthlyMetric('activities')}>
                acts
              </button>
            </div>
          }
          legend={
            comp ? (
              <>
                <LegendSwatch color={sportColor} label={`${year}`} variant="solid" />
                <LegendSwatch color={sportColor} label={`${year - 1}`} variant="outline" />
              </>
            ) : undefined
          }
        >
          <ResponsiveContainer width="100%" height={240}>
            <ComposedChart data={monthlyChartData} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={colors.gridStroke} />
              <XAxis dataKey="month" tick={{ fill: colors.tickFill, fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis
                tick={{ fill: colors.tickFillSecondary, fontSize: 10 }}
                axisLine={false}
                tickLine={false}
                width={isMobile ? (monthlyMetric === 'distance' ? 32 : 24) : (monthlyMetric === 'distance' ? 50 : 30)}
                allowDecimals={monthlyMetric === 'distance'}
                tickFormatter={(v: number) => monthlyMetric === 'distance' ? formatDistAxis(v, mainSport) : `${v}`}
              />
              <Tooltip
                contentStyle={{ backgroundColor: colors.tooltipBg, border: `1px solid ${colors.tooltipBorder}`, borderRadius: 8, fontSize: 12 }}
                labelStyle={{ color: colors.labelColor }}
                itemStyle={{ color: colors.labelColor }}
                formatter={(value: unknown, name: unknown) => {
                  const v = Number(value ?? 0)
                  const current = monthlyMetric === 'distance' ? 'distance' : 'activities'
                  const prev = monthlyMetric === 'distance' ? 'prevDistance' : 'prevActivities'
                  const label = name === prev ? `${year - 1}` : name === current ? `${year}` : ''
                  const formatted = monthlyMetric === 'distance' ? formatDist(v, mainSport) : `${v}`
                  return [formatted, label]
                }}
              />
              {comp && (
                <Bar
                  dataKey={monthlyMetric === 'distance' ? 'prevDistance' : 'prevActivities'}
                  fill={sportColor}
                  fillOpacity={0.15}
                  stroke={sportColor}
                  strokeOpacity={0.3}
                  strokeWidth={1}
                  radius={[3, 3, 0, 0]}
                />
              )}
              <Bar
                dataKey={monthlyMetric === 'distance' ? 'distance' : 'activities'}
                fill={sportColor}
                fillOpacity={0.7}
                radius={[3, 3, 0, 0]}
              />
              <Line
                dataKey={monthlyMetric === 'distance' ? 'distance' : 'activities'}
                stroke={sportColor}
                strokeWidth={2}
                dot={false}
                type="monotone"
                legendType="none"
                tooltipType="none"
              />
            </ComposedChart>
          </ResponsiveContainer>
        </ChartPanel>
      )}

      {/* ── Weekly totals ─────────────────────────────── */}
      {weeklyTotalsData && weeklyTotalsData.data.length > 0 && (
        <ChartPanel
          title="Weekly"
          sublabel={mainSport}
          accent={sportColor}
          toolbar={
            <div className="flex items-center gap-0.5">
              {([12, 16, 24, 52] as WeeklyWindow[]).map(w => (
                <button
                  key={w}
                  onClick={() => setWeeklyTotalsWeeks(w)}
                  className="chip font-mono"
                  data-active={weeklyTotalsWeeks === w}
                >
                  {w}w
                </button>
              ))}
            </div>
          }
        >
          {(() => {
            const hasDistance = weeklyTotalsData.data.some((w: { total_distance_km?: number }) => (w.total_distance_km ?? 0) > 0)
            const dataKey = hasDistance ? 'total_distance_km' : 'total_activities'
            const tooltipFmt = hasDistance
              ? (v: unknown) => [formatDist(Number(v), mainSport), 'Distance'] as [string, string]
              : (v: unknown) => [`${v}`, 'Activities'] as [string, string]
            return (
              <ResponsiveContainer width="100%" height={240}>
                <LineChart data={weeklyTotalsData.data} margin={{ top: 5, right: 30, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={colors.gridStroke} />
                  <XAxis
                    dataKey="week_label"
                    tick={{ fill: colors.tickFill, fontSize: 10 }}
                    axisLine={false}
                    tickLine={false}
                    interval={weeklyTotalsWeeks <= 16 ? 0 : Math.floor(weeklyTotalsWeeks / 12)}
                    angle={-45}
                    textAnchor="end"
                    height={55}
                    dy={12}
                  />
                  <YAxis
                    tick={{ fill: colors.tickFillSecondary, fontSize: 10 }}
                    axisLine={false}
                    tickLine={false}
                    width={isMobile ? 32 : 50}
                    allowDecimals={hasDistance}
                    tickFormatter={(v: number) => hasDistance ? formatDistAxis(v, mainSport) : `${v}`}
                  />
                  <Tooltip
                    contentStyle={{ backgroundColor: colors.tooltipBg, border: `1px solid ${colors.tooltipBorder}`, borderRadius: 8, fontSize: 12 }}
                    labelStyle={{ color: colors.labelColor }}
                    itemStyle={{ color: colors.labelColor }}
                    formatter={tooltipFmt}
                  />
                  <Line
                    dataKey={dataKey}
                    stroke={sportColor}
                    strokeWidth={2}
                    dot={{ fill: sportColor, r: 3 }}
                    activeDot={{ r: 5, fill: sportColor, stroke: isLight ? '#fff' : '#0c0c0c', strokeWidth: 2 }}
                    type="monotone"
                  />
                </LineChart>
              </ResponsiveContainer>
            )
          })()}
        </ChartPanel>
      )}

      {/* ── Relative effort — run/swim only; hides itself for other sports ── */}
      <RelativeEffortChart sportType={mainSport} />

      {/* ── Sport breakdown + Records ──────────────────── */}
      {!yearLoading && yearData && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {sportBars.length > 0 && (
            <ChartPanel title="Activities per sport" accent={sportColor} glow={false}>
              <div className="space-y-2.5">
                {sportBars.map(d => {
                  const max = sportBars[0]?.value || 1
                  const pct = (d.value / max) * 100
                  return (
                    <div key={d.name} className="flex items-center gap-3">
                      <span className={clsx('text-xs w-24 shrink-0 text-right truncate', isLight ? 'text-gray-500' : 'text-gray-400')}>{d.name}</span>
                      <div className={clsx('flex-1 h-5 rounded overflow-hidden relative', isLight ? 'bg-gray-100' : 'bg-surface-700')}>
                        <div
                          className="h-full rounded flex items-center px-2"
                          style={{ width: `${Math.max(pct, 8)}%`, backgroundColor: d.color, opacity: 0.72 }}
                        >
                          <span className="text-[10px] font-mono text-white font-semibold tabular-nums">{d.value}</span>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            </ChartPanel>
          )}
          <ChartPanel title={`Records · ${mainSport}`} accent={sportColor} glow={false}>
            <div>
              {yearData.main_sport.longest_activity_km > 0 && (
                <RecordRow label="Longest distance" value={formatDist(yearData.main_sport.longest_activity_km, mainSport)} activityId={yearData.main_sport.longest_activity_km_id} color={sportColor} />
              )}
              {yearData.main_sport.longest_activity_mins > 0 && (
                <RecordRow label="Longest time" value={`${Math.round(yearData.main_sport.longest_activity_mins)} min`} activityId={yearData.main_sport.longest_activity_mins_id} color={sportColor} />
              )}
              {yearData.main_sport.fastest_activity_speed > 0 && (
                <RecordRow label="Fastest" value={formatSpeed(yearData.main_sport.fastest_activity_speed, mainSport)} activityId={yearData.main_sport.fastest_activity_speed_id} color={sportColor} />
              )}
              {yearData.main_sport.average_speed > 0 && (
                <RecordRow label="Average pace" value={formatSpeed(yearData.main_sport.average_speed, mainSport)} color={sportColor} />
              )}
              {yearData.main_sport.most_active_weekday != null && (
                <RecordRow label="Most active day" value={WEEKDAYS_SHORT[yearData.main_sport.most_active_weekday]} color={sportColor} />
              )}
              {yearData.main_sport.month_most_km != null && (
                <RecordRow label={`Best month · ${getDistUnit(mainSport)}`} value={MONTH_LABELS[yearData.main_sport.month_most_km - 1]} color={sportColor} />
              )}
            </div>
          </ChartPanel>
        </div>
      )}
    </div>
  )
}

// ────────────────────────────────────────────────────────
// Hero block
// ────────────────────────────────────────────────────────

interface HeroBlockProps {
  loading: boolean
  sport: string
  sportColor: string
  hasGoal: boolean
  goalTarget: number | undefined
  todayKm: number
  goalProgress: number
  yearPace: number
  goalStatus: { label: string; tone: 'accent' | 'positive' | 'negative'; pct: number } | null
  etaToGoal: Date | null
  daysElapsed: number
  daysInYear: number
  daysRemaining: number
  isCurrentYear: boolean
  thisWeek: { total_distance_km?: number; total_activities?: number; week_label?: string } | null
  totalDistanceDelta: number | 'new' | null
  longestActivityKm: number
  activeDays: number
}

function HeroBlock(props: HeroBlockProps) {
  const {
    loading, sport, sportColor, hasGoal, goalTarget, todayKm, goalProgress, yearPace,
    goalStatus, etaToGoal, daysElapsed, daysInYear, daysRemaining, isCurrentYear,
    thisWeek, totalDistanceDelta, longestActivityKm, activeDays,
  } = props
  const { theme } = useTheme()
  const isLight = theme === 'light'

  // Ring state — swim uses meters, other sports use km
  const unit = getDistUnit(sport)
  const isSwim = unit === 'm'
  const displayDist = (km: number) => isSwim ? Math.round(km * 1000) : Math.round(km)
  const ringValue = displayDist(todayKm).toLocaleString()
  const ringSubValue = hasGoal
    ? `of ${displayDist(goalTarget ?? 0).toLocaleString()} ${unit}`
    : `${unit} · ${sport}`
  const ringLabel = hasGoal ? `${Math.round(goalProgress * 100)}% of goal` : `Year progress · ${Math.round(yearPace * 100)}%`
  const ringStatus = hasGoal && goalStatus ? { label: goalStatus.label, tone: goalStatus.tone } : undefined

  return (
    <section
      className={clsx(
        'panel hero-brackets relative p-6 md:p-8 grid gap-8 md:gap-10',
        'md:grid-cols-[minmax(0,auto)_1fr]',
        isLight ? 'bg-white' : 'bg-surface-800',
      )}
      style={{ ['--card-accent' as string]: sportColor }}
    >
      {/* Ring — left */}
      <div className="flex items-center justify-center md:justify-start">
        {loading ? (
          <div
            className={clsx('rounded-full animate-pulse', isLight ? 'bg-gray-100' : 'bg-surface-700')}
            style={{ width: 260, height: 260 }}
          />
        ) : (
          <GoalRing
            progress={hasGoal ? goalProgress : yearPace}
            pace={hasGoal && isCurrentYear ? yearPace : undefined}
            accent={sportColor}
            size={260}
            stroke={10}
            label={ringLabel}
            value={ringValue}
            subValue={ringSubValue}
            status={ringStatus}
          />
        )}
      </div>

      {/* Supporting stats — right side */}
      <div className="flex flex-col justify-center min-w-0">
        <div className="grid grid-cols-2 gap-x-8 gap-y-5">
          <HeroStat
            label={isCurrentYear ? 'This week' : 'Latest week'}
            value={thisWeek?.total_distance_km != null ? distValue(thisWeek.total_distance_km, sport) : '—'}
            unit={thisWeek?.total_distance_km != null ? getDistUnit(sport) : undefined}
            footnote={thisWeek?.total_activities != null ? `${thisWeek.total_activities} activities` : undefined}
            accent={sportColor}
          />
          <HeroStat
            label="vs. Last year"
            value={
              totalDistanceDelta === 'new' ? 'NEW'
              : typeof totalDistanceDelta === 'number' ? `${totalDistanceDelta >= 0 ? '+' : ''}${totalDistanceDelta.toFixed(1)}%`
              : '—'
            }
            tone={
              totalDistanceDelta === 'new' ? 'positive'
              : typeof totalDistanceDelta === 'number' && totalDistanceDelta >= 0 ? 'positive'
              : typeof totalDistanceDelta === 'number' ? 'negative'
              : 'neutral'
            }
            footnote="total distance"
          />
          <HeroStat
            label={isCurrentYear ? 'Days remaining' : 'Days in year'}
            value={isCurrentYear ? String(daysRemaining) : String(daysInYear)}
            unit="days"
            footnote={isCurrentYear ? `of ${daysInYear}` : undefined}
          />
          <HeroStat
            label={hasGoal && etaToGoal ? 'Projected finish' : 'Active days'}
            value={
              hasGoal && etaToGoal
                ? etaToGoal.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
                : String(activeDays)
            }
            footnote={
              hasGoal && etaToGoal
                ? 'at current pace'
                : hasGoal ? undefined : `longest · ${formatDist(longestActivityKm, sport)}`
            }
          />
        </div>

        {/* Year-elapsed strip */}
        {isCurrentYear && (
          <div className="mt-6 pt-5 border-t border-dashed border-surface-600/40">
            <div className="flex items-center justify-between text-[10px] uppercase tracking-[0.15em] text-gray-500 mb-2">
              <span>Year elapsed</span>
              <span className="tabular-nums font-mono">
                Day <span style={{ color: sportColor }}>{daysElapsed}</span> / {daysInYear}
              </span>
            </div>
            <div className={clsx('h-[3px] rounded-full overflow-hidden', isLight ? 'bg-gray-200' : 'bg-surface-700')}>
              <div
                className="h-full rounded-full transition-all duration-700 ease-out"
                style={{ width: `${yearPace * 100}%`, backgroundColor: sportColor, opacity: 0.8 }}
              />
            </div>
          </div>
        )}

        {!hasGoal && (
          <div className="mt-6 pt-5 border-t border-dashed border-surface-600/40">
            <Link
              to="/profile"
              className={clsx(
                'inline-flex items-center gap-2 text-xs font-semibold transition-colors',
                isLight ? 'text-gray-600 hover:text-gray-900' : 'text-gray-400 hover:text-gray-100',
              )}
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
                <path d="M7 1v12M1 7h12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
              Set a yearly goal
              <span className="opacity-50">→</span>
            </Link>
          </div>
        )}
      </div>
    </section>
  )
}

// ────────────────────────────────────────────────────────
// HeroStat — supporting stat in hero right side
// ────────────────────────────────────────────────────────

interface HeroStatProps {
  label: string
  value: string
  unit?: string
  footnote?: string
  accent?: string
  tone?: 'accent' | 'positive' | 'negative' | 'neutral'
}

function HeroStat({ label, value, unit, footnote, accent, tone = 'neutral' }: HeroStatProps) {
  const { theme } = useTheme()
  const isLight = theme === 'light'

  const color =
    tone === 'positive' ? (isLight ? '#16a34a' : '#4ade80')
    : tone === 'negative' ? (isLight ? '#dc2626' : '#f87171')
    : tone === 'accent' ? (accent ?? (isLight ? '#0f172a' : '#f3f4f6'))
    : (accent ?? (isLight ? '#0f172a' : '#f3f4f6'))

  return (
    <div>
      <div className="eyebrow mb-1.5">{label}</div>
      <div className="flex items-baseline gap-1.5">
        <span
          className="font-mono tabular-nums font-semibold tracking-tight leading-none"
          style={{ color, fontSize: 30, letterSpacing: '-0.02em' }}
        >
          {value}
        </span>
        {unit && (
          <span className={clsx('text-sm font-medium', isLight ? 'text-gray-400' : 'text-gray-500')}>{unit}</span>
        )}
      </div>
      {footnote && (
        <div className={clsx('text-[11px] mt-1', isLight ? 'text-gray-500' : 'text-gray-500')}>{footnote}</div>
      )}
    </div>
  )
}

// ────────────────────────────────────────────────────────
// TelemetryCell — single cell in the all-sports strip
// ────────────────────────────────────────────────────────

interface TelemetryCellProps {
  label: string
  value: string
  unit?: string
  delta?: number | 'new' | null
}

function TelemetryCell({ label, value, unit, delta }: TelemetryCellProps) {
  const { theme } = useTheme()
  const isLight = theme === 'light'

  return (
    <div className="px-4 py-2 md:py-1 first:pl-0 last:pr-0 md:first:pl-4 md:last:pr-4">
      <div className="eyebrow mb-1">{label}</div>
      <div className="flex items-baseline gap-1.5">
        <span className={clsx('font-mono tabular-nums text-xl font-semibold tracking-tight', isLight ? 'text-gray-900' : 'text-gray-100')}>
          {value}
        </span>
        {unit && (
          <span className={clsx('text-xs font-medium', isLight ? 'text-gray-400' : 'text-gray-500')}>{unit}</span>
        )}
        {delta !== undefined && delta !== null && (
          <span
            className={clsx(
              'text-[10px] font-semibold ml-1',
              delta === 'new'
                ? (isLight ? 'text-green-700' : 'text-green-400')
                : (delta as number) >= 0
                  ? (isLight ? 'text-green-700' : 'text-green-400')
                  : (isLight ? 'text-red-700' : 'text-red-400'),
            )}
          >
            {delta === 'new' ? 'new' : `${(delta as number) >= 0 ? '+' : ''}${(delta as number).toFixed(1)}%`}
          </span>
        )}
      </div>
    </div>
  )
}

// ────────────────────────────────────────────────────────
// RecordRow — single row in records panel
// ────────────────────────────────────────────────────────

function RecordRow({ label, value, activityId, color }: { label: string; value: string; activityId?: string | null; color: string }) {
  const content = (
    <div className="telemetry-row group">
      <span className="text-sm text-gray-400">{label}</span>
      <span className="text-sm font-mono tabular-nums group-hover:underline" style={{ color }}>{value}</span>
    </div>
  )
  if (activityId) return <Link to={`/activities/${activityId}`}>{content}</Link>
  return content
}
