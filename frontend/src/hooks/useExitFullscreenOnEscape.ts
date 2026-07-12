import { useEffect } from 'react'

/** Close a fullscreen map on Escape while it is expanded. */
export function useExitFullscreenOnEscape(expanded: boolean, exit: () => void): void {
  useEffect(() => {
    if (!expanded) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') exit() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [expanded, exit])
}
