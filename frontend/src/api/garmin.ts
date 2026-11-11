import { useEffect, useRef } from 'react';
import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import api from './client';

export interface GarminMetricCoverage {
  metric: string;
  n: number;
  earliest: string | null;
  latest: string | null;
}

export interface GarminStatus {
  enabled: boolean;
  client_error: string | null;
  syncing: boolean;
  last_error: string | null;
  last_summary: Record<string, unknown> | null;
  earliest_date: string | null;
  latest_date: string | null;
  last_sync_at: string | null;
  total_days: number;
  total_rows: number;
  per_metric: GarminMetricCoverage[];
}

/** One day of Garmin intraday data. Times are local wall-clock ms: format them as UTC. */
export interface GarminDay {
  date: string;
  start: number;
  end: number;
  heart_rate: [number, number][];
  stress: [number, number][];
  body_battery: [number, number][];
  respiration: [number, number][];
  spo2: [number, number][];
  sleep: { start: number; end: number; stage: 'deep' | 'light' | 'rem' | 'awake' }[];
  activities: { id: number; name: string | null; sport_type: string | null; start: number; end: number }[];
}

export function useGarminDay(day: string | null) {
  return useQuery<GarminDay>({
    queryKey: ['garmin-day', day],
    queryFn: () => api.get(`/garmin/day/${day}`).then(r => r.data),
    enabled: !!day,
    retry: false,
    staleTime: 1000 * 60 * 10,
    placeholderData: keepPreviousData,
  });
}

export function useGarminStatus() {
  const qc = useQueryClient();
  const query = useQuery<GarminStatus>({
    queryKey: ['garmin-status'],
    queryFn: () => api.get('/garmin/status').then(r => r.data),
    refetchInterval: (q) => (q.state.data?.syncing ? 2000 : false),
  });

  // The sync endpoint returns "started" immediately and runs in the
  // background, so fresh data only exists once polling sees syncing flip
  // back to false — invalidate the derived queries on that transition.
  const syncing: boolean = query.data?.syncing ?? false;
  const wasSyncing = useRef(false);
  useEffect(() => {
    if (wasSyncing.current && !syncing) {
      qc.invalidateQueries({ queryKey: ['garmin-latest'] });
      qc.invalidateQueries({ queryKey: ['garmin-trends'] });
      qc.invalidateQueries({ queryKey: ['garmin-events'] });
    }
    wasSyncing.current = syncing;
  }, [qc, syncing]);

  return query;
}

// Raw Garmin Connect payloads are deeply nested and device-dependent; only
// the paths the app reads are typed, everything else stays behind index
// signatures with unknown leaves.

export interface GarminSleepPayload {
  dailySleepDTO?: {
    sleepTimeSeconds?: number | null;
    sleepScores?: {
      overall?: { value?: number | null; qualifierKey?: string | null; [key: string]: unknown } | null;
      [key: string]: unknown;
    } | null;
    sleepScoreFeedback?: string | null;
    sleepScoreInsight?: string | null;
    [key: string]: unknown;
  } | null;
  [key: string]: unknown;
}

export interface GarminHrvPayload {
  hrvSummary?: {
    lastNightAvg?: number | null;
    weeklyAvg?: number | null;
    status?: string | null;
    feedbackPhrase?: string | null;
    [key: string]: unknown;
  } | null;
  [key: string]: unknown;
}

export interface GarminTrainingReadinessPayload {
  score?: number | null;
  level?: string | null;
  recoveryTime?: number | null;
  feedbackShort?: string | null;
  sleepScoreFactorPercent?: number | null;
  recoveryTimeFactorPercent?: number | null;
  acwrFactorPercent?: number | null;
  hrvFactorPercent?: number | null;
  stressHistoryFactorPercent?: number | null;
  sleepHistoryFactorPercent?: number | null;
  [key: string]: unknown;
}

export interface GarminTrainingStatusPayload {
  mostRecentVO2Max?: {
    generic?: {
      vo2MaxPreciseValue?: number | null;
      vo2MaxValue?: number | null;
      calendarDate?: string | null;
      [key: string]: unknown;
    } | null;
    [key: string]: unknown;
  } | null;
  /** Per-device maps ({deviceId: {...}}); consumers take the first entry. */
  mostRecentTrainingLoadBalance?: {
    metricsTrainingLoadBalanceDTOMap?: Record<string, Record<string, unknown>> | null;
    [key: string]: unknown;
  } | null;
  mostRecentTrainingStatus?: {
    latestTrainingStatusData?: Record<string, Record<string, unknown>> | null;
    [key: string]: unknown;
  } | null;
  [key: string]: unknown;
}

export interface GarminHeartRatesPayload {
  restingHeartRate?: number | null;
  lastSevenDaysAvgRestingHeartRate?: number | null;
  [key: string]: unknown;
}

export interface GarminStressPayload {
  avgStressLevel?: number | null;
  maxStressLevel?: number | null;
  [key: string]: unknown;
}

export interface GarminBodyBatteryPayload {
  charged?: number | null;
  drained?: number | null;
  [key: string]: unknown;
}

export interface GarminDailyStepsPayload {
  totalSteps?: number | null;
  stepGoal?: number | null;
  totalDistance?: number | null;
  [key: string]: unknown;
}

export interface GarminUserSummaryPayload {
  activeKilocalories?: number | null;
  totalKilocalories?: number | null;
  floorsAscended?: number | null;
  averageSpo2?: number | null;
  [key: string]: unknown;
}

export interface GarminSpo2Payload {
  averageSpO2?: number | null;
  avgSleepSpO2?: number | null;
  [key: string]: unknown;
}

export interface GarminIntensityMinutesPayload {
  moderateMinutes?: number | null;
  vigorousMinutes?: number | null;
  [key: string]: unknown;
}

export interface GarminLatestEntry<P = Record<string, unknown>> {
  date: string;
  payload: P;
}

/** Most-recent cached payload per metric; null when a metric was never
 * synced. Every configured metric key is present in the response. */
export interface GarminLatestResponse {
  sleep?: GarminLatestEntry<GarminSleepPayload> | null;
  hrv?: GarminLatestEntry<GarminHrvPayload> | null;
  training_readiness?: GarminLatestEntry<GarminTrainingReadinessPayload> | null;
  training_status?: GarminLatestEntry<GarminTrainingStatusPayload> | null;
  heart_rates?: GarminLatestEntry<GarminHeartRatesPayload> | null;
  stress?: GarminLatestEntry<GarminStressPayload> | null;
  body_battery?: GarminLatestEntry<GarminBodyBatteryPayload> | null;
  daily_steps?: GarminLatestEntry<GarminDailyStepsPayload> | null;
  user_summary?: GarminLatestEntry<GarminUserSummaryPayload> | null;
  spo2?: GarminLatestEntry<GarminSpo2Payload> | null;
  intensity_minutes?: GarminLatestEntry<GarminIntensityMinutesPayload> | null;
  [metric: string]: GarminLatestEntry | null | undefined;
}

export function useGarminLatest() {
  return useQuery<GarminLatestResponse>({
    queryKey: ['garmin-latest'],
    queryFn: () => api.get('/garmin/latest').then(r => r.data),
    staleTime: 1000 * 60 * 5,
  });
}

/** One day of a metric's slim chart summary (see zone2/garmin_extractors.py);
 * the fields vary per metric, so everything beyond the date stays unknown. */
export type GarminTrendRow = Record<string, unknown> & { date: string };

export interface GarminTrends {
  start_date: string;
  end_date: string;
  days: number;
  metrics: Record<string, GarminTrendRow[]>;
}

/** `metrics` narrows the payload to those summaries (all of them when omitted). */
export function useGarminTrends(days: number = 30, metrics?: readonly string[], enabled: boolean = true) {
  return useQuery<GarminTrends>({
    queryKey: ['garmin-trends', days, metrics?.join(',') ?? 'all'],
    queryFn: () => api.get('/garmin/trends', { params: { days, metrics: metrics?.join(',') } }).then(r => r.data),
    staleTime: 1000 * 60 * 5,
    placeholderData: keepPreviousData,
    enabled,
  });
}

/** One Move IQ auto-detected activity (not recorded on the watch). Local
 * timestamps come as `YYYY-MM-DDTHH:MM:SS.0` — slice, don't Date-parse. */
export interface GarminAutoEvent {
  date: string;
  activity_type: string | null;
  activity_sub_type: string | null;
  start_local: string | null;
  end_local: string | null;
  duration_mins: number | null;
}

export interface GarminEventsResponse {
  start_date: string;
  end_date: string;
  days: number;
  events: GarminAutoEvent[];
}

export function useGarminEvents(days: number = 14) {
  return useQuery<GarminEventsResponse>({
    queryKey: ['garmin-events', days],
    queryFn: () => api.get('/garmin/events', { params: { days } }).then(r => r.data),
    staleTime: 1000 * 60 * 5,
    placeholderData: keepPreviousData,
  });
}

export function useTriggerGarminSync() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: { full?: boolean } = {}) =>
      api.post<{ status: string; full?: boolean }>('/garmin/sync', null, { params }).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['garmin-status'] });
    },
  });
}

export function useCancelGarminSync() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ status: string }>('/garmin/sync/cancel').then(r => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['garmin-status'] }),
  });
}

export interface ActivityCost {
  body_battery: { impact: number | null; start: number | null; end: number | null; effect: string | null } | null;
  recovery_hours: number | null;
  night: {
    date: string;
    sleep_score: number | null;
    sleep_score_normal: number | null;
    sleep_seconds: number | null;
    hrv: number | null;
    hrv_balanced_low: number | null;
    hrv_balanced_upper: number | null;
    hrv_status: string | null;
    resting_hr: number | null;
    resting_hr_normal: number | null;
    body_battery_charged: number | null;
    readiness: number | null;
    readiness_level: string | null;
  } | null;
}

export function useActivityCost(activityId?: number) {
  return useQuery<ActivityCost>({
    queryKey: ['activity-cost', activityId],
    queryFn: () => api.get(`/garmin/activity-cost/${activityId}`).then(r => r.data),
    enabled: !!activityId,
    staleTime: 1000 * 60 * 30,
  });
}
