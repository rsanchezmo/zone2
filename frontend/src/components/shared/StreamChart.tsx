import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
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
}

export default function StreamChart({
  title, data, color, gradientId, unit,
  reversed = false, yDomain, formatValue,
}: StreamChartProps) {
  const { colors } = useTheme()

  // Downsample for performance
  const chartData = useMemo(() => {
    const maxPoints = 400
    if (data.length <= maxPoints) return data
    const step = Math.ceil(data.length / maxPoints)
    return data.filter((_, i) => i % step === 0)
  }, [data])

  const fmt = formatValue ?? ((v: number) => v.toFixed(0))

  return (
    <div className="bg-surface-800 border border-surface-600 rounded-xl p-4">
      <div className="text-xs text-gray-500 uppercase mb-3">{title}</div>
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
            labelFormatter={v => `${Number(v).toFixed(2)} km`}
            formatter={(v: number | undefined) => [fmt(v ?? 0) + ` ${unit}`, title]}
          />
          <Area
            type="monotone"
            dataKey="value"
            stroke={color}
            fill={`url(#${gradientId})`}
            strokeWidth={1.5}
            baseValue={reversed ? 'dataMax' : 'dataMin'}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
