import { useEffect, useRef, useState } from 'react'
import { useTheme } from '../../hooks/useTheme'

interface GoalRingProps {
  /** Progress value [0..1]. Values above 1 are clamped for the arc but the
   *  center content can still show the overshoot via `current`/`target`. */
  progress: number
  /** Where we "should be" today, [0..1]. Rendered as a thin pace marker
   *  on the ring so the user can see ahead/behind-schedule at a glance. */
  pace?: number
  /** Sport-color stroke. */
  accent: string
  /** Diameter in px. Default 260. */
  size?: number
  /** Arc stroke width. Default 10. */
  stroke?: number
  /** Optional label rendered above the center value (micro-cap). */
  label?: string
  /** Big central value (formatted). */
  value: string
  /** Denominator rendered beneath the value (e.g. "/ 1 200 km"). */
  subValue?: string
  /** Status chip beneath subValue (e.g. "On track"). */
  status?: { label: string; tone: 'accent' | 'positive' | 'negative' | 'neutral' }
}

/**
 * Speedometer-style progress ring.
 *
 *  - Outer tick marks at 0 / 25 / 50 / 75 / 100% read like instrument graduations.
 *  - Pace marker (optional) shows today's expected position — ahead/behind
 *    at a glance without reading a number.
 *  - Arc animates from 0 on mount (prefers-reduced-motion respected).
 *  - Accent is applied as a CSS var so the ring can glow in sport-color
 *    via the surrounding hero-brackets treatment.
 */
export default function GoalRing({
  progress,
  pace,
  accent,
  size = 260,
  stroke = 10,
  label,
  value,
  subValue,
  status,
}: GoalRingProps) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const trackColor = isLight ? '#e5e5e5' : '#1e1e1e'
  const tickColor = isLight ? '#d1d5db' : '#2a2a2a'

  // Arc mount animation — from 0 to target over ~900ms. Tracked in JS so we
  // can respect prefers-reduced-motion cleanly.
  const [animated, setAnimated] = useState(0)
  const rafRef = useRef<number | null>(null)
  useEffect(() => {
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduce) {
      rafRef.current = requestAnimationFrame(() => setAnimated(progress))
      return () => {
        if (rafRef.current !== null) cancelAnimationFrame(rafRef.current)
      }
    }
    const start = performance.now()
    const DURATION = 900
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / DURATION)
      // easeOutCubic
      const eased = 1 - Math.pow(1 - t, 3)
      setAnimated(progress * eased)
      if (t < 1) rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current)
    }
  }, [progress])

  const radius = size / 2
  const arcR = radius - stroke - 6 // leave 6px for outer tick marks
  const circumference = 2 * Math.PI * arcR
  const clampedAnimated = Math.min(Math.max(animated, 0), 1)
  const dash = circumference * clampedAnimated
  const overshoot = progress > 1

  // Tick positions: 0% (top), 25 (right), 50 (bottom), 75 (left), 100 (same as 0 but longer).
  const tickAnglesDeg = [0, 90, 180, 270]
  const paceAngleDeg = pace !== undefined ? Math.min(Math.max(pace, 0), 1) * 360 : null

  // Helper: convert [0..1] progress to SVG angle.
  // SVG circles start at 3 o'clock and go clockwise; we want 12 o'clock start, clockwise.
  const polarToCartesian = (cx: number, cy: number, r: number, angleDeg: number) => {
    const angleRad = ((angleDeg - 90) * Math.PI) / 180
    return { x: cx + r * Math.cos(angleRad), y: cy + r * Math.sin(angleRad) }
  }

  const statusTone = status
    ? {
        accent: { bg: `${accent}22`, color: accent, border: `${accent}55` },
        positive: { bg: 'rgba(34, 197, 94, 0.12)', color: '#4ade80', border: 'rgba(34, 197, 94, 0.3)' },
        negative: { bg: 'rgba(239, 68, 68, 0.12)', color: '#f87171', border: 'rgba(239, 68, 68, 0.3)' },
        neutral: { bg: isLight ? '#f3f4f6' : '#1e1e1e', color: isLight ? '#4b5563' : '#9ca3af', border: 'transparent' },
      }[status.tone]
    : null

  return (
    <div
      className="relative inline-flex items-center justify-center"
      style={{ width: size, height: size, ['--card-accent' as string]: accent }}
    >
      {/* Outer radial tick marks — speedometer graduations */}
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        className="absolute inset-0 pointer-events-none"
        aria-hidden="true"
      >
        {/* Four major ticks at cardinal points */}
        {tickAnglesDeg.map(deg => {
          const outer = polarToCartesian(radius, radius, arcR + 10, deg)
          const inner = polarToCartesian(radius, radius, arcR + 4, deg)
          return (
            <line
              key={deg}
              x1={inner.x}
              y1={inner.y}
              x2={outer.x}
              y2={outer.y}
              stroke={tickColor}
              strokeWidth={1.25}
              strokeLinecap="round"
            />
          )
        })}
        {/* Eight minor ticks between majors (every 45°, offset by 22.5° from majors would be odd; use 30° granularity except at cardinals) */}
        {[30, 60, 120, 150, 210, 240, 300, 330].map(deg => {
          const outer = polarToCartesian(radius, radius, arcR + 8, deg)
          const inner = polarToCartesian(radius, radius, arcR + 5, deg)
          return (
            <line
              key={deg}
              x1={inner.x}
              y1={inner.y}
              x2={outer.x}
              y2={outer.y}
              stroke={tickColor}
              strokeWidth={1}
              strokeLinecap="round"
              opacity={0.55}
            />
          )
        })}

        {/* Track (full ring, muted) */}
        <circle
          cx={radius}
          cy={radius}
          r={arcR}
          fill="none"
          stroke={trackColor}
          strokeWidth={stroke}
        />

        {/* Progress arc */}
        <g transform={`rotate(-90 ${radius} ${radius})`}>
          <circle
            cx={radius}
            cy={radius}
            r={arcR}
            fill="none"
            stroke={accent}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={`${dash} ${circumference}`}
            style={overshoot ? { filter: `drop-shadow(0 0 6px ${accent}99)` } : undefined}
          />
        </g>

        {/* Pace marker — thin tick on the arc track at "where we should be" */}
        {paceAngleDeg !== null && (() => {
          const outer = polarToCartesian(radius, radius, arcR + (stroke / 2) + 1, paceAngleDeg)
          const inner = polarToCartesian(radius, radius, arcR - (stroke / 2) - 1, paceAngleDeg)
          return (
            <line
              x1={inner.x}
              y1={inner.y}
              x2={outer.x}
              y2={outer.y}
              stroke={isLight ? '#111827' : '#f3f4f6'}
              strokeWidth={1.5}
              strokeLinecap="round"
              opacity={0.75}
            />
          )
        })()}
      </svg>

      {/* Center content */}
      <div className="relative z-10 flex flex-col items-center text-center px-6 select-none">
        {label && (
          <div className="text-[10px] uppercase tracking-[0.2em] text-gray-500 mb-2">
            {label}
          </div>
        )}
        <div
          className="font-mono tabular-nums font-semibold leading-none tracking-tight"
          style={{
            fontSize: size * 0.19,
            color: isLight ? '#0f172a' : '#f3f4f6',
            letterSpacing: '-0.02em',
          }}
        >
          {value}
        </div>
        {subValue && (
          <div className="mt-2 text-xs font-mono tabular-nums text-gray-500">
            {subValue}
          </div>
        )}
        {status && statusTone && (
          <div
            className="mt-3 inline-flex items-center gap-1.5 text-[10px] uppercase tracking-[0.15em] font-semibold px-2 py-1 rounded-full border"
            style={{
              backgroundColor: statusTone.bg,
              color: statusTone.color,
              borderColor: statusTone.border,
            }}
          >
            <span
              className="inline-block w-1.5 h-1.5 rounded-full"
              style={{ backgroundColor: statusTone.color }}
            />
            {status.label}
          </div>
        )}
      </div>
    </div>
  )
}
