import type { ReactNode } from 'react'
import clsx from 'clsx'

export type PillTone = 'good' | 'warn' | 'bad' | 'neutral'

const TONE_CLASS: Record<PillTone, string> = {
  good: 'text-emerald-400 border-emerald-400/40',
  warn: 'text-amber-400 border-amber-400/40',
  bad: 'text-rose-400 border-rose-400/40',
  neutral: 'text-gray-500 border-surface-500',
}

const SIZE_CLASS = {
  sm: 'text-[8.5px] tracking-[0.12em] px-1.5',
  md: 'text-[10px] tracking-[0.15em] px-2',
} as const

/** Small uppercase status label, coloured by a semantic tone or by an accent. */
export default function StatusPill({ children, tone = 'neutral', accent, size = 'sm', className }: {
  children: ReactNode
  tone?: PillTone
  /** Overrides the tone with this colour, e.g. the sport's. */
  accent?: string
  size?: keyof typeof SIZE_CLASS
  className?: string
}) {
  return (
    <span
      className={clsx(
        'uppercase font-semibold py-0.5 rounded-full border whitespace-nowrap',
        SIZE_CLASS[size],
        !accent && TONE_CLASS[tone],
        className,
      )}
      style={accent ? { color: accent, borderColor: `${accent}60`, backgroundColor: `${accent}15` } : undefined}
    >
      {children}
    </span>
  )
}
