import { useSyncExternalStore } from 'react'

function subscribe(onChange: () => void): () => void {
  document.addEventListener('visibilitychange', onChange)
  return () => document.removeEventListener('visibilitychange', onChange)
}

function visible(): boolean {
  return document.visibilityState === 'visible'
}

/** Whether the page's tab is the one on screen. */
export function usePageVisible(): boolean {
  return useSyncExternalStore(subscribe, visible)
}
