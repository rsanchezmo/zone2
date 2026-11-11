import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import api from './client';
import type { RaceEvent } from './races';

export interface PlanPhase { name: string; start: string; end: string; target_km: number | null }

export interface CoachPlanSummary {
  id: number;
  name: string;
  status: 'active' | 'done' | 'abandoned';
  goal: string | null;
  goal_time_s: number | null;
  start_date: string;
  end_date: string;
  race: RaceEvent | null;
  sessions: { total: number; due: number; done: number; completion_pct: number | null };
  completion_pct: number | null;
  average_score: number | null;
  days_to_race: number;
  phase: string | null;
  /** z2's prediction now for the race distance. */
  prediction_s: number | null;
  /** Whose prediction `prediction_s` is: Garmin's when it predicts the race distance, else z2's. */
  prediction_source: 'garmin' | 'z2' | null;
  /** The race time, once run. */
  result_s: number | null;
}

export interface CoachPlanSession {
  id: number;
  date: string;
  title: string;
  sport_type: string;
  description: string | null;
  planned_distance_km: number | null;
  planned_intensity: string | null;
  garmin_sync_state: string | null;
  done: boolean;
  /** Execution score against the session's targets; null when it has none or nothing matched. */
  score: number | null;
  activity_id: number | null;
}

export interface PlanCheckpoint {
  id: number;
  date: string;
  title: string;
  /** The decision thresholds, agreed before the checkpoint. */
  rule: string;
  session_id: number | null;
  result: string | null;
  decision: string | null;
}

export type CoachLogKind = 'review' | 'change' | 'decision' | 'suggestion' | 'summary';

export interface CoachLogEntry {
  id: number;
  plan_id: number | null;
  date: string;
  kind: CoachLogKind;
  title: string;
  body: string | null;
  session_id: number | null;
  activity_id: number | null;
  /** Suggestions only. */
  status: 'open' | 'done' | 'dismissed' | null;
  created_at: string;
}

export interface CoachPlan extends Omit<CoachPlanSummary, 'sessions' | 'completion_pct' | 'average_score' | 'days_to_race' | 'phase' | 'prediction_s' | 'prediction_source' | 'result_s'> {
  summary: string | null;
  phases: PlanPhase[] | null;
  progress: {
    today: string;
    days_to_race: number;
    phase: string | null;
    sessions: { total: number; due: number; done: number; completion_pct: number | null };
    score: { average: number | null; scored: number };
    weeks: { week_start: string; phase: string | null; target_km: number | null; planned_km: number; done_km: number | null }[];
    prediction: {
      distance: string;
      goal_s: number | null;
      /** Garmin's when it predicts the race distance and did lately, else z2's. */
      now_s: number | null;
      source: 'garmin' | 'z2';
      z2_now_s: number | null;
      range_s: [number | null, number | null];
      z2: { date: string; time_s: number }[];
      garmin: { date: string; time_s: number }[];
    } | null;
    form: { date: string; fitness: number; fatigue: number; form_pct: number } | null;
    /** The race itself, once run. */
    result: { activity_id: number | null; time_s: number | null; distance_km: number | null } | null;
  };
  sessions: CoachPlanSession[];
  checkpoints: PlanCheckpoint[];
  /** What the coach keeps for this plan only, read with the plan rather than in every turn. */
  agreements: CoachNote[];
  log: CoachLogEntry[];
}

export type CoachNoteTopic = 'kit' | 'body' | 'rules' | 'preferences';

/** A note about the athlete (`plan_id` null, with a topic), or an agreement of one plan. */
export interface CoachNote { id: number; note: string; topic: CoachNoteTopic | null; plan_id: number | null; added: string }

export function useCoachPlans() {
  return useQuery<CoachPlanSummary[]>({
    queryKey: ['coach-plans'],
    queryFn: () => api.get('/coach/plans').then(r => r.data),
    staleTime: 1000 * 60 * 5,
  });
}

export function useCoachPlan(planId: number | undefined) {
  return useQuery<CoachPlan>({
    queryKey: ['coach-plan', planId],
    queryFn: () => api.get(`/coach/plans/${planId}`).then(r => r.data),
    enabled: planId != null,
    staleTime: 1000 * 60 * 5,
  });
}

export function useCoachNotes() {
  return useQuery<CoachNote[]>({
    queryKey: ['coach-notes'],
    queryFn: () => api.get('/coach/notes').then(r => r.data),
    staleTime: 1000 * 60 * 5,
  });
}

export function useDeleteCoachNote() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (noteId: number) => api.delete(`/coach/notes/${noteId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['coach-notes'] });
      qc.invalidateQueries({ queryKey: ['coach-plan'] });
    },
  });
}

export function useUpdateSuggestion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: number; status: 'done' | 'dismissed' | 'open' }) =>
      api.put(`/coach/log/${id}`, { status }).then(r => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['coach-plan'] }),
  });
}
