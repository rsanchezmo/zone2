import { createContext } from 'react'

/** Bounding box of the city the backdrop is framed on, resolved via geocoding. */
export interface BackdropCity {
  name: string
  south: number
  west: number
  north: number
  east: number
}

export interface BackdropSettings {
  enabled: boolean
  /** Empty string means every sport. */
  sport: string
  /** Null frames the backdrop on every route, wherever they are. */
  city: BackdropCity | null
  color: string
  opacity: number
}

export interface BackdropContextValue {
  settings: BackdropSettings
  update: (patch: Partial<BackdropSettings>) => void
}

export const BACKDROP_STORAGE_KEY = 'route-backdrop'

export const BACKDROP_MIN_OPACITY = 0.02
export const BACKDROP_MAX_OPACITY = 0.35

export const DEFAULT_BACKDROP: BackdropSettings = {
  enabled: false,
  sport: '',
  city: null,
  color: '#fc0101',
  opacity: 0.12,
}

export const BackdropContext = createContext<BackdropContextValue | null>(null)
