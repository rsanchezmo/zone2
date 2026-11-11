import { useQuery, useMutation, useQueryClient, type QueryClient } from '@tanstack/react-query';
import api, { type IsoDate } from './client';
import type { Activity } from './activities';
import type { GarminSyncState, Segment } from './workouts';

export type SessionIntensity = 'easy' | 'moderate' | 'hard' | 'race';

export interface TrainingSession {
  id: number;
  date: IsoDate;
  title: string;
  sport_type: string;
  description: string | null;
  planned_distance_km: number | null;
  planned_duration_mins: number | null;
  planned_intensity: SessionIntensity | null;
  target_avg_pace: number | null;
  target_pace_min: number | null;
  target_pace_max: number | null;
  target_hr_zone: number | null;
  target_zone_pct: number | null;
  segments: Segment[] | null;
  workout_template_id: number | null;
  /** The coach's plan it belongs to, and that plan's name. */
  plan_id: number | null;
  plan_name?: string | null;
  completed: boolean;
  created_at: string;
  /** Its entry on the Garmin calendar; null when it has none. */
  garmin_sync_state: GarminSyncState | null;
  garmin_sync_error: string | null;
}

/** What a session form sets; a null clears the field on update, an absent one leaves it. */
export interface SessionFields {
  sport_type: string;
  description?: string | null;
  planned_distance_km?: number | null;
  planned_duration_mins?: number | null;
  planned_intensity?: SessionIntensity | null;
  target_avg_pace?: number | null;
  target_pace_min?: number | null;
  target_pace_max?: number | null;
  target_hr_zone?: number | null;
  target_zone_pct?: number | null;
  segments?: Segment[] | null;
  workout_template_id?: number | null;
}

export interface SessionCreateInput extends SessionFields {
  date: IsoDate;
  title: string;
}

export interface SessionUpdateInput extends Partial<SessionCreateInput> {
  completed?: boolean;
}

export function useCalendarSessionsByRange(dateFrom?: string, dateTo?: string) {
  return useQuery<TrainingSession[]>({
    queryKey: ['calendar-sessions-range', dateFrom, dateTo],
    queryFn: () =>
      api.get('/calendar/sessions', { params: { date_from: dateFrom, date_to: dateTo } }).then(r => r.data),
    enabled: !!dateFrom && !!dateTo,
    // Watch workouts are sent in the background after an edit: poll until they land
    refetchInterval: q => (q.state.data?.some(s => s.garmin_sync_state === 'pending') ? 2000 : false),
  });
}

export interface BriefingRecovery {
  /** Garmin's wake-up readiness, or its latest snapshot until that exists. */
  readiness: { score: number; level: string | null; feedback: string | null; at_wakeup: boolean; time: string | null } | null;
  recovery_hours: number | null;
  sleep: { score: number; qualifier: string | null; seconds: number | null } | null;
  hrv: { last_night: number; weekly: number | null; status: string | null } | null;
  body_battery: { at_wake: number; now: number | null } | null;
  resting_hr: { today: number; avg_7d: number | null } | null;
}

export interface Briefing {
  date: string;
  sessions: TrainingSession[];
  done: Activity[];
  /** Null without Garmin, or before today's Garmin data has synced. */
  recovery: BriefingRecovery | null;
  form: { date: string; fitness: number; fatigue: number; form_pct: number | null } | null;
  suggestion: { tone: 'caution' | 'go' | 'rest' | 'info'; text: string } | null;
}

export function useBriefing() {
  return useQuery<Briefing>({
    queryKey: ['briefing'],
    queryFn: () => api.get('/calendar/briefing').then(r => r.data),
    staleTime: 1000 * 60 * 5,
  });
}

/** Everything a planned session feeds: the calendar, scores, plan completion,
 *  the fitness projection and the saved workouts (a new one is saved with it). */
function invalidateSessionQueries(qc: QueryClient) {
  for (const key of ['calendar-sessions-range', 'session-scores', 'activity-score', 'plan-accomplishment', 'fitness-form', 'briefing', 'workout-templates']) {
    qc.invalidateQueries({ queryKey: [key] });
  }
}

export function useCreateSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: SessionCreateInput) =>
      api.post<TrainingSession>('/calendar/sessions', data).then(r => r.data),
    onSuccess: () => invalidateSessionQueries(qc),
  });
}

export function useUpdateSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: { id: number } & SessionUpdateInput) =>
      api.put<TrainingSession>(`/calendar/sessions/${id}`, data).then(r => r.data),
    onSuccess: () => invalidateSessionQueries(qc),
  });
}

export function useDeleteSession() {
  const qc = useQueryClient();
  return useMutation({
    // 204 No Content
    mutationFn: (id: number) => api.delete<void>(`/calendar/sessions/${id}`).then(r => r.data),
    onSuccess: () => invalidateSessionQueries(qc),
  });
}

/** Rates are null when no planned sessions fall in the corresponding window. */
export interface PlanAccomplishment {
  total_planned: number;
  total_completed: number;
  rate: number | null;
  recent_planned: number;
  recent_completed: number;
  recent_rate: number | null;
  window_days: number;
}

export function usePlanAccomplishment() {
  return useQuery<PlanAccomplishment>({
    queryKey: ['plan-accomplishment'],
    queryFn: () => api.get('/calendar/sessions/accomplishment').then(r => r.data),
    staleTime: 1000 * 60 * 5,
  });
}

export type CalendarFeedUrl = {
  token: string;
  url: string;
  env_managed: boolean;
  last_fetched_at: string | null;
  /** Who last fetched it: "Google Calendar", "Apple Calendar", or the client's User-Agent. */
  last_fetched_by: string | null;
};

export function useCalendarFeedUrl() {
  return useQuery({
    queryKey: ['calendar-feed-url'],
    queryFn: () => api.get('/calendar/feed-url').then(r => r.data as CalendarFeedUrl),
    staleTime: 1000 * 60 * 5,
    refetchOnWindowFocus: true,
  });
}

export function useRotateCalendarFeedToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.post('/calendar/feed-url/rotate').then(r => r.data as CalendarFeedUrl),
    onSuccess: (data) => {
      qc.setQueryData(['calendar-feed-url'], data);
    },
  });
}

export interface WatchWorkoutsSetting {
  /** Garmin Connect is configured. */
  available: boolean;
  enabled: boolean;
}

export function useWatchWorkouts() {
  return useQuery<WatchWorkoutsSetting>({
    queryKey: ['watch-workouts'],
    queryFn: () => api.get('/calendar/watch-workouts').then(r => r.data),
    staleTime: 1000 * 60 * 60,
  });
}

export function useSetWatchWorkouts() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (enabled: boolean) =>
      api.put<WatchWorkoutsSetting>('/calendar/watch-workouts', { enabled }).then(r => r.data),
    onSuccess: data => {
      qc.setQueryData(['watch-workouts'], data);
      qc.invalidateQueries({ queryKey: ['calendar-sessions-range'] });
    },
  });
}

/** One scored metric from the execution-score engine. The exact keys depend
 * on the metric kind (distance/duration/pace/hr_zone), so everything but the
 * score is optional. */
export interface ScoreMetric {
  score: number;
  target?: number | null;
  actual?: number | null;
  unit?: string;
  target_min?: number | null;
  target_max?: number | null;
  target_zone?: number;
  target_pct?: number;
  actual_pct?: number;
  [key: string]: unknown;
}

export interface SegmentScore {
  segment_idx: number;
  type: string;
  is_recovery: boolean;
  rep: number;
  label: string | null;
  distance_km: number | null;
  duration_mins: number | null;
  start_km: number;
  end_km: number;
  actual_distance_km: number;
  actual_duration_mins: number;
  /** Stopped time inside the segment (lights, auto-pause); excluded from pace. */
  stopped_s: number;
  overall_score: number | null;
  metrics: Record<string, ScoreMetric>;
  actual_pace?: number | null;
  pace_unit?: string;
}

export interface ExecutionScore {
  overall_score: number;
  matched_activity_id: number | null;
  /** 'segmented' for structured workouts scored per segment. */
  mode?: string;
  metrics?: Record<string, ScoreMetric>;
  segment_scores?: SegmentScore[];
}

/** Keyed by session id; null when no activity matched the session. */
export type SessionScoresResponse = Record<string, ExecutionScore | null>;

export function useSessionScores(dateFrom?: string, dateTo?: string) {
  return useQuery<SessionScoresResponse>({
    queryKey: ['session-scores', dateFrom, dateTo],
    queryFn: () =>
      api.get('/calendar/sessions/scores', { params: { date_from: dateFrom, date_to: dateTo } }).then(r => r.data),
    enabled: !!dateFrom && !!dateTo,
    staleTime: 1000 * 60 * 5,
  });
}

export interface ActivityScoreResponse {
  session: TrainingSession;
  score: ExecutionScore;
}

export function useActivityScore(activityId?: number) {
  return useQuery<ActivityScoreResponse | null>({
    queryKey: ['activity-score', activityId],
    queryFn: () =>
      api.get(`/calendar/sessions/score-by-activity/${activityId}`).then(r => r.data),
    enabled: !!activityId,
    staleTime: 1000 * 60 * 5,
  });
}
