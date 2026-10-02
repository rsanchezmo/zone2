import clsx from 'clsx'

export const ACTION_BASE = 'action-link text-[11px] uppercase tracking-[0.15em]'

/** Class of a neutral row action (Edit, Copy…), to match RowActions. */
export function rowActionClass(isLight: boolean, active = false): string {
  return clsx(ACTION_BASE, active ? 'text-blue-400' : isLight ? 'text-gray-400 hover:text-gray-700' : 'text-gray-500 hover:text-gray-200')
}
