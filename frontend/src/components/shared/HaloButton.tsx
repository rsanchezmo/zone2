import type { ButtonHTMLAttributes } from 'react'
import clsx from 'clsx'

/** The app's pill in one colour: tinted fill and border, coloured caps and a dot. */
export default function HaloButton({ color, className, children, ...props }:
  ButtonHTMLAttributes<HTMLButtonElement> & { color: string }) {
  return (
    <button
      {...props}
      className={clsx(
        'inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-full border px-3 py-1.5',
        'text-[11px] uppercase tracking-[0.15em] font-semibold transition-colors hover:brightness-125 disabled:opacity-60',
        className,
      )}
      style={{ color, borderColor: `${color}50`, backgroundColor: `${color}15` }}
    >
      <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: color }} aria-hidden="true" />
      {children}
    </button>
  )
}
