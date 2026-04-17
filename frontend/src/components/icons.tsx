/**
 * Minimal inline icon set — matches the existing stroke aesthetic
 * (1.5 stroke, round caps/joins) used elsewhere in the app. Kept as
 * plain function components so there's no runtime dep overhead.
 *
 * Every icon accepts a `size` prop (default 14) and a `className`.
 * Fill is `none`; stroke is `currentColor`, so the parent controls
 * color via Tailwind text-* / inline style.
 */

import type { SVGProps } from 'react'

export interface IconProps extends Omit<SVGProps<SVGSVGElement>, 'width' | 'height'> {
  size?: number
}

function Svg({ size = 14, children, ...props }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {children}
    </svg>
  )
}

// ── Activity metadata icons ─────────────────────────

export function DeviceIcon(p: IconProps) {
  return <Svg {...p}><rect x="4.5" y="1.5" width="7" height="13" rx="1.5" /><path d="M7.5 12.5h1" /></Svg>
}

export function ShoeIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M1.5 11.5h11a2 2 0 002-2v-.3a1 1 0 00-.55-.9L10 6.5l-2.5 1-2-2H3a1.5 1.5 0 00-1.5 1.5v3a1 1 0 001 1z" />
      <path d="M5 8.5l-1 1" />
    </Svg>
  )
}

export function ThermometerIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M8 1.5v8" />
      <circle cx="8" cy="11.5" r="2.5" />
      <path d="M8 9v-2.5" strokeWidth={3} strokeLinecap="round" />
    </Svg>
  )
}

export function ClockIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <circle cx="8" cy="8" r="6.25" />
      <path d="M8 4.5V8l2.5 1.5" />
    </Svg>
  )
}

export function DumbbellIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M3 5v6M5 3v10M11 3v10M13 5v6M5 8h6" />
    </Svg>
  )
}

export function MedalIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M5 1.5l-1.5 4M11 1.5l1.5 4" />
      <circle cx="8" cy="10" r="4" />
      <path d="M8 8v2l1.2.7" />
    </Svg>
  )
}

export function TrophyIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M4 2h8v3a4 4 0 01-8 0V2z" />
      <path d="M4 3.5H2.5a1.5 1.5 0 001.5 1.5M12 3.5h1.5a1.5 1.5 0 01-1.5 1.5" />
      <path d="M6.5 14.5h3M8 9v5.5" />
    </Svg>
  )
}

export function FlagIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M3 14.5V1.5M3 2l6 1.5L3 8z" />
    </Svg>
  )
}

export function CheckIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M3 8.5l3 3 7-7" />
    </Svg>
  )
}

// ── Metric icons (session / goal / score) ───────────

export function DistanceIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M2 8h12" />
      <path d="M4 5.5L1.5 8 4 10.5M12 5.5L14.5 8 12 10.5" />
    </Svg>
  )
}

export function TimerIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M6 1.5h4" />
      <circle cx="8" cy="9.5" r="5" />
      <path d="M8 6.5V9.5l2 1.5" />
    </Svg>
  )
}

export function BoltIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M9 1.5L3 9h4l-1 5.5L12 7H8z" />
    </Svg>
  )
}

export function RangeIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M8 2v12" />
      <path d="M5.5 4L8 1.5 10.5 4M5.5 12L8 14.5 10.5 12" />
    </Svg>
  )
}

export function HeartIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M8 13.5S1.5 10 1.5 5.75A3.25 3.25 0 018 4.25a3.25 3.25 0 016.5 1.5C14.5 10 8 13.5 8 13.5z" />
    </Svg>
  )
}

// ── External link (used for race site URLs, etc.) ───

export function ExternalLinkIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M9 2h5v5M14 2L7.5 8.5M12 9v4a1 1 0 01-1 1H3a1 1 0 01-1-1V5a1 1 0 011-1h4" />
    </Svg>
  )
}
