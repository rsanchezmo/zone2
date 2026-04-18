import { useEffect, useState } from 'react'

/**
 * Reports whether the viewport is below the Tailwind `md` breakpoint (768px).
 * Use in places where responsive behaviour can't be expressed in pure CSS —
 * e.g. Recharts axis widths, JS-driven layout decisions.
 */
export function useIsMobile(breakpoint = 768): boolean {
  const [isMobile, setIsMobile] = useState(() => {
    if (typeof window === 'undefined') return false
    return window.innerWidth < breakpoint
  })

  useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${breakpoint - 1}px)`)
    const onChange = (e: MediaQueryListEvent) => setIsMobile(e.matches)
    setIsMobile(mql.matches)
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [breakpoint])

  return isMobile
}
