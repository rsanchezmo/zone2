import { useContext } from 'react'
import { BackdropContext, type BackdropContextValue } from './backdropContext'

export function useBackdrop(): BackdropContextValue {
  const ctx = useContext(BackdropContext)
  if (!ctx) throw new Error('useBackdrop must be used within BackdropProvider')
  return ctx
}
