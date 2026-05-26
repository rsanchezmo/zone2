import { useMemo, useState } from 'react'
import clsx from 'clsx'
import {
  ResponsiveContainer, ComposedChart, BarChart, LineChart, AreaChart,
  Bar, Line, Area, Cell,
  XAxis, YAxis, Tooltip, CartesianGrid, ReferenceLine, ReferenceArea,
} from 'recharts'
import { useTheme } from '../hooks/useTheme'
import { useIsMobile } from '../hooks/useIsMobile'
import {
  useGarminStatus, useGarminLatest, useGarminTrends, useTriggerGarminSync,
} from '../api/hooks'
import StatCard from '../components/shared/StatCard'
import ChartPanel, { LegendSwatch } from '../components/shared/ChartPanel'

// Single accent for the whole page. Variations come from opacity / tints
// within the same cyan family, never from switching hues.
const ACCENT = '#06b6d4'           // cyan-500 (brand)
const ACCENT_DARK = '#0e7490'      // cyan-700 (deep)
const ACCENT_LIGHT = '#67e8f9'     // cyan-300 (light)
const ACCENT_PALE = '#cffafe'      // cyan-100 (palest)
const MUTED = '#94a3b8'            // slate-400 — only for "not garmin" series
// Semantic tones — used for qualitative status (qualifier pills, factor dots,
// ACWR readout, sleep/HRV/readiness verdicts). Cyan stays the page accent;
// these only appear on elements that mean "good" or "bad".
const POS = '#10b981'              // emerald-500
const NEG = '#ef4444'              // red-500

type Tone = 'pos' | 'neg' | 'neutral'
const toneColor = (t: Tone) => t === 'pos' ? POS : t === 'neg' ? NEG : ACCENT

// Tone classification helpers. Thresholds picked from Garmin's own UI:
// readiness HIGH ≥ 70 / LOW < 40; ACWR sweet-spot 0.8–1.3; HRV BALANCED vs
// UNBALANCED; sleep qualifier strings; body battery net swing.
const readinessTone = (score: number | null): Tone =>
  score == null ? 'neutral' : score >= 70 ? 'pos' : score < 40 ? 'neg' : 'neutral'
const sleepTone = (q: string | undefined): Tone => {
  if (!q) return 'neutral'
  const u = q.toUpperCase()
  if (u === 'EXCELLENT' || u === 'GOOD') return 'pos'
  if (u === 'POOR') return 'neg'
  return 'neutral'
}
const hrvTone = (s: string | undefined): Tone => {
  if (!s) return 'neutral'
  const u = s.toUpperCase()
  if (u === 'BALANCED') return 'pos'
  if (u.includes('UNBALANCED') || u === 'LOW' || u === 'POOR') return 'neg'
  return 'neutral'
}
const acwrTone = (r: number | null): Tone => {
  if (r == null) return 'neutral'
  if (r >= 0.8 && r <= 1.3) return 'pos'
  if (r > 1.5 || r < 0.5) return 'neg'
  return 'neutral'
}
const bbTone = (charged: number | null, drained: number | null): Tone => {
  if (charged == null || drained == null) return 'neutral'
  const net = charged - drained
  if (net > 10) return 'pos'
  if (net < -10) return 'neg'
  return 'neutral'
}
// Stress: Garmin's own bands — 0–25 rest, 26–50 low, 51–75 medium, 76+ high.
const stressTone = (s: number | null): Tone =>
  s == null ? 'neutral' : s <= 25 ? 'pos' : s >= 76 ? 'neg' : 'neutral'
// SpO2: <90% is clinically low (red), ≥95% normal-to-good (green).
const spo2Tone = (s: number | null): Tone =>
  s == null ? 'neutral' : s >= 95 ? 'pos' : s < 90 ? 'neg' : 'neutral'
// Resting HR vs the user's own 7-day baseline — drifting down = greener,
// drifting up = redder. Personal reference avoids age-cohort guessing.
const restingHrTone = (resting: number | null, avg7d: number | null): Tone => {
  if (resting == null || avg7d == null) return 'neutral'
  const delta = resting - avg7d
  if (delta <= -2) return 'pos'
  if (delta >= 3) return 'neg'
  return 'neutral'
}

// Reusable zone-pickers for the band-coloured charts below.
const AMBER = '#f59e0b'
const stressZoneColor = (v: number) =>
  v <= 25 ? POS : v <= 50 ? ACCENT : v <= 75 ? AMBER : NEG
const recoveryZoneColor = (h: number) =>
  h <= 12 ? POS : h <= 24 ? ACCENT : h <= 48 ? AMBER : NEG
const acwrZoneColor = (r: number) =>
  r >= 0.8 && r <= 1.3 ? POS
    : (r >= 0.5 && r < 0.8) || (r > 1.3 && r <= 1.5) ? AMBER
    : NEG
const readinessZoneColor = (v: number) =>
  v >= 75 ? POS : v >= 50 ? ACCENT : v >= 25 ? AMBER : NEG
// VO2 max — Garmin's adult-male 30s bands. Their app uses 5 named tiers:
// Superior · Excellent · Good · Fair · Poor, with red→orange→green→blue→purple
// (lower-better-is-worse here so we don't reuse our generic POS/NEG palette).
const VO2 = {
  poor:      '#ef4444', // red-500
  fair:      '#f97316', // orange-500
  good:      '#10b981', // green-500
  excellent: '#3b82f6', // blue-500
  superior:  '#a855f7', // purple-500
}
const vo2ZoneColor = (v: number) =>
  v >= 55 ? VO2.superior
    : v >= 49 ? VO2.excellent
    : v >= 44 ? VO2.good
    : v >= 39 ? VO2.fair
    : VO2.poor

const RANGE_OPTIONS = [
  { label: '7d', days: 7 },
  { label: '30d', days: 30 },
  { label: '90d', days: 90 },
  { label: '365d', days: 365 },
] as const

type TrendRow = Record<string, unknown> & { date: string }
type TrendsResp = {
  start_date: string
  end_date: string
  days: number
  metrics: Record<string, TrendRow[]>
}

// ─────────────────────────────────────────── helpers

function num(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}
function fmtDate(iso: string): string {
  const d = new Date(iso + 'T00:00:00')
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}
function fmtKm(meters: number | null): string {
  if (meters == null) return '–'
  const km = meters / 1000
  return km >= 10 ? km.toFixed(1) : km.toFixed(2)
}
function fmtRecovery(min: number | null): string | undefined {
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

// ─────────────────────────────────────────── skeleton

function PageSkeleton({ isLight }: { isLight: boolean }) {
  const bar = isLight ? 'bg-gray-100' : 'bg-surface-700'
  return (
    <div className="max-w-5xl mx-auto space-y-10 pb-12">
      <div className={clsx('h-12 panel animate-pulse rounded-xl')} />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {Array.from({ length: 12 }).map((_, i) => (
          <div key={i} className={clsx('rounded-xl p-4 panel animate-pulse')}>
            <div className={clsx('h-3 w-16 rounded mb-3', bar)} />
            <div className={clsx('h-7 w-20 rounded', bar)} />
          </div>
        ))}
      </div>
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className={clsx('panel p-5 animate-pulse')}>
          <div className={clsx('h-3 w-32 rounded mb-4', bar)} />
          <div className={clsx('h-[240px] rounded', bar)} />
        </div>
      ))}
    </div>
  )
}

// ─────────────────────────────────────────── page

export default function GarminPage() {
  const { theme, colors } = useTheme()
  const isLight = theme === 'light'
  const isMobile = useIsMobile()

  const [days, setDays] = useState<number>(30)
  const { data: status } = useGarminStatus()
  const { data: latest, isLoading: latestLoading } = useGarminLatest()
  const { data: trends, isLoading: trendsLoading } = useGarminTrends(days)
  const triggerSync = useTriggerGarminSync()

  const enabled = status?.enabled === true
  const syncing = status?.syncing === true

  // ── Latest card values ───────────────────────────────────────────
  const card = useMemo(() => {
    const sleep = latest?.sleep?.payload?.dailySleepDTO ?? null
    const overall = sleep?.sleepScores?.overall ?? {}
    const hrv = latest?.hrv?.payload?.hrvSummary ?? null
    const tr  = latest?.training_readiness?.payload ?? null
    const tsPayload = latest?.training_status?.payload ?? null
    const tsGeneric = tsPayload?.mostRecentVO2Max?.generic ?? null
    const tsLoadDev = tsPayload?.mostRecentTrainingLoadBalance?.metricsTrainingLoadBalanceDTOMap
    const loadDev = tsLoadDev ? Object.values<any>(tsLoadDev)[0] : null
    const tsStatusDev = tsPayload?.mostRecentTrainingStatus?.latestTrainingStatusData
    const statusDev = tsStatusDev ? Object.values<any>(tsStatusDev)[0] : null
    const acute = statusDev?.acuteTrainingLoadDTO ?? null
    const hr  = latest?.heart_rates?.payload ?? null
    const stress = latest?.stress?.payload ?? null
    const bb  = latest?.body_battery?.payload ?? null
    const steps = latest?.daily_steps?.payload ?? null
    const us = latest?.user_summary?.payload ?? null
    const spo2 = latest?.spo2?.payload ?? null
    const im = latest?.intensity_minutes?.payload ?? null

    return {
      restingHR: num(hr?.restingHeartRate),
      hr7dAvg: num(hr?.lastSevenDaysAvgRestingHeartRate),
      sleepScore: num(overall.value),
      sleepQualifier: overall.qualifierKey as string | undefined,
      sleepHours: sleep ? sleep.sleepTimeSeconds / 3600 : null,
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
      statusPhrase: cleanPhrase(statusDev?.trainingStatusFeedbackPhrase),
      statusSport: statusDev?.sport as string | undefined,
      acwrRatio: num(acute?.dailyAcuteChronicWorkloadRatio),
      acwrStatus: acute?.acwrStatus as string | undefined,
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
        feedback: cleanPhrase(loadDev.trainingBalanceFeedbackPhrase),
      } : null,
    }
  }, [latest])

  // ── Chart shaping ────────────────────────────────────────────────
  const t = trends as TrendsResp | undefined

  const sleepData = useMemo(() => (t?.metrics.sleep ?? []).map(r => ({
    date: r.date,
    deep:  num(r.deep_seconds)  ? (r.deep_seconds  as number) / 60 : null,
    rem:   num(r.rem_seconds)   ? (r.rem_seconds   as number) / 60 : null,
    light: num(r.light_seconds) ? (r.light_seconds as number) / 60 : null,
    awake: num(r.awake_seconds) ? (r.awake_seconds as number) / 60 : null,
    score: num(r.score),
    sleep_hr: num((r as any).avg_hr),
  })), [t])

  const recoveryData = useMemo(() => (t?.metrics.training_readiness ?? []).map(r => ({
    date: r.date,
    recovery_h: num((r as any).recovery_time_min) ? ((r as any).recovery_time_min as number) / 60 : null,
  })), [t])

  const acwrData = useMemo(() => (t?.metrics.training_status ?? [])
    .map(r => ({ date: r.date, ratio: num((r as any).acwr_ratio) }))
    .filter(r => r.ratio !== null), [t])

  const caloriesData = useMemo(() => (t?.metrics.user_summary ?? []).map(r => ({
    date: r.date,
    active: num(r.active_kcal) ?? 0,
    bmr: num(r.bmr_kcal) ?? 0,
  })), [t])

  const hrData = useMemo(() => (t?.metrics.heart_rates ?? []).map(r => ({
    date: r.date,
    resting: num(r.resting),
    min: num(r.min),
    max: num(r.max),
  })), [t])

  const hrvData = useMemo(() => (t?.metrics.hrv ?? []).map(r => ({
    date: r.date,
    last_night: num(r.last_night_avg),
    weekly: num(r.weekly_avg),
  })), [t])

  const readinessData = useMemo(() => (t?.metrics.training_readiness ?? []).map(r => ({
    date: r.date,
    score: num(r.score),
  })), [t])

  const stressData = useMemo(() => (t?.metrics.stress ?? []).map(r => ({
    date: r.date,
    avg: num(r.avg),
    max: num(r.max),
  })), [t])

  const bbData = useMemo(() => (t?.metrics.body_battery ?? []).map(r => ({
    date: r.date,
    charged: num(r.charged) ?? 0,
    drained: -1 * (num(r.drained) ?? 0),
  })), [t])

  const stepsData = useMemo(() => (t?.metrics.daily_steps ?? []).map(r => ({
    date: r.date,
    steps: num(r.total_steps),
    goal: num(r.step_goal),
  })), [t])

  const imData = useMemo(() => (t?.metrics.intensity_minutes ?? []).map(r => ({
    date: r.date,
    moderate: num(r.moderate) ?? 0,
    vigorous: num(r.vigorous) ?? 0,
  })), [t])

  const distanceData = useMemo(() => (t?.metrics.daily_steps ?? []).map(r => {
    const m = num(r.total_distance_m)
    return { date: r.date, km: m != null ? m / 1000 : null }
  }), [t])

  const floorsData = useMemo(() => (t?.metrics.user_summary ?? []).map(r => ({
    date: r.date,
    floors: num(r.floors_climbed),
  })), [t])

  const vo2Data = useMemo(() => (t?.metrics.training_status ?? [])
    .map(r => ({ date: r.date, vo2max: num(r.vo2max) }))
    .filter(r => r.vo2max !== null), [t])

  const respSpo2Data = useMemo(() => {
    const sleep = t?.metrics.sleep ?? []
    return sleep.map(r => ({
      date: r.date,
      spo2: num((r as any).avg_spo2),
      respiration: num((r as any).avg_respiration),
    }))
  }, [t])

  const goalRef = stepsData[0]?.goal ?? null

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
  const tooltipProps = {
    contentStyle: {
      background: colors.tooltipBg,
      border: `1px solid ${colors.tooltipBorder}`,
      borderRadius: 8,
      fontSize: 12,
    },
    labelStyle: { color: colors.tickFillSecondary },
    itemStyle: { color: colors.tickFillSecondary },
    labelFormatter: fmtDate,
  }

  if (latestLoading || trendsLoading) return <PageSkeleton isLight={isLight} />

  return (
    <div className="max-w-5xl mx-auto space-y-10 pb-12">
      {/* ── Header (eyebrow breadcrumb + range/sync controls) ────── */}
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div className="flex items-baseline gap-2">
          <span className="eyebrow">Garmin</span>
          <span className={clsx('text-[11px]', isLight ? 'text-gray-300' : 'text-gray-700')}>·</span>
          <span className={clsx('text-[11px] normal-case tracking-normal', isLight ? 'text-gray-500' : 'text-gray-500')}>
            watch-level wellness
          </span>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex items-center gap-0.5" role="tablist">
            {RANGE_OPTIONS.map(opt => (
              <button key={opt.days} className="chip"
                data-active={opt.days === days}
                onClick={() => setDays(opt.days)}>
                {opt.label}
              </button>
            ))}
          </div>
          <button className="btn"
            disabled={!enabled || syncing || triggerSync.isPending}
            onClick={() => triggerSync.mutate({ full: false })}
            title="Refresh the last 14 days">
            {syncing ? 'Syncing…' : 'Sync recent'}
          </button>
          <button className="btn"
            disabled={!enabled || syncing || triggerSync.isPending}
            onClick={() => {
              if (confirm('Backfill full Garmin history? Can take 20–60 min in the background.')) {
                triggerSync.mutate({ full: true })
              }
            }}
            title="Walk history backwards until empty days">
            Backfill all
          </button>
        </div>
      </header>

      {/* ── TODAY hero ──────────────────────────────────────────── */}
      {enabled && (
        <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
          <HeroTile
            label="Readiness"
            value={card.readinessScore}
            qualifier={card.readinessFeedback?.text ?? card.readinessLevel}
            tone={readinessTone(card.readinessScore)}
            detail={fmtRecovery(card.recoveryTimeMin) ?? card.readinessLevel?.toLowerCase()}
            isLight={isLight}
          />
          <HeroTile
            label="Sleep score"
            value={card.sleepScore}
            qualifier={card.sleepFeedback?.text ?? card.sleepQualifier}
            tone={card.sleepFeedback?.tone ?? sleepTone(card.sleepQualifier)}
            detail={card.sleepHours != null
              ? `${card.sleepHours.toFixed(1)}h asleep${card.sleepQualifier ? ` · ${card.sleepQualifier.toLowerCase()}` : ''}${card.sleepInsight ? ` · ${card.sleepInsight.text.toLowerCase()}` : ''}`
              : undefined}
            isLight={isLight}
          />
          <HeroTile
            label="Body Battery"
            value={card.bbCharged != null && card.bbDrained != null
              ? `+${card.bbCharged}/−${card.bbDrained}` : null}
            qualifier={card.bbCharged != null && card.bbDrained != null
              ? (card.bbCharged - card.bbDrained > 0 ? 'Net charged' : 'Net drained')
              : undefined}
            tone={bbTone(card.bbCharged, card.bbDrained)}
            detail="charged · drained today"
            isLight={isLight}
          />
          <HeroTile
            label="HRV"
            value={card.hrvLastNight}
            unit="ms"
            qualifier={card.hrvFeedback?.text ?? card.hrvStatus}
            tone={hrvTone(card.hrvStatus)}
            detail={card.hrvWeekly != null ? `7-day avg ${card.hrvWeekly} ms` : undefined}
            isLight={isLight}
          />
          <HeroTile
            label="Load ratio"
            value={card.acwrRatio != null ? card.acwrRatio.toFixed(2) : null}
            qualifier={card.acwrStatus}
            tone={acwrTone(card.acwrRatio)}
            detail="acute / chronic load"
            isLight={isLight}
          />
        </section>
      )}

      {/* ── Readiness factor breakdown (today snapshot) ──────────── */}
      {enabled && card.readinessFactors.length > 0 && (
        <ChartPanel
          title="Readiness factors"
          sublabel="today · contributors to your readiness score"
          accent={ACCENT}
        >
          <FactorBars factors={card.readinessFactors} isLight={isLight} />
        </ChartPanel>
      )}

      {/* ── Status banners ───────────────────────────────────────── */}
      {!enabled && (
        <div className={clsx(
          'rounded-xl border p-4 text-sm',
          isLight ? 'bg-amber-50/80 border-amber-200 text-amber-900' : 'bg-amber-500/5 border-amber-500/30 text-amber-300',
        )}>
          <div className="font-medium mb-1">Garmin Connect not configured</div>
          <div className="text-xs opacity-90">
            Set <code className="px-1 rounded bg-black/10">GARMIN_EMAIL</code> and{' '}
            <code className="px-1 rounded bg-black/10">GARMIN_PASSWORD</code> in <code className="px-1 rounded bg-black/10">.env</code>, then restart the backend.
            First login may need an MFA code in the server terminal.
          </div>
          {status?.client_error && (
            <div className="text-xs mt-2 opacity-75">Last error: {status.client_error}</div>
          )}
        </div>
      )}
      {status?.last_error && (
        <div className={clsx(
          'rounded-xl border p-3 text-xs',
          isLight ? 'bg-red-50/80 border-red-200 text-red-800' : 'bg-red-500/5 border-red-500/30 text-red-300',
        )}>
          Last sync error: {status.last_error}
        </div>
      )}

      {/* ── Secondary stats: body (row 1) + activity (row 2) ────── */}
      <section className="space-y-3">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard label="Resting HR" value={card.restingHR ?? '–'} unit="bpm"
            sublabel={card.hr7dAvg != null ? `7d avg ${card.hr7dAvg}` : undefined}
            accent={toneColor(restingHrTone(card.restingHR, card.hr7dAvg))} />
          <StatCard label="VO2 max"
            value={card.vo2max != null ? card.vo2max.toFixed(1) : '–'}
            sublabel={card.vo2maxDate ? `updated ${card.vo2maxDate}` : undefined}
            accent={ACCENT} />
          <StatCard label="Stress avg" value={card.stressAvg ?? '–'}
            sublabel={card.stressMax != null ? `peak ${card.stressMax}` : undefined}
            accent={toneColor(stressTone(card.stressAvg))} />
          <StatCard label="SpO2"
            value={card.avgSpo2 != null ? `${Math.round(card.avgSpo2)}%` : '–'}
            sublabel={card.avgSpo2Sleep != null ? `sleep ${Math.round(card.avgSpo2Sleep)}%` : undefined}
            accent={toneColor(spo2Tone(card.avgSpo2))} />
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard label="Steps" value={card.stepsToday?.toLocaleString() ?? '–'}
            sublabel={card.stepGoal != null ? `goal ${card.stepGoal.toLocaleString()}` : undefined}
            accent={ACCENT} />
          <StatCard label="Distance"
            value={fmtKm(card.distanceM)} unit="km"
            sublabel={card.distanceM != null ? `${card.distanceM.toLocaleString()} m walked` : undefined}
            accent={ACCENT} />
          <StatCard label="Calories"
            value={card.totalKcal != null ? Math.round(card.totalKcal).toLocaleString() : '–'}
            unit="kcal"
            sublabel={card.activeKcal != null ? `${Math.round(card.activeKcal)} active` : undefined}
            accent={ACCENT} />
          <StatCard label="Floors"
            value={card.floors != null ? Math.round(card.floors).toString() : '–'}
            sublabel={card.imVigorous != null || card.imModerate != null
              ? `IM ${(card.imVigorous ?? 0) + (card.imModerate ?? 0)} min`
              : undefined}
            accent={ACCENT} />
        </div>
      </section>

      {!enabled && (
        <div className={clsx('text-center text-xs py-12', isLight ? 'text-gray-400' : 'text-gray-600')}>
          Configure Garmin Connect to start collecting trends.
        </div>
      )}

      {enabled && (
        <>
          {/* ── Section divider before the evolution plots ─────── */}
          <div className="section-head pt-2">
            <span className="eyebrow">Evolution</span>
          </div>

          {/* ── Sleep stages + score line overlay ───────────────── */}
          {(() => {
            // Single hue per stage, with a vertical opacity fade — saturated
            // at the top edge, dropping toward transparent at the bottom.
            // Mirrors the atmospheric "area-chart fade" look used by the HR
            // panel below.
            const STAGE = {
              deep:  '#6366f1',  // indigo-500
              rem:   '#a855f7',  // purple-500
              light: '#22d3ee',  // cyan-400
              awake: '#94a3b8',  // slate-400
            }
            const grad = (id: string, color: string) => (
              <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%"  stopColor={color} stopOpacity={0.95} />
                <stop offset="100%" stopColor={color} stopOpacity={0.08} />
              </linearGradient>
            )
            return (
              <ChartPanel
                title="Sleep stages & score" sublabel={`last ${days}d`} accent={ACCENT}
                legend={<>
                  <LegendSwatch color={STAGE.deep}  label="Deep" />
                  <LegendSwatch color={STAGE.rem}   label="REM" />
                  <LegendSwatch color={STAGE.light} label="Light" />
                  <LegendSwatch color={STAGE.awake} label="Awake" />
                  <LegendSwatch color="#fef08a" label="Sleep score" variant="dashed" />
                </>}
              >
                <ResponsiveContainer width="100%" height={260}>
                  <ComposedChart data={sleepData} margin={chartMargin}>
                    <defs>
                      {grad('sleepDeep',  STAGE.deep)}
                      {grad('sleepRem',   STAGE.rem)}
                      {grad('sleepLight', STAGE.light)}
                      {grad('sleepAwake', STAGE.awake)}
                    </defs>
                    <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
                    <XAxis {...xAxisProps} />
                    <YAxis yAxisId="dur" {...yAxisProps} tickFormatter={(v) => `${Math.round(v / 60)}h`} />
                    <YAxis yAxisId="score" orientation="right" {...yAxisProps} domain={[0, 100]}
                      tickFormatter={(v) => `${v}`} />
                    <Tooltip {...tooltipProps}
                      formatter={(v: number, name) => name === 'score' ? [`${v}/100`, 'Score'] : [`${Math.round(v)} min`, name]} />
                    <Bar yAxisId="dur" dataKey="deep"  stackId="s"
                      fill="url(#sleepDeep)" stroke="none"
                      isAnimationActive={false} />
                    <Bar yAxisId="dur" dataKey="rem"   stackId="s"
                      fill="url(#sleepRem)" stroke="none"
                      isAnimationActive={false} />
                    <Bar yAxisId="dur" dataKey="light" stackId="s"
                      fill="url(#sleepLight)" stroke="none"
                      isAnimationActive={false} />
                    <Bar yAxisId="dur" dataKey="awake" stackId="s"
                      fill="url(#sleepAwake)" stroke="none"
                      isAnimationActive={false} />
                    <Line yAxisId="score" type="monotone" dataKey="score"
                      stroke="#fef08a" strokeWidth={1.75} strokeDasharray="4 3"
                      dot={{ r: 2.5, fill: '#fef08a', stroke: '#fef08a' }}
                      activeDot={{ r: 4, fill: '#fef08a' }}
                      isAnimationActive={false} />
                  </ComposedChart>
                </ResponsiveContainer>
              </ChartPanel>
            )
          })()}

          {/* ── HR split: Resting & Min (tight) · Max (fade area) ── */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <ChartPanel
              title="Resting & min HR" sublabel={`last ${days}d`} accent={ACCENT}
              legend={<>
                <LegendSwatch color={ACCENT} label="Resting" />
                <LegendSwatch color={ACCENT_LIGHT} label="Daily min" variant="dashed" />
              </>}
            >
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={hrData} margin={chartMargin}>
                  <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
                  <XAxis {...xAxisProps} />
                  <YAxis {...yAxisProps} domain={['dataMin - 3', 'dataMax + 3']} />
                  <Tooltip {...tooltipProps}
                    formatter={(v: number, name) => [`${v} bpm`, name === 'resting' ? 'Resting' : 'Min']} />
                  <Line type="monotone" dataKey="min"
                    stroke={ACCENT_LIGHT} strokeWidth={1.5} strokeDasharray="4 3"
                    dot={false} isAnimationActive={false} />
                  <Line type="monotone" dataKey="resting"
                    stroke={ACCENT} strokeWidth={2}
                    dot={{ r: 2.5, fill: ACCENT, stroke: ACCENT }}
                    activeDot={{ r: 4, fill: ACCENT }} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </ChartPanel>

            <ChartPanel
              title="Max HR" sublabel={`last ${days}d`} accent={ACCENT}
              legend={<LegendSwatch color={ACCENT} label="Daily peak" />}
            >
              <ResponsiveContainer width="100%" height={220}>
                <AreaChart data={hrData} margin={chartMargin}>
                  <defs>
                    <linearGradient id="hrMax" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%"  stopColor={ACCENT} stopOpacity={0.55} />
                      <stop offset="100%" stopColor={ACCENT} stopOpacity={0.04} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
                  <XAxis {...xAxisProps} />
                  <YAxis {...yAxisProps} domain={['dataMin - 5', 'dataMax + 5']} />
                  <Tooltip {...tooltipProps}
                    formatter={(v: number) => [`${v} bpm`, 'Max']} />
                  <Area type="monotone" dataKey="max"
                    stroke={ACCENT} strokeWidth={2}
                    fill="url(#hrMax)"
                    activeDot={{ r: 4, fill: ACCENT }} isAnimationActive={false} />
                </AreaChart>
              </ResponsiveContainer>
            </ChartPanel>
          </div>

          {/* ── HRV + Sleep HR side-by-side ──────────────────────── */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <ChartPanel
              title="HRV overnight" sublabel={`last ${days}d`} accent={ACCENT}
              status={card.hrvStatus ? (() => {
                const c = toneColor(hrvTone(card.hrvStatus))
                return (
                  <span className="inline-flex items-center gap-1.5 text-[10px] uppercase font-semibold tracking-[0.15em] px-2 py-0.5 rounded-full border"
                    style={{ background: `${c}1a`, color: c, borderColor: `${c}55` }}>
                    <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ background: c }} />
                    {card.hrvStatus.toLowerCase()}
                  </span>
                )
              })() : undefined}
              legend={<>
                <LegendSwatch color={ACCENT} label="Last night" />
                <LegendSwatch color={ACCENT_LIGHT} label="7-day avg" variant="dashed" />
              </>}
            >
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={hrvData} margin={chartMargin}>
                  <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
                  <XAxis {...xAxisProps} />
                  <YAxis {...yAxisProps} domain={['dataMin - 3', 'dataMax + 3']} />
                  <Tooltip {...tooltipProps} formatter={(v: number) => `${v} ms`} />
                  <Line type="monotone" dataKey="weekly"
                    stroke={ACCENT_LIGHT} strokeWidth={1.5} strokeDasharray="4 3"
                    dot={false} isAnimationActive={false} />
                  <Line type="monotone" dataKey="last_night"
                    stroke={ACCENT} strokeWidth={2}
                    dot={{ r: 2.5, fill: ACCENT, stroke: ACCENT }}
                    activeDot={{ r: 4, fill: ACCENT }} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </ChartPanel>

            <ChartPanel
              title="Avg HR during sleep" sublabel={`last ${days}d`} accent={ACCENT}
              legend={<LegendSwatch color={ACCENT} label="Sleep HR" />}
            >
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={sleepData} margin={chartMargin}>
                  <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
                  <XAxis {...xAxisProps} />
                  <YAxis {...yAxisProps} domain={['dataMin - 3', 'dataMax + 3']}
                    tickFormatter={(v) => `${Math.round(v)}`} />
                  <Tooltip {...tooltipProps} formatter={(v: number) => `${v} bpm`} />
                  <Line type="monotone" dataKey="sleep_hr"
                    stroke={ACCENT} strokeWidth={2}
                    dot={{ r: 2.5, fill: ACCENT, stroke: ACCENT }}
                    activeDot={{ r: 4, fill: ACCENT }} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </ChartPanel>
          </div>

          {/* ── Training readiness (full width) ─────────────────── */}
          <ChartPanel
            title="Training readiness" sublabel={`last ${days}d`} accent={ACCENT}
            legend={<>
              <LegendSwatch color={POS}    label="High ≥75" />
              <LegendSwatch color={ACCENT} label="Moderate 50–75" />
              <LegendSwatch color={AMBER}  label="Low 25–50" />
              <LegendSwatch color={NEG}    label="Poor <25" />
            </>}
          >
                <ResponsiveContainer width="100%" height={220}>
                  <LineChart data={readinessData} margin={chartMargin}>
                    <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
                    <XAxis {...xAxisProps} />
                    <YAxis {...yAxisProps} domain={[0, 100]} />
                    <Tooltip {...tooltipProps} formatter={(v: number) => [`${v}/100`, 'Readiness']} />
                    <ReferenceArea y1={0}  y2={25}  fill={NEG}    fillOpacity={0.10} />
                    <ReferenceArea y1={25} y2={50}  fill={AMBER}  fillOpacity={0.08} />
                    <ReferenceArea y1={50} y2={75}  fill={ACCENT} fillOpacity={0.06} />
                    <ReferenceArea y1={75} y2={100} fill={POS}    fillOpacity={0.10} />
                    <Line type="monotone" dataKey="score"
                      stroke={isLight ? '#475569' : '#cbd5e1'} strokeOpacity={0.55}
                      strokeWidth={1.5}
                      isAnimationActive={false}
                      dot={(props: any) => {
                        const v = props.payload?.score
                        if (v == null) return <g />
                        const c = readinessZoneColor(v)
                        return <circle cx={props.cx} cy={props.cy} r={3.5}
                          fill={c} stroke={c} strokeWidth={1.5} />
                      }}
                      activeDot={(props: any) => {
                        const v = props.payload?.score ?? 0
                        const c = readinessZoneColor(v)
                        return <circle cx={props.cx} cy={props.cy} r={5} fill={c} stroke={c} />
                      }} />
                  </LineChart>
                </ResponsiveContainer>
              </ChartPanel>

          {/* ── ACWR + Recovery time ─────────────────────────────── */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <ChartPanel
              title="ACWR (acute / chronic load)" sublabel={`last ${days}d`} accent={ACCENT}
              legend={<>
                <LegendSwatch color={POS}    label="Sweet 0.8–1.3" />
                <LegendSwatch color={AMBER}  label="Caution" />
                <LegendSwatch color={NEG}    label="Risk" />
              </>}
            >
              {acwrData.length === 0 ? (
                <div className={clsx('flex items-center justify-center h-[200px] text-xs', isLight ? 'text-gray-400' : 'text-gray-500')}>
                  No ACWR readings in this window
                </div>
              ) : (
                <ResponsiveContainer width="100%" height={200}>
                  <LineChart data={acwrData} margin={chartMargin}>
                    <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
                    <XAxis {...xAxisProps} />
                    <YAxis {...yAxisProps} domain={[0, 'dataMax + 0.3']}
                      tickFormatter={(v) => v.toFixed(1)} />
                    <Tooltip {...tooltipProps}
                      formatter={(v: number) => [v.toFixed(2), 'ACWR']} />
                    {/* ACWR risk bands */}
                    <ReferenceArea y1={0}    y2={0.5} fill={NEG}   fillOpacity={0.10} />
                    <ReferenceArea y1={0.5}  y2={0.8} fill={AMBER} fillOpacity={0.08} />
                    <ReferenceArea y1={0.8}  y2={1.3} fill={POS}   fillOpacity={0.10} />
                    <ReferenceArea y1={1.3}  y2={1.5} fill={AMBER} fillOpacity={0.08} />
                    <ReferenceArea y1={1.5}  y2={99}  fill={NEG}   fillOpacity={0.12} />
                    <Line type="monotone" dataKey="ratio"
                      stroke={isLight ? '#475569' : '#cbd5e1'} strokeOpacity={0.55}
                      strokeWidth={1.5}
                      isAnimationActive={false}
                      dot={(props: any) => {
                        const v = props.payload?.ratio
                        if (v == null) return <g />
                        const c = acwrZoneColor(v)
                        return <circle cx={props.cx} cy={props.cy} r={3.5}
                          fill={c} stroke={c} strokeWidth={1.5} />
                      }}
                      activeDot={(props: any) => {
                        const v = props.payload?.ratio ?? 0
                        const c = acwrZoneColor(v)
                        return <circle cx={props.cx} cy={props.cy} r={5} fill={c} stroke={c} />
                      }} />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </ChartPanel>

            <ChartPanel
              title="Recovery time needed" sublabel={`last ${days}d`} accent={ACCENT}
              legend={<>
                <LegendSwatch color={POS}    label="≤12h" />
                <LegendSwatch color={ACCENT} label="12–24h" />
                <LegendSwatch color={AMBER}  label="24–48h" />
                <LegendSwatch color={NEG}    label=">48h" />
              </>}
            >
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={recoveryData} margin={chartMargin}>
                  <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
                  <XAxis {...xAxisProps} />
                  <YAxis {...yAxisProps} tickFormatter={(v) => `${Math.round(v)}h`} />
                  <Tooltip {...tooltipProps}
                    formatter={(v: number) => [`${v.toFixed(1)}h`, 'Recovery time']} />
                  <ReferenceArea y1={0}  y2={12} fill={POS}    fillOpacity={0.08} />
                  <ReferenceArea y1={12} y2={24} fill={ACCENT} fillOpacity={0.06} />
                  <ReferenceArea y1={24} y2={48} fill={AMBER}  fillOpacity={0.08} />
                  <ReferenceArea y1={48} y2={9999} fill={NEG}  fillOpacity={0.10} />
                  <Bar dataKey="recovery_h" isAnimationActive={false}>
                    {recoveryData.map((entry, i) => (
                      <Cell key={i} fill={entry.recovery_h != null ? recoveryZoneColor(entry.recovery_h) : ACCENT} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </ChartPanel>
          </div>

          {/* ── Stress + Body battery ────────────────────────────── */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <ChartPanel title="Stress" sublabel={`last ${days}d`} accent={ACCENT}
              legend={<>
                <LegendSwatch color={POS} label="Rest 0–25" />
                <LegendSwatch color={ACCENT} label="Low 26–50" />
                <LegendSwatch color="#f59e0b" label="Medium 51–75" />
                <LegendSwatch color={NEG} label="High 76–100" />
              </>}
            >
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={stressData} margin={chartMargin}>
                  <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
                  <XAxis {...xAxisProps} />
                  <YAxis {...yAxisProps} domain={[0, 100]} />
                  <Tooltip {...tooltipProps} />
                  {/* Garmin stress zones — tinted reference bands */}
                  <ReferenceArea y1={0}  y2={25}  fill={POS}     fillOpacity={0.10} />
                  <ReferenceArea y1={25} y2={50}  fill={ACCENT}  fillOpacity={0.08} />
                  <ReferenceArea y1={50} y2={75}  fill={AMBER}   fillOpacity={0.10} />
                  <ReferenceArea y1={75} y2={100} fill={NEG}     fillOpacity={0.12} />
                  <Line type="monotone" dataKey="max"
                    stroke={isLight ? '#94a3b8' : '#cbd5e1'} strokeOpacity={0.7}
                    strokeWidth={1.25} strokeDasharray="4 3"
                    dot={false} isAnimationActive={false} name="Peak" />
                  <Line type="monotone" dataKey="avg"
                    stroke={isLight ? '#475569' : '#cbd5e1'} strokeOpacity={0.55}
                    strokeWidth={1.5}
                    isAnimationActive={false} name="Avg"
                    dot={(props: any) => {
                      const v = props.payload?.avg
                      if (v == null) return <g />
                      const c = stressZoneColor(v)
                      return (
                        <circle cx={props.cx} cy={props.cy} r={3.5}
                          fill={c} stroke={c} strokeWidth={1.5} />
                      )
                    }}
                    activeDot={(props: any) => {
                      const v = props.payload?.avg ?? 0
                      const c = stressZoneColor(v)
                      return <circle cx={props.cx} cy={props.cy} r={5} fill={c} stroke={c} />
                    }} />
                </LineChart>
              </ResponsiveContainer>
            </ChartPanel>

            <ChartPanel title="Body battery" sublabel={`last ${days}d`} accent={ACCENT}
              legend={<>
                <LegendSwatch color={POS} label="Charged" />
                <LegendSwatch color={NEG} label="Drained" />
              </>}
            >
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={bbData} margin={chartMargin}>
                  <defs>
                    <linearGradient id="bbCharged" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%"  stopColor="#34d399" stopOpacity={0.95} />
                      <stop offset="100%" stopColor={POS}   stopOpacity={0.85} />
                    </linearGradient>
                    <linearGradient id="bbDrained" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%"  stopColor={NEG}    stopOpacity={0.85} />
                      <stop offset="100%" stopColor="#fca5a5" stopOpacity={0.95} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
                  <XAxis {...xAxisProps} />
                  <YAxis {...yAxisProps}
                    tickFormatter={(v) => v === 0 ? '0' : Math.abs(v).toString()} />
                  <Tooltip {...tooltipProps}
                    formatter={(v: number, name) => [Math.abs(v), name === 'charged' ? 'Charged' : 'Drained']} />
                  <ReferenceLine y={0} stroke={colors.tickFillSecondary} strokeOpacity={0.35} />
                  <Bar dataKey="charged" fill="url(#bbCharged)" isAnimationActive={false} />
                  <Bar dataKey="drained" fill="url(#bbDrained)" isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </ChartPanel>
          </div>

          {/* ── SpO2 + Respiration overnight ─────────────────────── */}
          <ChartPanel
            title="Overnight SpO2 & respiration" sublabel={`last ${days}d`} accent={ACCENT}
            legend={<>
              <LegendSwatch color={ACCENT} label="SpO2 %" />
              <LegendSwatch color={ACCENT_LIGHT} label="Respiration brpm" variant="dashed" />
            </>}
          >
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={respSpo2Data} margin={chartMargin}>
                <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
                <XAxis {...xAxisProps} />
                <YAxis yAxisId="spo2" {...yAxisProps} domain={[85, 100]}
                  tickFormatter={(v) => `${v}%`} />
                <YAxis yAxisId="resp" orientation="right" {...yAxisProps} domain={[8, 22]}
                  tickFormatter={(v) => `${v}`} />
                <Tooltip {...tooltipProps}
                  formatter={(v: number, name) => name === 'spo2' ? [`${v}%`, 'SpO2'] : [`${v} brpm`, 'Respiration']} />
                <Line yAxisId="spo2" type="monotone" dataKey="spo2"
                  stroke={ACCENT} strokeWidth={2}
                  dot={{ r: 2, fill: ACCENT, stroke: ACCENT }}
                  activeDot={{ r: 4, fill: ACCENT }} isAnimationActive={false} />
                <Line yAxisId="resp" type="monotone" dataKey="respiration"
                  stroke={ACCENT_LIGHT} strokeWidth={1.5} strokeDasharray="4 3"
                  dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </ChartPanel>

          {/* ── Steps ─────────────────────────────────────────────── */}
          <ChartPanel
            title="Daily steps" sublabel={`last ${days}d`} accent={ACCENT}
            legend={<>
              <LegendSwatch color={ACCENT} label="Below goal" />
              <LegendSwatch color={POS} label="Goal met" />
              {goalRef != null && <LegendSwatch color={MUTED} label={`Goal · ${goalRef.toLocaleString()}`} variant="dashed" />}
            </>}
          >
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={stepsData} margin={chartMargin}>
                <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
                <XAxis {...xAxisProps} />
                <YAxis {...yAxisProps}
                  tickFormatter={(v) => v >= 1000 ? `${(v / 1000).toFixed(0)}k` : String(v)} />
                <Tooltip {...tooltipProps} formatter={(v: number) => v.toLocaleString()} />
                {goalRef != null && (
                  <ReferenceLine y={goalRef} stroke={MUTED} strokeOpacity={0.5} strokeDasharray="4 3" />
                )}
                <Bar dataKey="steps" isAnimationActive={false}>
                  {stepsData.map((entry, i) => (
                    <Cell key={i}
                      fill={entry.steps != null && entry.goal != null && entry.steps >= entry.goal ? POS : ACCENT} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </ChartPanel>

          {/* ── Distance + Floors + Calories ─────────────────────── */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <ChartPanel title="Distance walked" sublabel={`last ${days}d`} accent={ACCENT}
              legend={<LegendSwatch color={ACCENT} label="km / day" />}
            >
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={distanceData} margin={chartMargin}>
                  <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
                  <XAxis {...xAxisProps} />
                  <YAxis {...yAxisProps} tickFormatter={(v) => `${v}`} />
                  <Tooltip {...tooltipProps}
                    formatter={(v: number) => [`${v.toFixed(2)} km`, 'Distance']} />
                  <Bar dataKey="km" fill={ACCENT} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </ChartPanel>

            <ChartPanel title="Floors climbed" sublabel={`last ${days}d`} accent={ACCENT}
              legend={<LegendSwatch color={ACCENT} label="floors / day" />}
            >
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={floorsData} margin={chartMargin}>
                  <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
                  <XAxis {...xAxisProps} />
                  <YAxis {...yAxisProps} tickFormatter={(v) => `${Math.round(v)}`} />
                  <Tooltip {...tooltipProps}
                    formatter={(v: number) => [`${Math.round(v)} floors`, 'Climbed']} />
                  <Bar dataKey="floors" fill={ACCENT} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </ChartPanel>

            <ChartPanel title="Calories" sublabel={`last ${days}d`} accent={ACCENT}
              legend={<>
                <LegendSwatch color="#64748b" label="BMR · resting" />
                <LegendSwatch color={POS} label="Active · earned" />
              </>}
            >
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={caloriesData} margin={chartMargin}>
                  <defs>
                    <linearGradient id="kcalBmr" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%"  stopColor="#94a3b8" stopOpacity={0.85} />
                      <stop offset="100%" stopColor="#475569" stopOpacity={0.7} />
                    </linearGradient>
                    <linearGradient id="kcalActive" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%"  stopColor="#34d399" stopOpacity={0.95} />
                      <stop offset="100%" stopColor={POS}   stopOpacity={0.85} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
                  <XAxis {...xAxisProps} />
                  <YAxis {...yAxisProps} tickFormatter={(v) => v >= 1000 ? `${(v/1000).toFixed(1)}k` : `${v}`} />
                  <Tooltip {...tooltipProps}
                    formatter={(v: number, name) => [`${Math.round(v).toLocaleString()} kcal`, name === 'bmr' ? 'BMR' : 'Active']} />
                  <Bar dataKey="bmr" stackId="kcal" fill="url(#kcalBmr)" isAnimationActive={false} />
                  <Bar dataKey="active" stackId="kcal" fill="url(#kcalActive)" isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </ChartPanel>
          </div>

          {/* ── Intensity minutes ────────────────────────────────── */}
          <ChartPanel
            title="Intensity minutes" sublabel={`last ${days}d`} accent={ACCENT}
            legend={<>
              <LegendSwatch color={ACCENT} label="Vigorous" />
              <LegendSwatch color={ACCENT_LIGHT} label="Moderate" />
            </>}
          >
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={imData} margin={chartMargin}>
                <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
                <XAxis {...xAxisProps} />
                <YAxis {...yAxisProps} tickFormatter={(v) => `${v}`} />
                <Tooltip {...tooltipProps}
                  formatter={(v: number, name) => [`${v} min`, name === 'vigorous' ? 'Vigorous' : 'Moderate']} />
                <Bar dataKey="moderate" stackId="im" fill={ACCENT_LIGHT} isAnimationActive={false} />
                <Bar dataKey="vigorous" stackId="im" fill={ACCENT} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </ChartPanel>

          {/* ── VO2 max (full width) ─────────────────────────────── */}
          <ChartPanel title="VO2 max" sublabel={`last ${days}d`} accent={ACCENT}
            legend={<>
              <LegendSwatch color={VO2.superior}  label="Superior ≥55" />
              <LegendSwatch color={VO2.excellent} label="Excellent 49–55" />
              <LegendSwatch color={VO2.good}      label="Good 44–49" />
              <LegendSwatch color={VO2.fair}      label="Fair 39–44" />
              <LegendSwatch color={VO2.poor}      label="Poor <39" />
            </>}
          >
            {vo2Data.length === 0 ? (
              <div className={clsx('flex items-center justify-center h-[220px] text-xs', isLight ? 'text-gray-400' : 'text-gray-500')}>
                No VO2 max updates in this window
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={240}>
                <LineChart data={vo2Data} margin={chartMargin}>
                  <CartesianGrid stroke={colors.gridStroke} strokeDasharray="3 3" vertical={false} />
                  <XAxis {...xAxisProps} />
                  {/* Pad the y-domain so the relevant zone bands sit visible
                      regardless of tight measured-value variation. */}
                  <YAxis {...yAxisProps} domain={[
                    (min: number) => Math.min(min - 1, 39),
                    (max: number) => Math.max(max + 1, 60),
                  ]} />
                  <Tooltip {...tooltipProps}
                    formatter={(v: number) => `${v.toFixed(1)} ml/kg/min`} />
                  <ReferenceArea y1={0}  y2={39} fill={VO2.poor}      fillOpacity={0.10} />
                  <ReferenceArea y1={39} y2={44} fill={VO2.fair}      fillOpacity={0.10} />
                  <ReferenceArea y1={44} y2={49} fill={VO2.good}      fillOpacity={0.08} />
                  <ReferenceArea y1={49} y2={55} fill={VO2.excellent} fillOpacity={0.10} />
                  <ReferenceArea y1={55} y2={99} fill={VO2.superior}  fillOpacity={0.12} />
                  <Line type="monotone" dataKey="vo2max"
                    stroke={isLight ? '#475569' : '#cbd5e1'} strokeOpacity={0.55}
                    strokeWidth={1.5}
                    isAnimationActive={false}
                    dot={(props: any) => {
                      const v = props.payload?.vo2max
                      if (v == null) return <g />
                      const c = vo2ZoneColor(v)
                      return <circle cx={props.cx} cy={props.cy} r={3.5}
                        fill={c} stroke={c} strokeWidth={1.5} />
                    }}
                    activeDot={(props: any) => {
                      const v = props.payload?.vo2max ?? 0
                      const c = vo2ZoneColor(v)
                      return <circle cx={props.cx} cy={props.cy} r={5} fill={c} stroke={c} />
                    }} />
                </LineChart>
              </ResponsiveContainer>
            )}
          </ChartPanel>

          {/* ── Monthly training load (full width, own line) ─────── */}
          <ChartPanel
            title="Monthly training load"
            sublabel={card.load?.feedback || 'current month'}
            accent={ACCENT}
          >
            <div className="min-h-[220px]">
              <LoadBalanceBars load={card.load} isLight={isLight} />
            </div>
          </ChartPanel>
        </>
      )}
    </div>
  )
}

// ─────────────────────────────────────────── hero tile

function HeroTile({
  label, value, unit, qualifier, tone, detail, isLight,
}: {
  label: string
  value: number | string | null
  unit?: string
  qualifier?: string
  tone: Tone
  detail?: string
  isLight: boolean
}) {
  const c = toneColor(tone)
  return (
    <div
      className="panel relative overflow-hidden p-5"
      style={{ ['--card-accent' as string]: c } as React.CSSProperties}
    >
      {/* Top accent stripe carries the tone */}
      <div className="absolute top-0 left-0 right-0 h-[2px]" style={{ background: c, opacity: 0.85 }} />
      {/* Soft tone wash */}
      <div className="absolute inset-0 pointer-events-none"
        style={{ background: `radial-gradient(ellipse at top left, ${c}10, transparent 65%)` }} />

      <div className="relative flex items-center gap-2 mb-2.5">
        <span className="eyebrow">{label}</span>
        <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ background: c }} />
      </div>

      <div className="relative flex items-baseline gap-2">
        <span className={clsx('text-3xl md:text-4xl font-bold tabular-nums tracking-tight',
          isLight ? 'text-gray-900' : 'text-gray-100')}>
          {value ?? '–'}
        </span>
        {unit && (
          <span className={clsx('text-sm font-medium tracking-normal', isLight ? 'text-gray-400' : 'text-gray-500')}>
            {unit}
          </span>
        )}
      </div>

      {qualifier && (
        <div className="relative text-[10px] uppercase tracking-[0.18em] font-semibold mt-1.5"
          style={{ color: c }}>
          {qualifier}
        </div>
      )}
      {detail && (
        <div className={clsx('relative text-[11px] mt-1', isLight ? 'text-gray-500' : 'text-gray-500')}>
          {detail}
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────── readiness factor bars

function FactorBars({
  factors, isLight,
}: {
  factors: { label: string; value: number | null }[]
  isLight: boolean
}) {
  if (!factors.length) {
    return <div className={clsx('text-xs py-12 text-center', isLight ? 'text-gray-400' : 'text-gray-500')}>
      No readiness data yet
    </div>
  }
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-4">
      {factors.map(f => {
        const v = f.value ?? 0
        const c = f.value != null ? readinessZoneColor(v) : ACCENT
        const label = f.value == null ? '–'
          : v >= 75 ? 'Excellent'
          : v >= 50 ? 'Good'
          : v >= 25 ? 'Fair'
          : 'Poor'
        return (
          <div key={f.label} className="space-y-1.5">
            <div className="flex items-baseline justify-between gap-2">
              <span className={clsx('text-[11px] uppercase tracking-[0.15em]', isLight ? 'text-gray-500' : 'text-gray-500')}>
                {f.label}
              </span>
              <span className="text-[11px] font-mono tabular-nums">
                <span style={{ color: c }}>{f.value != null ? `${Math.round(v)}%` : '–'}</span>
              </span>
            </div>
            <div className={clsx('relative h-2.5 rounded-full overflow-hidden', isLight ? 'bg-gray-100' : 'bg-surface-700')}>
              <div
                className="h-full rounded-full transition-all duration-300"
                style={{
                  width: `${Math.max(2, Math.min(100, v))}%`,
                  background: `linear-gradient(90deg, ${c}aa, ${c})`,
                  boxShadow: `0 0 8px ${c}55`,
                }}
              />
            </div>
            <div className={clsx('text-[10px] uppercase tracking-[0.12em]', isLight ? 'text-gray-400' : 'text-gray-500')}>
              {label}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ─────────────────────────────────────────── training load bars

type LoadData = {
  aerobic_low: number | null
  aerobic_high: number | null
  anaerobic: number | null
  targets: {
    aerobic_low: (number | null)[]
    aerobic_high: (number | null)[]
    anaerobic: (number | null)[]
  }
  feedback: string
}

function LoadBalanceBars({ load, isLight }: { load: LoadData | null; isLight: boolean }) {
  if (!load) {
    return <div className={clsx('text-xs py-12 text-center', isLight ? 'text-gray-400' : 'text-gray-500')}>
      No training-load data yet
    </div>
  }
  const buckets: { key: keyof typeof load.targets; label: string; value: number | null }[] = [
    { key: 'aerobic_low',  label: 'Aerobic low',  value: load.aerobic_low },
    { key: 'aerobic_high', label: 'Aerobic high', value: load.aerobic_high },
    { key: 'anaerobic',    label: 'Anaerobic',    value: load.anaerobic },
  ]
  const maxAxis = Math.max(
    ...buckets.flatMap(b => {
      const t = load.targets[b.key]
      return [b.value ?? 0, t[1] ?? 0]
    }),
    1,
  ) * 1.15

  // Color rule: green when value lands inside the personal target window;
  // amber if you've gone over the upper bound (overdoing it); red if you
  // fell short of the lower bound (undertraining this bucket).
  const colorFor = (val: number, tmin: number, tmax: number) =>
    val < tmin ? NEG : val > tmax ? '#f59e0b' : POS

  const rectBorder = isLight ? 'rgba(148, 163, 184, 0.7)' : 'rgba(148, 163, 184, 0.45)'

  return (
    <div className="flex flex-col justify-around h-full py-1">
      {buckets.map(b => {
        const target = load.targets[b.key]
        const tmin = target[0] ?? 0
        const tmax = target[1] ?? 0
        const val = b.value ?? 0
        const barColor = colorFor(val, tmin, tmax)
        const valuePct = (val / maxAxis) * 100
        const minPct = (tmin / maxAxis) * 100
        const widthPct = ((tmax - tmin) / maxAxis) * 100
        return (
          <div key={b.key}>
            <div className="flex items-baseline justify-between mb-1.5">
              <span className={clsx('text-[11px] uppercase tracking-[0.15em]', isLight ? 'text-gray-500' : 'text-gray-500')}>
                {b.label}
              </span>
              <span className="text-[11px] font-mono tabular-nums" style={{ color: barColor }}>
                {Math.round(val)}
              </span>
            </div>
            {/* Track: bar passes THROUGH the target rectangle.
                Container has no background — the rectangle is just an
                outline, the bar is a solid horizontal stripe centered in it. */}
            <div className="relative h-9">
              {/* Target rectangle outline (the "personal range") */}
              <div
                className="absolute top-0 bottom-0 rounded-lg"
                style={{
                  left: `${minPct}%`,
                  width: `${widthPct}%`,
                  border: `1.5px solid ${rectBorder}`,
                }}
              />
              {/* Value bar — solid colored stripe, vertically centered */}
              <div
                className="absolute rounded-full transition-all duration-300"
                style={{
                  left: 0,
                  width: `${valuePct}%`,
                  top: '50%',
                  height: 10,
                  transform: 'translateY(-50%)',
                  background: barColor,
                  boxShadow: `0 0 10px ${barColor}55`,
                }}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}
