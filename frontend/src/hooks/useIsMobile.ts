import { useCallback, useSyncExternalStore } from 'react'

/**
 * Reports whether the viewport is below the Tailwind `md` breakpoint (768px).
 * Use in places where responsive behaviour can't be expressed in pure CSS —
 * e.g. Recharts axis widths, JS-driven layout decisions.
 */
export function useIsMobile(breakpoint = 768): boolean {
  const getSnapshot = useCallback(() => {
    if (typeof window === 'undefined') return false
    return window.matchMedia(`(max-width: ${breakpoint - 1}px)`).matches
  }, [breakpoint])

  const subscribe = useCallback((onStoreChange: () => void) => {
    if (typeof window === 'undefined') return () => {}
    const mql = window.matchMedia(`(max-width: ${breakpoint - 1}px)`)
    const onChange = () => onStoreChange()
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [breakpoint])

  return useSyncExternalStore(subscribe, getSnapshot, () => false)
}
