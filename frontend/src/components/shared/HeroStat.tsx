import clsx from 'clsx'
import { useTheme } from '../../hooks/useTheme'

export interface HeroStatProps {
  label: string
  value: string
  unit?: string
  footnote?: string
  accent?: string
  tone?: 'accent' | 'positive' | 'negative' | 'neutral'
}

/** A supporting stat beside a hero ring: label, big value, unit and footnote. */
export default function HeroStat({ label, value, unit, footnote, accent, tone = 'neutral' }: HeroStatProps) {
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
        <div className={clsx('text-[11px] mt-1', 'text-gray-500')}>{footnote}</div>
      )}
    </div>
  )
}

