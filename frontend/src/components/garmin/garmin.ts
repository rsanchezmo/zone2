import { useIsMobile } from '../../hooks/useIsMobile'
import { useTheme } from '../../hooks/useTheme'
import type { GarminLatestResponse, GarminTrendRow as TrendRow, GarminTrends } from '../../api/hooks'

// Single accent for the whole page. Variations come from opacity / tints
// within the same cyan family, never from switching hues.
export const ACCENT = '#06b6d4'           // cyan-500 (brand)
export const ACCENT_LIGHT = '#67e8f9'     // cyan-300 (light)
export const MUTED = '#94a3b8'            // slate-400 — only for "not garmin" series
// Semantic tones — used for qualitative status (qualifier pills, factor dots,
// ACWR readout, sleep/HRV/readiness verdicts). Cyan stays the page accent;
// these only appear on elements that mean "good" or "bad".
export const POS = '#10b981'              // emerald-500
export const NEG = '#ef4444'              // red-500

export type Tone = 'pos' | 'neg' | 'neutral'
export const toneColor = (t: Tone) => t === 'pos' ? POS : t === 'neg' ? NEG : ACCENT

// Tone classification helpers. Thresholds picked from Garmin's own UI:
// readiness HIGH ≥ 70 / LOW < 40; ACWR sweet-spot 0.8–1.3; HRV BALANCED vs
// UNBALANCED; sleep qualifier strings; body battery net swing.
export const readinessTone = (score: number | null): Tone =>
  score == null ? 'neutral' : score >= 70 ? 'pos' : score < 40 ? 'neg' : 'neutral'
export const sleepTone = (q: string | undefined): Tone => {
  if (!q) return 'neutral'
  const u = q.toUpperCase()
  if (u === 'EXCELLENT' || u === 'GOOD') return 'pos'
  if (u === 'POOR') return 'neg'
  return 'neutral'
}
export const hrvTone = (s: string | undefined): Tone => {
  if (!s) return 'neutral'
  const u = s.toUpperCase()
  if (u === 'BALANCED') return 'pos'
  if (u.includes('UNBALANCED') || u === 'LOW' || u === 'POOR') return 'neg'
  return 'neutral'
}
export const acwrTone = (r: number | null): Tone => {
  if (r == null) return 'neutral'
  if (r >= 0.8 && r <= 1.3) return 'pos'
  if (r > 1.5 || r < 0.5) return 'neg'
  return 'neutral'
}
export const bbTone = (charged: number | null, drained: number | null): Tone => {
  if (charged == null || drained == null) return 'neutral'
  const net = charged - drained
  if (net > 10) return 'pos'
  if (net < -10) return 'neg'
  return 'neutral'
}
// Stress: Garmin's own bands — 0–25 rest, 26–50 low, 51–75 medium, 76+ high.
export const stressTone = (s: number | null): Tone =>
  s == null ? 'neutral' : s <= 25 ? 'pos' : s >= 76 ? 'neg' : 'neutral'
// SpO2: <90% is clinically low (red), ≥95% normal-to-good (green).
export const spo2Tone = (s: number | null): Tone =>
  s == null ? 'neutral' : s >= 95 ? 'pos' : s < 90 ? 'neg' : 'neutral'
// Resting HR vs the user's own 7-day baseline — drifting down = greener,
// drifting up = redder. Personal reference avoids age-cohort guessing.
export const restingHrTone = (resting: number | null, avg7d: number | null): Tone => {
  if (resting == null || avg7d == null) return 'neutral'
  const delta = resting - avg7d
  if (delta <= -2) return 'pos'
  if (delta >= 3) return 'neg'
  return 'neutral'
}

// Reusable zone-pickers for the band-coloured charts below.
export const AMBER = '#f59e0b'
export const stressZoneColor = (v: number) =>
  v <= 25 ? POS : v <= 50 ? ACCENT : v <= 75 ? AMBER : NEG
export const recoveryZoneColor = (h: number) =>
  h <= 12 ? POS : h <= 24 ? ACCENT : h <= 48 ? AMBER : NEG
export const acwrZoneColor = (r: number) =>
  r >= 0.8 && r <= 1.3 ? POS
    : (r >= 0.5 && r < 0.8) || (r > 1.3 && r <= 1.5) ? AMBER
    : NEG
export const readinessZoneColor = (v: number) =>
  v >= 75 ? POS : v >= 50 ? ACCENT : v >= 25 ? AMBER : NEG
// VO2 max — Garmin's adult-male 30s bands. Their app uses 5 named tiers:
// Superior · Excellent · Good · Fair · Poor, with red→orange→green→blue→purple
// (lower-better-is-worse here so we don't reuse our generic POS/NEG palette).
export const VO2 = {
  poor:      '#ef4444', // red-500
  fair:      '#f97316', // orange-500
  good:      '#10b981', // green-500
  excellent: '#3b82f6', // blue-500
  superior:  '#a855f7', // purple-500
}
export const vo2ZoneColor = (v: number) =>
  v >= 55 ? VO2.superior
    : v >= 49 ? VO2.excellent
    : v >= 44 ? VO2.good
    : v >= 39 ? VO2.fair
    : VO2.poor

type LooseRecord = Record<string, unknown>
type ChartDotProps = { cx: number; cy: number; payload: LooseRecord }

// ─────────────────────────────────────────── helpers

export function num(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}
export function secondsToMinutes(v: unknown): number | null {
  const s = num(v)
  return s != null ? s / 60 : null
}
export function displayNum(v: unknown): number {
  if (typeof v === 'number' && Number.isFinite(v)) return v
  if (typeof v === 'string' && v.trim() !== '') {
    const parsed = Number(v)
    if (Number.isFinite(parsed)) return parsed
  }
  return 0
}
export function text(v: unknown): string | undefined {
  return typeof v === 'string' ? v : undefined
}
function asRecord(v: unknown): LooseRecord | null {
  return typeof v === 'object' && v !== null ? v as LooseRecord : null
}
function firstRecordValue(v: unknown): LooseRecord | null {
  const record = asRecord(v)
  if (!record) return null
  return asRecord(Object.values(record)[0])
}
export function dotProps(props: unknown): ChartDotProps | null {
  const p = asRecord(props)
  const cx = num(p?.cx)
  const cy = num(p?.cy)
  const payload = asRecord(p?.payload)
  if (cx == null || cy == null || !payload) return null
  return { cx, cy, payload }
}
export function fmtDate(iso: unknown): string {
  if (typeof iso !== 'string') return ''
  const d = new Date(iso + 'T00:00:00')
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}
export function fmtDayDate(iso: string): string {
  const d = new Date(iso + 'T00:00:00')
  return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
}
export function fmtSigned(v: number): string {
  return v > 0 ? `+${v}` : String(v)
}
export function fmtKm(meters: number | null): string {
  if (meters == null) return '–'
  const km = meters / 1000
  return km >= 10 ? km.toFixed(1) : km.toFixed(2)
}
export function fmtRecovery(min: number | null): string | undefined {
  if (min == null || min <= 0) return undefined
  const h = Math.round(min / 60)
  if (h < 24) return `${h}h to recovery`
  const d = Math.floor(h / 24)
  return `${d}d ${h % 24}h to recovery`
}
function cleanPhrase(p: string | null | undefined): string {
  if (!p) return ''
  // PRODUCTIVE_3 → Productive · ABOVE_TARGETS → Above targets
  return p.replace(/_\d+$/, '').toLowerCase().replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase())
}

// ─────────────────────────────────────────── weekly rhythm

export type WeekdayPattern = {
  bestIdx: number            // Monday = 0
  means: (number | null)[]   // per-weekday mean, Monday-first
  bestMean: number
  deltaPct: number | null    // best weekday vs the all-days mean
}

export function weekdayPattern(
  rows: TrendRow[] | undefined,
  value: (r: TrendRow) => number | null,
  mode: 'max' | 'min',
): WeekdayPattern | null {
  const sums = new Array(7).fill(0)
  const counts = new Array(7).fill(0)
  let total = 0
  let n = 0
  for (const r of rows ?? []) {
    const v = value(r)
    if (v == null) continue
    const idx = (new Date(r.date + 'T00:00:00').getDay() + 6) % 7
    sums[idx] += v
    counts[idx] += 1
    total += v
    n += 1
  }
  // Every weekday needs a couple of samples before crowning a winner.
  if (counts.some(c => c < 2)) return null
  const means = sums.map((s, i) => s / counts[i])
  let bestIdx = 0
  for (let i = 1; i < 7; i++) {
    if (mode === 'max' ? means[i] > means[bestIdx] : means[i] < means[bestIdx]) bestIdx = i
  }
  const overallMean = total / n
  return {
    bestIdx,
    means,
    bestMean: means[bestIdx],
    deltaPct: overallMean !== 0 ? ((means[bestIdx] - overallMean) / overallMean) * 100 : null,
  }
}

function cleanCoaching(p: string | null | undefined): { text: string; tone: 'pos' | 'neg' | 'neutral' } | null {
  if (!p || p === 'NONE') return null
  // Garmin codes carry a tone prefix we want to surface separately.
  let tone: 'pos' | 'neg' | 'neutral' = 'neutral'
  let c = p
  const m = c.match(/^(POSITIVE|NEGATIVE|NEUTRAL|MODERATE|MOD)_/i)
  if (m) {
    tone = /POSITIVE/i.test(m[1]) ? 'pos' : /NEGATIVE/i.test(m[1]) ? 'neg' : 'neutral'
    c = c.slice(m[0].length)
  }
  // HRV phrases start with HRV_ which is redundant when shown next to the
  // HRV tile label. Strip it so HRV_BALANCED_2 → "Balanced".
  c = c.replace(/^HRV_/i, '')
  c = c.replace(/_\d+$/, '')                  // drop trailing _3 etc
  const text = c.toLowerCase().replace(/_/g, ' ').replace(/^\w/, ch => ch.toUpperCase())
  return { text, tone }
}

/** The last `days` days of a trends payload fetched over a longer window. */
export function lastDays(trends: GarminTrends | undefined, days: number): GarminTrends | undefined {
  if (!trends || trends.days <= days) return trends
  const from = new Date(`${trends.end_date}T00:00:00`)
  from.setDate(from.getDate() - (days - 1))
  const fromIso = `${from.getFullYear()}-${String(from.getMonth() + 1).padStart(2, '0')}-${String(from.getDate()).padStart(2, '0')}`
  const metrics = Object.fromEntries(
    Object.entries(trends.metrics).map(([metric, rows]) => [metric, rows.filter(r => r.date >= fromIso)]),
  )
  return { ...trends, days, start_date: fromIso, metrics }
}

/** The stat cards' values from the latest Garmin payloads. */
export function cardValues(latest: GarminLatestResponse | undefined) {
  const sleep = latest?.sleep?.payload?.dailySleepDTO ?? null
  const overall = sleep?.sleepScores?.overall ?? {}
  const hrv = latest?.hrv?.payload?.hrvSummary ?? null
  const tr  = latest?.training_readiness?.payload ?? null
  const tsPayload = latest?.training_status?.payload ?? null
  const tsGeneric = tsPayload?.mostRecentVO2Max?.generic ?? null
  const tsLoadDev = tsPayload?.mostRecentTrainingLoadBalance?.metricsTrainingLoadBalanceDTOMap
  const loadDev = firstRecordValue(tsLoadDev)
  const tsStatusDev = tsPayload?.mostRecentTrainingStatus?.latestTrainingStatusData
  const statusDev = firstRecordValue(tsStatusDev)
  const acute = asRecord(statusDev?.acuteTrainingLoadDTO)
  const hr  = latest?.heart_rates?.payload ?? null
  const stress = latest?.stress?.payload ?? null
  const bb  = latest?.body_battery?.payload ?? null
  const steps = latest?.daily_steps?.payload ?? null
  const us = latest?.user_summary?.payload ?? null
  const spo2 = latest?.spo2?.payload ?? null
  const im = latest?.intensity_minutes?.payload ?? null
  const sleepSeconds = num(sleep?.sleepTimeSeconds)

  return {
    restingHR: num(hr?.restingHeartRate),
    hr7dAvg: num(hr?.lastSevenDaysAvgRestingHeartRate),
    sleepScore: num(overall.value),
    sleepQualifier: overall.qualifierKey as string | undefined,
    sleepHours: sleepSeconds != null ? sleepSeconds / 3600 : null,
    sleepFeedback: cleanCoaching(sleep?.sleepScoreFeedback),
    sleepInsight:  cleanCoaching(sleep?.sleepScoreInsight),
    readinessFeedback: cleanCoaching(tr?.feedbackShort),
    hrvFeedback: cleanCoaching(hrv?.feedbackPhrase),
    hrvLastNight: num(hrv?.lastNightAvg),
    hrvWeekly: num(hrv?.weeklyAvg),
    hrvStatus: hrv?.status as string | undefined,
    readinessScore: num(tr?.score),
    readinessLevel: tr?.level as string | undefined,
    recoveryTimeMin: num(tr?.recoveryTime),
    vo2max: num(tsGeneric?.vo2MaxPreciseValue) ?? num(tsGeneric?.vo2MaxValue),
    vo2maxDate: tsGeneric?.calendarDate as string | undefined,
    stressAvg: num(stress?.avgStressLevel),
    stressMax: num(stress?.maxStressLevel),
    bbCharged: num(bb?.charged),
    bbDrained: num(bb?.drained),
    stepsToday: num(steps?.totalSteps),
    stepGoal: num(steps?.stepGoal),
    distanceM: num(steps?.totalDistance),
    activeKcal: num(us?.activeKilocalories),
    totalKcal: num(us?.totalKilocalories),
    floors: num(us?.floorsAscended),
    avgSpo2: num(spo2?.averageSpO2) ?? num(us?.averageSpo2),
    avgSpo2Sleep: num(spo2?.avgSleepSpO2),
    imModerate: num(im?.moderateMinutes),
    imVigorous: num(im?.vigorousMinutes),
    // Training-status hero strip
    statusPhrase: cleanPhrase(text(statusDev?.trainingStatusFeedbackPhrase)),
    statusSport: text(statusDev?.sport),
    acwrRatio: num(acute?.dailyAcuteChronicWorkloadRatio),
    acwrStatus: text(acute?.acwrStatus),
    // Readiness factor bars
    readinessFactors: tr ? [
      { label: 'Sleep',         value: num(tr.sleepScoreFactorPercent) },
      { label: 'Recovery',      value: num(tr.recoveryTimeFactorPercent) },
      { label: 'ACWR',          value: num(tr.acwrFactorPercent) },
      { label: 'HRV',           value: num(tr.hrvFactorPercent) },
      { label: 'Stress hist.',  value: num(tr.stressHistoryFactorPercent) },
      { label: 'Sleep hist.',   value: num(tr.sleepHistoryFactorPercent) },
    ] : [],
    // Training load balance
    load: loadDev ? {
      aerobic_low: num(loadDev.monthlyLoadAerobicLow),
      aerobic_high: num(loadDev.monthlyLoadAerobicHigh),
      anaerobic: num(loadDev.monthlyLoadAnaerobic),
      targets: {
        aerobic_low: [num(loadDev.monthlyLoadAerobicLowTargetMin), num(loadDev.monthlyLoadAerobicLowTargetMax)],
        aerobic_high: [num(loadDev.monthlyLoadAerobicHighTargetMin), num(loadDev.monthlyLoadAerobicHighTargetMax)],
        anaerobic: [num(loadDev.monthlyLoadAnaerobicTargetMin), num(loadDev.monthlyLoadAnaerobicTargetMax)],
      },
      feedback: cleanPhrase(text(loadDev.trainingBalanceFeedbackPhrase)),
    } : null,
  }
}

export type GarminCard = ReturnType<typeof cardValues>

/** Axis, margin and tooltip props shared by the page's charts. */
export function useGarminChartProps() {
  const { colors } = useTheme()
  const isMobile = useIsMobile()
// Common chart props
const chartMargin = { top: 8, right: 8, left: 4, bottom: 8 }
const xAxisProps = {
  dataKey: 'date',
  tickFormatter: fmtDate,
  tick: { fill: colors.tickFill, fontSize: 10 },
  axisLine: false as const,
  tickLine: false as const,
  interval: 'equidistantPreserveStart' as const,
}
const yAxisProps = {
  tick: { fill: colors.tickFillSecondary, fontSize: 10 },
  axisLine: false as const,
  tickLine: false as const,
  width: isMobile ? 42 : 60,
}
const tooltipProps = { ...colors.tooltip, labelFormatter: fmtDate }
  return { chartMargin, xAxisProps, yAxisProps, tooltipProps }
}
