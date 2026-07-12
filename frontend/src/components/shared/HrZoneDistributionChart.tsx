import { memo, useEffect, useMemo, useRef, useState } from 'react'
import clsx from 'clsx'
import { useTheme } from '../../hooks/useTheme'
import type { HrHistogram } from './hrHistogram'

type Zone = { min: number; max: number }

interface Props {
  /** Integer-bpm histogram. counts[i] is the sample count at bpm = minBpm + i. */
  histogram: HrHistogram
  /** Five zones (Z1–Z5). Boundary at zones[i].max == zones[i+1].min is assumed. */
  zones: Zone[]
  /** Pre-computed zone percentages (1..5). Falls back to deriving them from the histogram. */
  percentages?: number[]
  /** Total chart height in px. */
  height?: number
  className?: string
}

const ZONE_COLORS = ['#6b7280', '#3b82f6', '#22c55e', '#eab308', '#ef4444']
const FILL_OPACITY = 0.22
const BAND_OPACITY = 0.08

function gaussianSmooth(counts: number[], sigma: number): number[] {
  if (sigma <= 0 || counts.length === 0) return counts.slice()
  const radius = Math.max(1, Math.ceil(sigma * 3))
  const kernel: number[] = []
  let sum = 0
  for (let k = -radius; k <= radius; k++) {
    const w = Math.exp(-(k * k) / (2 * sigma * sigma))
    kernel.push(w)
    sum += w
  }
  for (let i = 0; i < kernel.length; i++) kernel[i] /= sum
  const n = counts.length
  const out = new Array<number>(n).fill(0)
  for (let i = 0; i < n; i++) {
    let acc = 0
    for (let k = -radius; k <= radius; k++) {
      const j = i + k
      if (j >= 0 && j < n) acc += counts[j] * kernel[k + radius]
    }
    out[i] = acc
  }
  return out
}

function HrZoneDistributionChart({
  histogram,
  zones,
  percentages,
  height = 180,
  className,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(640)
  const { theme } = useTheme()
  const isLight = theme === 'light'

  useEffect(() => {
    if (!containerRef.current) return
    const el = containerRef.current
    const ro = new ResizeObserver(entries => {
      const w = entries[0]?.contentRect.width ?? 0
      if (w > 0) setWidth(w)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const computed = useMemo(() => {
    if (!histogram || histogram.counts.length === 0 || zones.length < 5) return null
    const minBpm = histogram.minBpm
    const dataHi = minBpm + histogram.counts.length
    // X range: ensure both Z1/Z2 and Z4/Z5 boundaries are visible
    const lo = Math.min(minBpm, zones[0].max - 5)
    const hi = Math.max(dataHi, zones[3].max + 10)
    const range = hi - lo
    if (range <= 0) return null

    const smoothed = gaussianSmooth(histogram.counts, 3)

    const points: { bpm: number; v: number }[] = []
    for (let bpm = lo; bpm <= hi; bpm++) {
      const idx = bpm - minBpm
      const v = idx >= 0 && idx < smoothed.length ? smoothed[idx] : 0
      points.push({ bpm, v })
    }
    let ymax = 0
    for (const p of points) if (p.v > ymax) ymax = p.v
    if (ymax === 0) ymax = 1

    let pcts = percentages
    if (!pcts) {
      const total = histogram.counts.reduce((a, b) => a + b, 0) || 1
      const zoneCounts = [0, 0, 0, 0, 0]
      for (let i = 0; i < histogram.counts.length; i++) {
        const bpm = minBpm + i
        let zi = 4
        for (let k = 0; k < 4; k++) if (bpm < zones[k].max) { zi = k; break }
        zoneCounts[zi] += histogram.counts[i]
      }
      pcts = zoneCounts.map(c => Math.round((c / total) * 1000) / 10)
    }

    return { lo, hi, range, points, ymax, pcts }
  }, [histogram, zones, percentages])

  if (!computed) return null
  const { lo, hi, points, ymax, pcts } = computed

  // Boundaries: 4 split points at zones[k].max for k=0..3
  const splits = [zones[0].max, zones[1].max, zones[2].max, zones[3].max]
  // Segment ranges (bpm): [lo, splits[0]], [splits[0], splits[1]], …, [splits[3], hi]
  const segments: [number, number][] = [
    [lo, splits[0]],
    [splits[0], splits[1]],
    [splits[1], splits[2]],
    [splits[2], splits[3]],
    [splits[3], hi],
  ]

  const padX = 8
  const padTop = 6
  const padBottom = 22
  const innerW = Math.max(0, width - padX * 2)
  const innerH = Math.max(0, height - padTop - padBottom)
  const baseY = padTop + innerH

  const xScale = (bpm: number) => padX + ((bpm - lo) / (hi - lo)) * innerW
  const yScale = (v: number) => padTop + innerH - (v / ymax) * innerH

  const tickColor = isLight ? '#6b7280' : '#9ca3af'
  const axisColor = isLight ? '#9ca3af' : '#4b5563'

  const segPaths = segments.map(([a, b], zi) => {
    const seg = points.filter(p => p.bpm >= a && p.bpm <= b)
    if (seg.length < 2) return null
    const linePath = seg
      .map((p, i) => `${i === 0 ? 'M' : 'L'}${xScale(p.bpm).toFixed(2)},${yScale(p.v).toFixed(2)}`)
      .join(' ')
    const fillPath =
      `M${xScale(seg[0].bpm).toFixed(2)},${baseY.toFixed(2)} ` +
      seg.map(p => `L${xScale(p.bpm).toFixed(2)},${yScale(p.v).toFixed(2)}`).join(' ') +
      ` L${xScale(seg[seg.length - 1].bpm).toFixed(2)},${baseY.toFixed(2)} Z`
    return { zi, linePath, fillPath }
  }).filter((s): s is { zi: number; linePath: string; fillPath: string } => s !== null)

  return (
    <div ref={containerRef} className={clsx('w-full select-none', className)}>
      <svg width={width} height={height} role="img" aria-label="HR zone distribution">
        {/* Zone background bands */}
        {segments.map(([a, b], zi) => {
          const x1 = xScale(a)
          const x2 = xScale(b)
          return (
            <rect
              key={`band-${zi}`}
              x={x1}
              y={padTop}
              width={Math.max(0, x2 - x1)}
              height={innerH}
              fill={ZONE_COLORS[zi]}
              opacity={BAND_OPACITY}
            />
          )
        })}

        {/* Boundary dashed lines */}
        {splits.map((bpm, i) => {
          const x = xScale(bpm)
          return (
            <line
              key={`bl-${i}`}
              x1={x}
              x2={x}
              y1={padTop}
              y2={padTop + innerH}
              stroke={axisColor}
              strokeOpacity={0.5}
              strokeDasharray="2 3"
              strokeWidth={1}
            />
          )
        })}

        {/* Filled curves per zone */}
        {segPaths.map(zp => (
          <path key={`f-${zp.zi}`} d={zp.fillPath} fill={ZONE_COLORS[zp.zi]} opacity={FILL_OPACITY} />
        ))}

        {/* Stroke curves per zone */}
        {segPaths.map(zp => (
          <path
            key={`s-${zp.zi}`}
            d={zp.linePath}
            stroke={ZONE_COLORS[zp.zi]}
            strokeWidth={1.75}
            strokeLinejoin="round"
            fill="none"
          />
        ))}

        {/* Baseline */}
        <line
          x1={padX}
          x2={padX + innerW}
          y1={baseY}
          y2={baseY}
          stroke={axisColor}
          strokeOpacity={0.45}
          strokeWidth={1}
        />

        {/* Zone labels — placed inside each band near the top */}
        {segments.map(([a, b], zi) => {
          const x1 = xScale(a)
          const x2 = xScale(b)
          const bandW = x2 - x1
          if (bandW < 24) return null
          const cx = (x1 + x2) / 2
          const pct = pcts[zi] ?? 0
          const showPct = pct >= 0.1 && bandW >= 60
          const label = showPct ? `Z${zi + 1} · ${pct.toFixed(0)}%` : `Z${zi + 1}`
          return (
            <text
              key={`zl-${zi}`}
              x={cx}
              y={padTop + innerH / 2}
              textAnchor="middle"
              dominantBaseline="middle"
              fill={ZONE_COLORS[zi]}
              opacity={pct >= 0.1 ? 0.95 : 0.55}
              fontSize={10}
              fontWeight={600}
              fontFamily="ui-sans-serif, system-ui, sans-serif"
            >
              {label}
            </text>
          )
        })}

        {/* X-axis ticks (marks + labels) at boundaries + outer edges */}
        {(() => {
          const ticks = [lo, ...splits, hi]
          const lastIdx = ticks.length - 1
          return ticks.map((bpm, i) => {
            const x = xScale(bpm)
            if (x < padX - 1 || x > padX + innerW + 1) return null
            const isLast = i === lastIdx
            return (
              <g key={`tx-${i}`}>
                <line
                  x1={x}
                  x2={x}
                  y1={baseY}
                  y2={baseY + 3}
                  stroke={axisColor}
                  strokeOpacity={0.6}
                  strokeWidth={1}
                />
                <text
                  x={x}
                  y={height - 6}
                  textAnchor={isLast ? 'end' : 'middle'}
                  fill={tickColor}
                  fontSize={10}
                  fontFamily="ui-sans-serif, system-ui, sans-serif"
                >
                  {Math.round(bpm)}
                  {isLast && (
                    <tspan dx={3} fill={tickColor} opacity={0.7}>bpm</tspan>
                  )}
                </text>
              </g>
            )
          })
        })()}
      </svg>
    </div>
  )
}

export default memo(HrZoneDistributionChart)
