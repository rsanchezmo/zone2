import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useYearInSport, useYears, useSportTypes } from '../api/hooks'
import { getSportColor } from '../constants/sportColors'
import StatCard from '../components/shared/StatCard'
import ExportButton from '../components/shared/ExportButton'
import {
  ComposedChart, Bar, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { useTheme } from '../hooks/useTheme'

const MONTH_LABELS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const WEEKDAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export default function DashboardPage() {
  const { theme, colors } = useTheme()
  const isLight = theme === 'light'
  const { data: years } = useYears()
  const { data: sportTypes } = useSportTypes()
  const [year, setYear] = useState(new Date().getFullYear())
  const [mainSport, setMainSport] = useState('Run')

  const { data: yearData, isLoading: yearLoading } = useYearInSport(year, mainSport, year - 1)

  const comp = yearData?.comparison
  function yearDelta(section: 'main_sport' | 'all_sports', key: string): number | string | null {
    if (!yearData || !comp) return null
    const c = yearData[section]?.[key]
    const p = comp[section]?.[key]
    if (c == null) return null
    if (!p || p === 0) return c > 0 ? 'new' : null
    return ((c - p) / p) * 100
  }

  const sportColor = getSportColor(mainSport)

  // Monthly distance chart data
  const monthlyDistanceData = useMemo(() => {
    const distMap = yearData?.main_sport?.distance_per_month_km ?? {}
    const compDistMap = comp?.main_sport?.distance_per_month_km ?? {}
    return MONTH_LABELS.map((label, i) => ({
      month: label,
      distance: distMap[i + 1] ?? 0,
      prev: compDistMap[i + 1] ?? 0,
    }))
  }, [yearData, comp])

  // Monthly activities chart data
  const monthlyActivitiesData = useMemo(() => {
    const actMap = yearData?.main_sport?.activities_per_month ?? {}
    const compActMap = comp?.main_sport?.activities_per_month ?? {}
    return MONTH_LABELS.map((label, i) => ({
      month: label,
      activities: actMap[i + 1] ?? 0,
      prev: compActMap[i + 1] ?? 0,
    }))
  }, [yearData, comp])

  // Sport breakdown pie data
  const sportPieData = useMemo(() => {
    const perSport = yearData?.all_sports?.activities_per_sport ?? {}
    return Object.entries(perSport)
      .sort((a, b) => (b[1] as number) - (a[1] as number))
      .map(([name, value]) => ({
        name,
        value: value as number,
        color: getSportColor(name),
      }))
  }, [yearData])

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      <div className="flex items-center gap-3 flex-wrap">
        <h2 className="text-2xl font-bold">Year in Sport</h2>
        <ExportButton
          url={`/api/exports/year-in-sport?year=${year}&main_sport=${mainSport}`}
          label="Export Sport PNG"
          filename={`year_in_sport_${year}_${mainSport}.png`}
        />
        <ExportButton
          url={`/api/exports/year-in-sport?year=${year}&main_sport=${mainSport}&variant=totals`}
          label="Export Totals PNG"
          filename={`year_in_sport_${year}_totals.png`}
        />
        <select
          value={year}
          onChange={e => setYear(Number(e.target.value))}
          className="bg-surface-700 border border-surface-600 rounded px-2 py-1 text-sm"
        >
          {(years ?? []).map((y: number) => (
            <option key={y} value={y}>{y}</option>
          ))}
        </select>
        <select
          value={mainSport}
          onChange={e => setMainSport(e.target.value)}
          className="bg-surface-700 border border-surface-600 rounded px-2 py-1 text-sm"
        >
          {(sportTypes ?? []).map((s: string) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>

      {yearLoading ? (
        <div className="text-gray-500">Loading...</div>
      ) : yearData ? (
        <>
          {/* Main sport stat cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-3">
            <StatCard label="Activities" value={yearData.main_sport.total_activities} delta={yearDelta('main_sport', 'total_activities')} />
            <StatCard label="Distance" value={yearData.main_sport.total_distance_km?.toFixed(1)} unit="km" delta={yearDelta('main_sport', 'total_distance_km')} />
            <StatCard label="Time" value={yearData.main_sport.total_time_hours?.toFixed(1)} unit="hrs" delta={yearDelta('main_sport', 'total_time_hours')} />
            <StatCard label="Elevation" value={Math.round(yearData.main_sport.total_elevation_m ?? 0)} unit="m" delta={yearDelta('main_sport', 'total_elevation_m')} />
            <StatCard label="Active Days" value={yearData.main_sport.active_days} delta={yearDelta('main_sport', 'active_days')} />
            <StatCard label="Avg Distance" value={yearData.main_sport.average_distance_km?.toFixed(1)} unit="km" delta={yearDelta('main_sport', 'average_distance_km')} />
            <StatCard label="Per Week" value={yearData.main_sport.activities_per_week?.toFixed(1)} delta={yearDelta('main_sport', 'activities_per_week')} />
            <StatCard
              label="All Sports"
              value={yearData.all_sports.total_activities}
              color="text-neon-cyan"
              delta={yearDelta('all_sports', 'total_activities')}
            />
            <StatCard
              label="Total Distance"
              value={yearData.all_sports.total_distance_km?.toFixed(1)}
              unit="km"
              color="text-neon-cyan"
              delta={yearDelta('all_sports', 'total_distance_km')}
            />
            <StatCard
              label="Total Time"
              value={yearData.all_sports.total_time_hours?.toFixed(1)}
              unit="hrs"
              color="text-neon-cyan"
              delta={yearDelta('all_sports', 'total_time_hours')}
            />
          </div>

          {/* Monthly Distance Chart */}
          <div className="bg-surface-800 border border-surface-600 rounded-xl p-4">
            <div className="flex items-center justify-between mb-3">
              <div className="text-xs text-gray-500 uppercase">Monthly Distance — {mainSport}</div>
              {comp && (
                <div className="flex items-center gap-4">
                  <div className="flex items-center gap-1.5">
                    <span className="w-3 h-2 rounded-sm" style={{ backgroundColor: sportColor, opacity: 0.7 }} />
                    <span className="text-[11px] text-gray-400">{year}</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="w-3 h-2 rounded-sm border border-gray-500" style={{ backgroundColor: 'transparent' }} />
                    <span className="text-[11px] text-gray-500">{year - 1}</span>
                  </div>
                </div>
              )}
            </div>
            <ResponsiveContainer width="100%" height={250}>
              <ComposedChart data={monthlyDistanceData} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={colors.gridStroke} />
                <XAxis dataKey="month" tick={{ fill: colors.tickFill, fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: colors.tickFillSecondary, fontSize: 10 }} axisLine={false} tickLine={false} width={40} tickFormatter={(v: number) => `${v}`} />
                <Tooltip
                  contentStyle={{ backgroundColor: colors.tooltipBg, border: `1px solid ${colors.tooltipBorder}`, borderRadius: 8, fontSize: 12 }}
                  labelStyle={{ color: colors.labelColor }}
                  itemStyle={{ color: colors.labelColor }}
                  formatter={(value: number, name: string) => [`${value.toFixed(1)} km`, name === 'prev' ? `${year - 1}` : name === 'distance' ? `${year}` : '']}
                />
                {comp && (
                  <Bar dataKey="prev" fill={sportColor} fillOpacity={0.15} stroke={sportColor} strokeOpacity={0.3} strokeWidth={1} radius={[3, 3, 0, 0]} />
                )}
                <Bar dataKey="distance" fill={sportColor} fillOpacity={0.7} radius={[3, 3, 0, 0]} />
                <Line dataKey="distance" stroke={sportColor} strokeWidth={2} dot={false} type="monotone" legendType="none" tooltipType="none" />
                {comp && (
                  <Line dataKey="prev" stroke={sportColor} strokeWidth={1.5} strokeDasharray="4 3" strokeOpacity={0.4} dot={false} type="monotone" legendType="none" tooltipType="none" />
                )}
              </ComposedChart>
            </ResponsiveContainer>
          </div>

          {/* Monthly Activities Chart */}
          <div className="bg-surface-800 border border-surface-600 rounded-xl p-4">
            <div className="flex items-center justify-between mb-3">
              <div className="text-xs text-gray-500 uppercase">Monthly Activities — {mainSport}</div>
              {comp && (
                <div className="flex items-center gap-4">
                  <div className="flex items-center gap-1.5">
                    <span className="w-3 h-2 rounded-sm" style={{ backgroundColor: sportColor, opacity: 0.7 }} />
                    <span className="text-[11px] text-gray-400">{year}</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="w-3 h-2 rounded-sm border border-gray-500" style={{ backgroundColor: 'transparent' }} />
                    <span className="text-[11px] text-gray-500">{year - 1}</span>
                  </div>
                </div>
              )}
            </div>
            <ResponsiveContainer width="100%" height={250}>
              <ComposedChart data={monthlyActivitiesData} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={colors.gridStroke} />
                <XAxis dataKey="month" tick={{ fill: colors.tickFill, fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: colors.tickFillSecondary, fontSize: 10 }} axisLine={false} tickLine={false} width={30} allowDecimals={false} />
                <Tooltip
                  contentStyle={{ backgroundColor: colors.tooltipBg, border: `1px solid ${colors.tooltipBorder}`, borderRadius: 8, fontSize: 12 }}
                  labelStyle={{ color: colors.labelColor }}
                  itemStyle={{ color: colors.labelColor }}
                  formatter={(value: number, name: string) => [`${value}`, name === 'prev' ? `${year - 1}` : name === 'activities' ? `${year}` : '']}
                />
                {comp && (
                  <Bar dataKey="prev" fill={sportColor} fillOpacity={0.15} stroke={sportColor} strokeOpacity={0.3} strokeWidth={1} radius={[3, 3, 0, 0]} />
                )}
                <Bar dataKey="activities" fill={sportColor} fillOpacity={0.7} radius={[3, 3, 0, 0]} />
                <Line dataKey="activities" stroke={sportColor} strokeWidth={2} dot={false} type="monotone" legendType="none" tooltipType="none" />
                {comp && (
                  <Line dataKey="prev" stroke={sportColor} strokeWidth={1.5} strokeDasharray="4 3" strokeOpacity={0.4} dot={false} type="monotone" legendType="none" tooltipType="none" />
                )}
              </ComposedChart>
            </ResponsiveContainer>
          </div>

          {/* Sport breakdown + Records side by side */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Activities per sport bar chart */}
            {sportPieData.length > 0 && (
              <div className="bg-surface-800 border border-surface-600 rounded-xl p-4 flex flex-col">
                <div className="text-xs text-gray-500 uppercase mb-3">Activities per Sport</div>
                <div className="space-y-2 flex-1 flex flex-col justify-center">
                  {sportPieData.map(d => {
                    const max = sportPieData[0]?.value || 1
                    const pct = (d.value / max) * 100
                    return (
                      <div key={d.name} className="flex items-center gap-3">
                        <span className="text-xs text-gray-400 w-24 shrink-0 text-right truncate">{d.name}</span>
                        <div className="flex-1 h-5 bg-surface-700 rounded overflow-hidden">
                          <div
                            className="h-full rounded flex items-center px-2"
                            style={{ width: `${Math.max(pct, 8)}%`, backgroundColor: d.color, opacity: 0.7 }}
                          >
                            <span className="text-[10px] font-mono text-white font-bold">{d.value}</span>
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {/* Records */}
            <div className="bg-surface-800 border border-surface-600 rounded-xl p-4">
              <div className="text-xs text-gray-500 uppercase mb-3">Records — {mainSport}</div>
              <div className="space-y-3">
                {yearData.main_sport.longest_activity_km > 0 && (
                  <RecordRow
                    label="Longest Distance"
                    value={`${yearData.main_sport.longest_activity_km.toFixed(1)} km`}
                    activityId={yearData.main_sport.longest_activity_km_id}
                    color={sportColor}
                  />
                )}
                {yearData.main_sport.longest_activity_mins > 0 && (
                  <RecordRow
                    label="Longest Time"
                    value={`${Math.round(yearData.main_sport.longest_activity_mins)} min`}
                    activityId={yearData.main_sport.longest_activity_mins_id}
                    color={sportColor}
                  />
                )}
                {yearData.main_sport.fastest_activity_speed > 0 && (
                  <RecordRow
                    label="Fastest"
                    value={formatSpeed(yearData.main_sport.fastest_activity_speed, mainSport)}
                    activityId={yearData.main_sport.fastest_activity_speed_id}
                    color={sportColor}
                  />
                )}
                {yearData.main_sport.average_speed > 0 && (
                  <div className="flex items-center justify-between py-2 border-b border-surface-600/50">
                    <span className="text-sm text-gray-400">Average Pace</span>
                    <span className="text-sm font-mono" style={{ color: sportColor }}>
                      {formatSpeed(yearData.main_sport.average_speed, mainSport)}
                    </span>
                  </div>
                )}
                {yearData.main_sport.most_active_weekday != null && (
                  <div className="flex items-center justify-between py-2 border-b border-surface-600/50">
                    <span className="text-sm text-gray-400">Most Active Day</span>
                    <span className="text-sm font-mono" style={{ color: sportColor }}>
                      {WEEKDAY_LABELS[yearData.main_sport.most_active_weekday]}
                    </span>
                  </div>
                )}
                {yearData.main_sport.month_most_km != null && (
                  <div className="flex items-center justify-between py-2 border-b border-surface-600/50">
                    <span className="text-sm text-gray-400">Best Month (km)</span>
                    <span className="text-sm font-mono" style={{ color: sportColor }}>
                      {MONTH_LABELS[yearData.main_sport.month_most_km - 1]}
                    </span>
                  </div>
                )}
              </div>
            </div>
          </div>
        </>
      ) : null}
    </div>
  )
}

function RecordRow({ label, value, activityId, color }: { label: string; value: string; activityId?: string | null; color: string }) {
  const content = (
    <div className="flex items-center justify-between py-2 border-b border-surface-600/50 group">
      <span className="text-sm text-gray-400">{label}</span>
      <span className="text-sm font-mono group-hover:underline" style={{ color }}>{value}</span>
    </div>
  )

  if (activityId) {
    return <Link to={`/activities/${activityId}`}>{content}</Link>
  }
  return content
}

const CYCLING_SPORTS = ['ride', 'cycling', 'ebikeride', 'virtualride']
const SWIMMING_SPORTS = ['swim', 'swimming']

function formatSpeed(speedMs: number, sportType: string): string {
  const lower = sportType.toLowerCase()
  if (CYCLING_SPORTS.some(s => lower.includes(s))) {
    return `${(speedMs * 3.6).toFixed(1)} km/h`
  }
  if (SWIMMING_SPORTS.some(s => lower.includes(s))) {
    const pace = (100 / speedMs) / 60
    const m = Math.floor(pace)
    const s = Math.round((pace - m) * 60)
    return `${m}:${s.toString().padStart(2, '0')} /100m`
  }
  const pace = (1000 / speedMs) / 60
  const m = Math.floor(pace)
  const s = Math.round((pace - m) * 60)
  return `${m}:${s.toString().padStart(2, '0')} /km`
}
