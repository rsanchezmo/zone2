import type { RateLimits as RateLimitsData } from '../../api/athlete'
import ChartPanel from '../shared/ChartPanel'

export default function RateLimits({ limits: rateLimits }: { limits: RateLimitsData | undefined }) {
  if (!rateLimits) return null

  return (
    <ChartPanel
      title="Strava API rate limits"
      glow={false}
      footer={
        <span className="text-[11px] text-gray-500">
          Daily limit resets at midnight UTC
        </span>
      }
    >
      <div className="space-y-3">
        {[
          { label: '15-minute', data: rateLimits.fifteen_min },
          { label: 'Daily', data: rateLimits.daily },
        ].map(({ label, data }) => {
          const pct = data.limit > 0 ? (data.usage / data.limit) * 100 : 0
          const isOver = data.usage >= data.limit
          const isWarning = pct >= 80
          const barColor = isOver ? '#ef4444' : isWarning ? '#eab308' : '#22c55e'
          return (
            <div key={label}>
              <div className="flex items-center justify-between mb-1.5">
                <span className="eyebrow text-gray-500">{label}</span>
                <span className="text-sm font-mono tabular-nums font-semibold" style={{ color: barColor }}>
                  {data.usage.toLocaleString()} <span className="text-fg-subtle">/</span> {data.limit.toLocaleString()}
                </span>
              </div>
              <div className="h-2 rounded-full overflow-hidden bg-surface-700">
                <div
                  className="h-full rounded-full transition-all"
                  style={{ width: `${Math.min(pct, 100)}%`, backgroundColor: barColor }}
                />
              </div>
            </div>
          )
        })}
      </div>
    </ChartPanel>
  )
}
