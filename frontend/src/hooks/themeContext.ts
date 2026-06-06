import { createContext } from 'react'

export type Theme = 'dark' | 'light'

export interface ThemeColors {
  tooltipBg: string
  tooltipBorder: string
  tickFill: string
  tickFillSecondary: string
  gridStroke: string
  mapBg: string
  labelColor: string
}

export interface ThemeContextValue {
  theme: Theme
  toggleTheme: () => void
  colors: ThemeColors
}

export const DARK_COLORS: ThemeColors = {
  tooltipBg: '#0a0a0a',
  tooltipBorder: '#1a1a1a',
  tickFill: '#9ca3af',
  tickFillSecondary: '#6b7280',
  gridStroke: 'rgba(255,255,255,0.04)',
  mapBg: '#000',
  labelColor: '#9ca3af',
}

export const LIGHT_COLORS: ThemeColors = {
  tooltipBg: '#fff',
  tooltipBorder: '#e5e5e5',
  tickFill: '#6b7280',
  tickFillSecondary: '#374151',
  gridStroke: 'rgba(0,0,0,0.06)',
  mapBg: '#fafafa',
  labelColor: '#6b7280',
}

export const ThemeContext = createContext<ThemeContextValue | null>(null)
