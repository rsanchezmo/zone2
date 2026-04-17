import { type ReactNode, type CSSProperties } from 'react'
import clsx from 'clsx'
import { useTheme } from '../../hooks/useTheme'

interface ChartPanelProps {
  /** Uppercase micro-cap section title (e.g. "CUMULATIVE DISTANCE"). */
  title: string
  /** Optional text appended after the title, muted (e.g. sport name). */
  sublabel?: string
  /** Sport accent color — wires `--card-accent` so the hover gradient border
   *  picks it up. */
  accent?: string
  /** Right-aligned toolbar slot (chips, selects). */
  toolbar?: ReactNode
  /** Legend row under the header. Keep to small pill/swatch items. */
  legend?: ReactNode
  /** Status pill slot — rendered inline next to title (for goal state, etc). */
  status?: ReactNode
  /** Extra content that appears BELOW the chart (e.g. a hint/caption). */
  footer?: ReactNode
  /** Chart or content. */
  children: ReactNode
  /** Additional class on the outer panel. */
  className?: string
  /** Accent gradient border on hover — default true. */
  glow?: boolean
}

/**
 * Shared wrapper for dashboard chart sections.
 *
 *  - Enforces consistent header (title / sublabel / status / toolbar / legend).
 *  - Hairline bordered panel (reuses `.panel` + optional `.chart-card` glow).
 *  - Sport accent threaded via --card-accent for the decorative hover border.
 */
export default function ChartPanel({
  title,
  sublabel,
  accent,
  toolbar,
  legend,
  status,
  footer,
  children,
  className,
  glow = true,
}: ChartPanelProps) {
  const { theme } = useTheme()
  const isLight = theme === 'light'

  const style: CSSProperties | undefined = accent
    ? ({ ['--card-accent' as string]: accent } as CSSProperties)
    : undefined

  return (
    <section
      className={clsx(
        'panel p-5',
        glow && 'chart-card',
        isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600',
        className,
      )}
      style={style}
    >
      <header className="flex items-start justify-between gap-3 flex-wrap mb-4">
        <div className="flex items-center gap-3 min-w-0">
          <h3 className="eyebrow truncate">
            {title}
            {sublabel && (
              <span className={clsx('ml-2 normal-case tracking-normal font-medium', isLight ? 'text-gray-400' : 'text-gray-500')}>
                {sublabel}
              </span>
            )}
          </h3>
          {status}
        </div>
        {toolbar && <div className="flex items-center gap-1.5 shrink-0">{toolbar}</div>}
      </header>

      {legend && (
        <div className="flex items-center flex-wrap gap-x-4 gap-y-1 mb-3">{legend}</div>
      )}

      {children}

      {footer && <div className="mt-3 pt-3 border-t border-dashed border-surface-600/50">{footer}</div>}
    </section>
  )
}

/**
 * Small reusable legend swatch used inside ChartPanel's `legend` slot.
 * Keeps the look consistent between chart panels without forcing them to
 * re-implement swatch + caption markup each time.
 */
export function LegendSwatch({
  color,
  label,
  variant = 'solid',
}: {
  color: string
  label: string
  variant?: 'solid' | 'dashed' | 'outline'
}) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] text-gray-500">
      {variant === 'solid' && (
        <span className="w-3 h-0.5 rounded-sm" style={{ backgroundColor: color }} />
      )}
      {variant === 'dashed' && (
        <span className="w-3 h-0 border-t border-dashed" style={{ borderColor: color }} />
      )}
      {variant === 'outline' && (
        <span className="w-3 h-2 rounded-sm border" style={{ borderColor: color }} />
      )}
      <span>{label}</span>
    </span>
  )
}
