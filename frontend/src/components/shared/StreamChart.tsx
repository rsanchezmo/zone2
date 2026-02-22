import { AreaChart, Area, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { useMemo } from 'react'
import { useTheme } from '../../hooks/useTheme'

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
}

export default function StreamChart({
  title, data, color, gradientId, unit,
  reversed = false, yDomain, formatValue,
  secondaryData, secondaryColor, secondaryLabel,
}: StreamChartProps) {
  const { colors } = useTheme()

  // Merge primary and secondary data by distance, downsampled
  const chartData = useMemo(() => {
    const maxPoints = 400
    const step = data.length > maxPoints ? Math.ceil(data.length / maxPoints) : 1
    const primary = step > 1 ? data.filter((_, i) => i % step === 0) : data

    if (!secondaryData || secondaryData.length === 0) return primary

    // Build a map of secondary values by rounded distance for lookup
    const secStep = secondaryData.length > maxPoints ? Math.ceil(secondaryData.length / maxPoints) : 1
    const secondary = secStep > 1 ? secondaryData.filter((_, i) => i % secStep === 0) : secondaryData
    const secMap = new Map<number, number>()
    for (const pt of secondary) {
      secMap.set(Math.round(pt.distance * 100), pt.value)
    }

    return primary.map(pt => {
      const key = Math.round(pt.distance * 100)
      const secVal = secMap.get(key)
      // Find closest if exact match not found
      let closest = secVal
      if (closest === undefined && secondary.length > 0) {
        let minDiff = Infinity
        for (const s of secondary) {
          const diff = Math.abs(s.distance - pt.distance)
          if (diff < minDiff) {
            minDiff = diff
            closest = s.value
          }
          if (diff > minDiff) break // sorted, so we can stop
        }
      }
      return { ...pt, secondary: closest }
    })
  }, [data, secondaryData])

  const fmt = formatValue ?? ((v: number) => v.toFixed(0))
  const hasSecondary = secondaryData && secondaryData.length > 0

  return (
    <div className="bg-surface-800 border border-surface-600 rounded-xl p-4">
      <div className="flex items-center gap-3 mb-3">
        <span className="text-xs text-gray-500 uppercase">{title}</span>
        {hasSecondary && secondaryLabel && (
          <span className="text-xs flex items-center gap-1">
            <span className="inline-block w-4 border-t-2 border-dashed" style={{ borderColor: secondaryColor }} />
            <span style={{ color: secondaryColor }}>{secondaryLabel}</span>
          </span>
        )}
      </div>
      <ResponsiveContainer width="100%" height={150}>
        <AreaChart data={chartData} margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={color} stopOpacity={0.3} />
              <stop offset="95%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis
            dataKey="distance"
            tick={{ fill: colors.tickFill, fontSize: 10 }}
            tickFormatter={v => `${Number(v).toFixed(1)}`}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            tick={{ fill: colors.tickFill, fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            reversed={reversed}
            domain={yDomain}
            tickFormatter={v => fmt(Number(v))}
          />
          <Tooltip
            contentStyle={{ background: colors.tooltipBg, border: `1px solid ${colors.tooltipBorder}`, borderRadius: 8 }}
            labelStyle={{ color: colors.labelColor }}
            itemStyle={{ color: colors.labelColor }}
            labelFormatter={v => `${Number(v).toFixed(2)} km`}
            formatter={(v: number | undefined, name: string) => {
              const label = name === 'secondary' ? (secondaryLabel ?? 'Secondary') : title
              return [fmt(v ?? 0) + ` ${unit}`, label]
            }}
          />
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
  )
}
