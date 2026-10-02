import clsx from 'clsx'
import { useTheme } from '../../hooks/useTheme'

/** Edit / Delete controls for a list row; Delete asks for confirmation inline. */
export default function RowActions({
  isConfirming,
  onEdit,
  onConfirmDelete,
  onAskDelete,
  onCancelDelete,
}: {
  isConfirming: boolean
  onEdit: () => void
  onConfirmDelete: () => void
  onAskDelete: () => void
  onCancelDelete: () => void
}) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const actionBase = 'action-link text-[11px] uppercase tracking-[0.15em]'
  const actionClass = clsx(actionBase, isLight ? 'text-gray-400 hover:text-gray-700' : 'text-gray-500 hover:text-gray-200')
  return (
    <div className="flex items-center gap-2 shrink-0">
      {isConfirming ? (
        <>
          <span className="text-[11px] uppercase tracking-[0.15em] text-red-400">Delete?</span>
          <button onClick={onConfirmDelete} className={clsx(actionBase, 'text-red-400 hover:text-red-300 font-bold')}>Yes</button>
          <button onClick={onCancelDelete} className={actionClass}>No</button>
        </>
      ) : (
        <>
          <button onClick={onEdit} className={actionClass}>Edit</button>
          <button onClick={onAskDelete} className={clsx(actionBase, 'text-red-400/80 hover:text-red-300')}>Delete</button>
        </>
      )}
    </div>
  )
}
