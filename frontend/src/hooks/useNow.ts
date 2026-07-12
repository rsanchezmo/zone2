import { useEffect, useState } from 'react'

/** Current epoch milliseconds, refreshed every `intervalMs` — lets elapsed-time
 *  displays tick without impure Date.now() calls during render. */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])
  return now
}
