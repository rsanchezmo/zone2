import { useMemo, useState } from 'react'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import clsx from 'clsx'
import { useTheme } from '../../hooks/useTheme'

interface MethodologyProps {
  tex: string
  description: string
  accent?: string
  className?: string
}

/**
 * A collapsible methodology block: colored accent bar, rendered LaTeX formula,
 * and a plain-language explanation underneath. Starts collapsed — click to reveal.
 */
export default function Methodology({ tex, description, accent = '#60a5fa', className }: MethodologyProps) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const [open, setOpen] = useState(false)

  const html = useMemo(() => {
    try {
      return katex.renderToString(tex, { displayMode: true, throwOnError: false })
    } catch {
      return tex
    }
  }, [tex])

  return (
    <div className={clsx('my-3', className)}>
      {/* Toggle trigger */}
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className={clsx(
          'flex items-center gap-2 text-[11px] font-medium transition-colors',
          isLight ? 'text-gray-400 hover:text-gray-600' : 'text-gray-500 hover:text-gray-300',
        )}
      >
        <svg
          className={clsx('w-3 h-3 transition-transform duration-200', open && 'rotate-90')}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>
        How is this calculated?
      </button>

      {/* Collapsible content */}
      <div
        className={clsx(
          'grid transition-all duration-300 ease-out',
          open ? 'grid-rows-[1fr] opacity-100 mt-2' : 'grid-rows-[0fr] opacity-0',
        )}
      >
        <div className="overflow-hidden">
          <div
            className={clsx(
              'rounded-xl overflow-hidden',
              isLight ? 'bg-gray-50/80 border border-gray-200/80' : 'bg-surface-700/40 border border-surface-600/60',
            )}
            style={{
              borderLeftWidth: 3,
              borderLeftColor: accent,
            }}
          >
            {/* Formula */}
            <div
              className="relative px-5 pt-4 pb-2 overflow-x-auto"
              style={{ '--katex-accent': accent } as React.CSSProperties}
            >
              {/* Subtle gradient wash from accent */}
              <div
                className="absolute inset-0 pointer-events-none"
                style={{ background: `linear-gradient(135deg, ${accent}06, transparent 60%)` }}
              />
              <div
                className="relative katex-display-override"
                dangerouslySetInnerHTML={{ __html: html }}
              />
            </div>

            {/* Divider */}
            <div className={clsx('mx-5', isLight ? 'border-t border-gray-200/60' : 'border-t border-surface-600/40')} />

            {/* Description */}
            <div className={clsx(
              'px-5 py-3 text-xs leading-relaxed',
              isLight ? 'text-gray-500' : 'text-gray-400',
            )}>
              {description}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
