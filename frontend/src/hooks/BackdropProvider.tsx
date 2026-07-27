import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  BACKDROP_MAX_OPACITY,
  BACKDROP_MIN_OPACITY,
  BACKDROP_STORAGE_KEY,
  BackdropContext,
  DEFAULT_BACKDROP,
  type BackdropCity,
  type BackdropSettings,
} from './backdropContext'

function isCity(value: unknown): value is BackdropCity {
  if (!value || typeof value !== 'object') return false
  const c = value as Record<string, unknown>
  return (
    typeof c.name === 'string' &&
    ['south', 'west', 'north', 'east'].every(k => typeof c[k] === 'number' && Number.isFinite(c[k]))
  )
}

function getInitialSettings(): BackdropSettings {
  if (typeof window === 'undefined') return DEFAULT_BACKDROP
  const raw = localStorage.getItem(BACKDROP_STORAGE_KEY)
  if (!raw) return DEFAULT_BACKDROP
  try {
    const stored = JSON.parse(raw) as Partial<BackdropSettings>
    return {
      enabled: typeof stored.enabled === 'boolean' ? stored.enabled : DEFAULT_BACKDROP.enabled,
      sport: typeof stored.sport === 'string' ? stored.sport : DEFAULT_BACKDROP.sport,
      city: isCity(stored.city) ? stored.city : null,
      color:
        typeof stored.color === 'string' && /^#[0-9a-fA-F]{6}$/.test(stored.color)
          ? stored.color
          : DEFAULT_BACKDROP.color,
      opacity:
        typeof stored.opacity === 'number' && Number.isFinite(stored.opacity)
          ? Math.min(BACKDROP_MAX_OPACITY, Math.max(BACKDROP_MIN_OPACITY, stored.opacity))
          : DEFAULT_BACKDROP.opacity,
    }
  } catch {
    return DEFAULT_BACKDROP
  }
}

export function BackdropProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<BackdropSettings>(getInitialSettings)

  useEffect(() => {
    localStorage.setItem(BACKDROP_STORAGE_KEY, JSON.stringify(settings))
  }, [settings])

  const update = useCallback(
    (patch: Partial<BackdropSettings>) => setSettings(s => ({ ...s, ...patch })),
    [],
  )

  const value = useMemo(() => ({ settings, update }), [settings, update])

  return <BackdropContext.Provider value={value}>{children}</BackdropContext.Provider>
}
