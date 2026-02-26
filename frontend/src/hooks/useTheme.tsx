import { createContext, useContext, useState, useEffect, useMemo, type ReactNode } from 'react'

type Theme = 'dark' | 'light'

interface ThemeColors {
  tooltipBg: string
  tooltipBorder: string
  tickFill: string
  tickFillSecondary: string
  gridStroke: string
  mapBg: string
  labelColor: string
}

interface ThemeContextValue {
  theme: Theme
  toggleTheme: () => void
  colors: ThemeColors
}

const DARK_COLORS: ThemeColors = {
  tooltipBg: '#0a0a0a',
  tooltipBorder: '#1a1a1a',
  tickFill: '#9ca3af',
  tickFillSecondary: '#6b7280',
  gridStroke: 'rgba(255,255,255,0.04)',
  mapBg: '#000',
  labelColor: '#9ca3af',
}

const LIGHT_COLORS: ThemeColors = {
  tooltipBg: '#fff',
  tooltipBorder: '#e5e5e5',
  tickFill: '#6b7280',
  tickFillSecondary: '#374151',
  gridStroke: 'rgba(0,0,0,0.06)',
  mapBg: '#fafafa',
  labelColor: '#6b7280',
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

function getInitialTheme(): Theme {
  if (typeof window === 'undefined') return 'dark'
  const stored = localStorage.getItem('theme')
  if (stored === 'light' || stored === 'dark') return stored
  return 'dark'
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(getInitialTheme)

  useEffect(() => {
    const root = document.documentElement
    if (theme === 'light') {
      root.classList.add('light')
    } else {
      root.classList.remove('light')
    }
    localStorage.setItem('theme', theme)
  }, [theme])

  const toggleTheme = () => setTheme(t => (t === 'dark' ? 'light' : 'dark'))

  const colors = useMemo(() => (theme === 'dark' ? DARK_COLORS : LIGHT_COLORS), [theme])

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme, colors }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider')
  return ctx
}
