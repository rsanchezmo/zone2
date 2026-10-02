import clsx from 'clsx'
import type { RateLimits as RateLimitsData } from '../../api/hooks'
import ChartPanel from '../shared/ChartPanel'
import { useTheme } from '../../hooks/useTheme'

export default function RateLimits({ limits: rateLimits }: { limits: RateLimitsData | undefined }) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  if (!rateLimits) return null

  return (
    <ChartPanel
      title="Strava API rate limits"
      glow={false}
      footer={
        <span className={clsx('text-[11px]', isLight ? 'text-gray-500' : 'text-gray-500')}>
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
                <span className={clsx('eyebrow', isLight ? 'text-gray-500' : 'text-gray-500')}>{label}</span>
                <span className="text-sm font-mono tabular-nums font-semibold" style={{ color: barColor }}>
                  {data.usage.toLocaleString()} <span className={isLight ? 'text-gray-400' : 'text-gray-500'}>/</span> {data.limit.toLocaleString()}
                </span>
              </div>
              <div className={clsx('h-2 rounded-full overflow-hidden', isLight ? 'bg-gray-100' : 'bg-surface-700')}>
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
