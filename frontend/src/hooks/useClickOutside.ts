import { useEffect, useEffectEvent, type RefObject } from 'react'

/** Call `onOutside` on a mouse press outside `ref` while `active` (a popover or menu open). */
export function useClickOutside(ref: RefObject<HTMLElement | null>, active: boolean, onOutside: () => void): void {
  const handle = useEffectEvent((e: MouseEvent) => {
    if (ref.current && !ref.current.contains(e.target as Node)) onOutside()
  })
  useEffect(() => {
    if (!active) return
    const onMouseDown = (e: MouseEvent) => handle(e)
    document.addEventListener('mousedown', onMouseDown)
    return () => document.removeEventListener('mousedown', onMouseDown)
  }, [active])
}
