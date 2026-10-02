import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import clsx from 'clsx'
import { useTheme } from '../../hooks/useTheme'
import { useEscapeKey } from '../../hooks/useEscapeKey'

/** A dialog centred over a dimmed backdrop; the backdrop and Escape close it.
 *  `className` sizes the panel (width, padding). */
export default function Modal({ onClose, className, children }: {
  onClose: () => void
  className?: string
  children: ReactNode
}) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  useEscapeKey(true, onClose)
  return createPortal(
    <div
      className={clsx('fixed inset-0 p-4 flex items-center justify-center z-[10001] animate-[fadeIn_150ms_ease-out]', isLight ? 'bg-black/30' : 'bg-black/60')}
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        className={clsx(
          'border rounded-xl w-full overflow-y-auto animate-[scaleIn_150ms_ease-out]',
          isLight ? 'bg-white border-gray-200 shadow-xl' : 'bg-surface-800 border-surface-600 shadow-2xl',
          className,
        )}
        onClick={e => e.stopPropagation()}
      >
        {children}
      </div>
    </div>,
    document.body,
  )
}
