import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { useTheme } from '../../hooks/useTheme'

interface ElevationChartProps {
  data: { distance: number; altitude: number }[]
}

export default function ElevationChart({ data }: ElevationChartProps) {
  const { colors } = useTheme()

  // Downsample if too many points
  const maxPoints = 300
  let chartData = data
  if (data.length > maxPoints) {
    const step = Math.ceil(data.length / maxPoints)
    chartData = data.filter((_, i) => i % step === 0)
  }

  return (
    <ResponsiveContainer width="100%" height={150}>
      <AreaChart data={chartData} margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="elevGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#fc0101" stopOpacity={0.3} />
            <stop offset="95%" stopColor="#fc0101" stopOpacity={0} />
          </linearGradient>
        </defs>
        <XAxis
          dataKey="distance"
          tick={{ fill: colors.tickFill, fontSize: 10 }}
          tickFormatter={v => `${v.toFixed(1)}`}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          tick={{ fill: colors.tickFill, fontSize: 10 }}
          axisLine={false}
          tickLine={false}
          domain={['dataMin - 10', 'dataMax + 10']}
        />
        <Tooltip
          contentStyle={{ background: colors.tooltipBg, border: `1px solid ${colors.tooltipBorder}`, borderRadius: 8 }}
          labelStyle={{ color: colors.labelColor }}
          itemStyle={{ color: colors.labelColor }}
          labelFormatter={v => `${Number(v).toFixed(2)} km`}
          formatter={(v: number | undefined) => [`${(v ?? 0).toFixed(0)} m`, 'Elevation']}
        />
        <Area
          type="monotone"
          dataKey="altitude"
          stroke="#fc0101"
          fill="url(#elevGrad)"
          strokeWidth={1.5}
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}
