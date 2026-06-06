import { AreaChart, Area, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceArea } from 'recharts'
import { useMemo, Component, type ReactNode } from 'react'
import { useTheme } from '../../hooks/useTheme'
import { useIsMobile } from '../../hooks/useIsMobile'

export interface ChartZone {
  x1: number  // start distance (km)
  x2: number  // end distance (km)
  color: string
  label?: string
  opacity?: number
}

interface StreamChartProps {
  title: string
  data: { distance: number; value: number }[]
  color: string
  gradientId: string
  unit: string
  reversed?: boolean
  yDomain?: [string | number, string | number]
  formatValue?: (v: number) => string
  secondaryData?: { distance: number; value: number }[]
  secondaryColor?: string
  secondaryLabel?: string
  /** Colored background zones (e.g. workout segments) */
  zones?: ChartZone[]
  /** X-axis unit label (defaults to "km"). Pass "m" for swim streams with a matching xFormatter. */
  xUnit?: string
  /** Formatter for the X-axis values (stored in km). Defaults to `v.toFixed(1)`. */
  xFormatter?: (v: number) => string
}

/** Error boundary to prevent chart crashes from taking down the whole page */
class ChartErrorBoundary extends Component<{ children: ReactNode; title: string }, { hasError: boolean }> {
  constructor(props: { children: ReactNode; title: string }) {
    super(props)
    this.state = { hasError: false }
  }
  static getDerivedStateFromError() {
    return { hasError: true }
  }
  render() {
    if (this.state.hasError) {
      return (
        <div className="bg-surface-800 border border-surface-600 rounded-xl p-4">
          <span className="text-xs text-gray-500 uppercase">{this.props.title}</span>
          <div className="h-[150px] flex items-center justify-center text-gray-500 text-sm">
            Chart failed to render
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

/**
 * Resample data at regular distance intervals using linear interpolation.
 * This avoids compression artifacts when using a numeric X axis.
 */
function resampleByDistance(
  data: { distance: number; value: number }[],
  maxPoints: number,
): { distance: number; value: number }[] {
  if (data.length === 0) return []
  if (data.length <= maxPoints) return data

  const minD = data[0].distance
  const maxD = data[data.length - 1].distance
  const range = maxD - minD
  if (range <= 0) return data.slice(0, maxPoints)

  const step = range / (maxPoints - 1)
  const result: { distance: number; value: number }[] = []
  let srcIdx = 0

  for (let i = 0; i < maxPoints; i++) {
    const targetDist = minD + i * step
    // Advance source index
    while (srcIdx < data.length - 1 && data[srcIdx + 1].distance <= targetDist) {
      srcIdx++
    }
    // Linear interpolation between srcIdx and srcIdx+1
    if (srcIdx < data.length - 1) {
      const d0 = data[srcIdx].distance
      const d1 = data[srcIdx + 1].distance
      const span = d1 - d0
      if (span > 0) {
        const t = (targetDist - d0) / span
        const v = data[srcIdx].value + t * (data[srcIdx + 1].value - data[srcIdx].value)
        result.push({ distance: targetDist, value: v })
      } else {
        result.push({ distance: targetDist, value: data[srcIdx].value })
      }
    } else {
      result.push({ distance: targetDist, value: data[srcIdx].value })
    }
  }
  return result
}

export default function StreamChart({
  title, data, color, gradientId, unit,
  reversed = false, yDomain, formatValue,
  secondaryData, secondaryColor, secondaryLabel,
  zones,
  xUnit = 'km',
  xFormatter = (v: number) => v.toFixed(1),
}: StreamChartProps) {
  const { colors } = useTheme()
  const isMobile = useIsMobile()

  const hasZones = zones && zones.length > 0

  // Downsample: use distance-based resampling when zones are present (needs numeric axis),
  // otherwise use simple index-based sampling (category axis, preserves time-based spacing)
  const chartData = useMemo(() => {
    if (data.length === 0) return []
    const maxPoints = 400

    if (hasZones) {
      // Distance-based resampling for numeric axis
      const primary = resampleByDistance(data, maxPoints)
      if (!secondaryData || secondaryData.length === 0) return primary

      const secondary = resampleByDistance(secondaryData, maxPoints)
      const secMap = new Map<number, number>()
      for (const pt of secondary) {
        secMap.set(Math.round(pt.distance * 100), pt.value)
      }
      return primary.map(pt => {
        const key = Math.round(pt.distance * 100)
        let closest = secMap.get(key)
        if (closest === undefined && secondary.length > 0) {
          let minDiff = Infinity
          for (const s of secondary) {
            const diff = Math.abs(s.distance - pt.distance)
            if (diff < minDiff) { minDiff = diff; closest = s.value }
            if (diff > minDiff) break
          }
        }
        return { ...pt, secondary: closest }
      })
    }

    // Index-based sampling for category axis (original behavior)
    const step = data.length > maxPoints ? Math.ceil(data.length / maxPoints) : 1
    const primary = step > 1 ? data.filter((_, i) => i % step === 0) : data

    if (!secondaryData || secondaryData.length === 0) return primary

    const secStep = secondaryData.length > maxPoints ? Math.ceil(secondaryData.length / maxPoints) : 1
    const secondary = secStep > 1 ? secondaryData.filter((_, i) => i % secStep === 0) : secondaryData
    const secMap = new Map<number, number>()
    for (const pt of secondary) {
      secMap.set(Math.round(pt.distance * 100), pt.value)
    }
    return primary.map(pt => {
      const key = Math.round(pt.distance * 100)
      const secVal = secMap.get(key)
      let closest = secVal
      if (closest === undefined && secondary.length > 0) {
        let minDiff = Infinity
        for (const s of secondary) {
          const diff = Math.abs(s.distance - pt.distance)
          if (diff < minDiff) { minDiff = diff; closest = s.value }
          if (diff > minDiff) break
        }
      }
      return { ...pt, secondary: closest }
    })
  }, [data, secondaryData, hasZones])

  const fmt = formatValue ?? ((v: number) => v.toFixed(0))
  const hasSecondary = secondaryData && secondaryData.length > 0

  // Clip zones to actual data range so ReferenceArea doesn't fall outside the domain
  const clippedZones = useMemo(() => {
    if (!hasZones || !zones || chartData.length === 0) return []
    const dataMin = chartData[0].distance
    const dataMax = chartData[chartData.length - 1].distance
    return zones
      .map(z => ({
        ...z,
        x1: Math.max(z.x1, dataMin),
        x2: Math.min(z.x2, dataMax),
      }))
      .filter(z => z.x2 > z.x1)
  }, [zones, hasZones, chartData])

  // Deduplicate zone labels for legend
  const zoneLegend = useMemo(() => {
    if (!hasZones || !zones) return []
    const seen = new Set<string>()
    const items: { label: string; color: string }[] = []
    for (const z of zones) {
      if (z.label && !seen.has(z.label)) {
        seen.add(z.label)
        items.push({ label: z.label, color: z.color })
      }
    }
    return items
  }, [zones, hasZones])

  if (chartData.length === 0) {
    return (
      <div className="bg-surface-800 border border-surface-600 rounded-xl p-4">
        <span className="text-xs text-gray-500 uppercase">{title}</span>
        <div className="h-[150px] flex items-center justify-center text-gray-500 text-sm">
          No data
        </div>
      </div>
    )
  }

  // Gym / indoor activities have no GPS, so distance stays at 0 throughout. Hide the axis
  // and remap each sample's x position to its index so points still spread across the width.
  const hasDistanceRange = chartData.length > 1
    && (chartData[chartData.length - 1].distance - chartData[0].distance) > 0.001
  const plotData = hasDistanceRange
    ? chartData
    : chartData.map((pt, i) => ({ ...pt, distance: i }))

  return (
    <ChartErrorBoundary title={title}>
      <div className="bg-surface-800 border border-surface-600 rounded-xl p-4">
        <div className="flex items-center gap-3 mb-3 flex-wrap">
          <span className="text-xs text-gray-500 uppercase">{title}</span>
          {hasSecondary && secondaryLabel && (
            <span className="text-xs flex items-center gap-1">
              <span className="inline-block w-4 border-t-2 border-dashed" style={{ borderColor: secondaryColor }} />
              <span style={{ color: secondaryColor }}>{secondaryLabel}</span>
            </span>
          )}
          {zoneLegend.map(z => (
            <span key={z.label} className="text-[10px] flex items-center gap-1">
              <span className="inline-block w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: z.color, opacity: 0.5 }} />
              <span className="text-gray-400">{z.label}</span>
            </span>
          ))}
        </div>
        <ResponsiveContainer width="100%" height={150}>
          <AreaChart data={plotData} margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={color} stopOpacity={0.3} />
                <stop offset="95%" stopColor={color} stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis
              dataKey="distance"
              type="number"
              domain={[0, 'dataMax']}
              tick={{ fill: colors.tickFill, fontSize: 10 }}
              tickFormatter={v => xFormatter(Number(v))}
              tickCount={10}
              angle={-30}
              textAnchor="end"
              height={30}
              minTickGap={15}
              axisLine={false}
              tickLine={false}
              hide={!hasDistanceRange}
            />
            <YAxis
              tick={{ fill: colors.tickFill, fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              reversed={reversed}
              domain={yDomain}
              tickFormatter={v => fmt(Number(v))}
              width={isMobile ? 32 : 60}
            />
            <Tooltip
              contentStyle={{ background: colors.tooltipBg, border: `1px solid ${colors.tooltipBorder}`, borderRadius: 8 }}
              labelStyle={{ color: colors.labelColor }}
              itemStyle={{ color: colors.labelColor }}
              labelFormatter={v => hasDistanceRange ? `${xFormatter(Number(v))} ${xUnit}` : ''}
              formatter={(v, name) => {
                const label = name === 'secondary' ? (secondaryLabel ?? 'Secondary') : title
                return [fmt(Number(v ?? 0)) + ` ${unit}`, label]
              }}
            />
            {clippedZones.length > 0 && clippedZones.map((z, i) => (
              <ReferenceArea
                key={i}
                x1={z.x1}
                x2={z.x2}
                fill={z.color}
                fillOpacity={z.opacity ?? 0.12}
                strokeOpacity={0}
              />
            ))}
            <Area
              type="monotone"
              dataKey="value"
              stroke={color}
              fill={`url(#${gradientId})`}
              strokeWidth={1.5}
              baseValue={reversed ? 'dataMax' : 'dataMin'}
            />
            {hasSecondary && (
              <Line
                type="monotone"
                dataKey="secondary"
                stroke={secondaryColor}
                strokeWidth={1.5}
                strokeDasharray="4 3"
                dot={false}
                connectNulls
              />
            )}
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </ChartErrorBoundary>
  )
}
