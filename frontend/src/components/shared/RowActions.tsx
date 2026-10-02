import type { ReactNode } from 'react'
import clsx from 'clsx'
import { useTheme } from '../../hooks/useTheme'
import { ACTION_BASE, rowActionClass } from './rowActionClass'

/** Edit / Delete controls for a list row; Delete asks for confirmation inline.
 *  `extra` actions (built with `rowActionClass`) come first. */
export default function RowActions({
  isConfirming,
  onEdit,
  onConfirmDelete,
  onAskDelete,
  onCancelDelete,
  extra,
}: {
  isConfirming: boolean
  onEdit: () => void
  onConfirmDelete: () => void
  onAskDelete: () => void
  onCancelDelete: () => void
  extra?: ReactNode
}) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const actionClass = rowActionClass(isLight)
  return (
    <div className="flex items-center gap-2 shrink-0">
      {isConfirming ? (
        <>
          <span className="text-[11px] uppercase tracking-[0.15em] text-red-400">Delete?</span>
          <button onClick={onConfirmDelete} className={clsx(ACTION_BASE, 'text-red-400 hover:text-red-300 font-bold')}>Yes</button>
          <button onClick={onCancelDelete} className={actionClass}>No</button>
        </>
      ) : (
        <>
          {extra}
          <button onClick={onEdit} className={actionClass}>Edit</button>
          <button onClick={onAskDelete} className={clsx(ACTION_BASE, 'text-red-400/80 hover:text-red-300')}>Delete</button>
        </>
      )}
    </div>
  )
}
