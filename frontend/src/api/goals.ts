import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import api from './client';

export type GoalMetric = 'distance_km' | 'time_hours' | 'activities' | 'elevation_m'
export type GoalPeriod = 'weekly' | 'monthly' | 'yearly'

export interface Goal {
  id: number;
  year: number;
  /** Sport type or '__all__'. */
  sport_type: string;
  metric: GoalMetric;
  period: GoalPeriod;
  target_value: number;
  created_at: string;
}

export interface GoalInput {
  year: number;
  /** Sport type or '__all__'. */
  sport_type: string;
  metric: GoalMetric;
  period: GoalPeriod;
  target_value: number;
}

export function useGoals(year?: number) {
  return useQuery<Goal[]>({
    queryKey: ['goals', year],
    queryFn: () => api.get('/goals/', { params: year ? { year } : {} }).then(r => r.data),
    placeholderData: keepPreviousData,
  });
}

export function useCreateGoal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: GoalInput) =>
      api.post<Goal>('/goals/', data).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['goals'] });
      qc.invalidateQueries({ queryKey: ['goal-progress'] });
    },
  });
}

export function useUpdateGoal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: { id: number } & Partial<GoalInput>) =>
      api.put<Goal>(`/goals/${id}`, data).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['goals'] });
      qc.invalidateQueries({ queryKey: ['goal-progress'] });
    },
  });
}

export function useDeleteGoal() {
  const qc = useQueryClient();
  return useMutation({
    // 204 No Content
    mutationFn: (id: number) => api.delete<void>(`/goals/${id}`).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['goals'] });
      qc.invalidateQueries({ queryKey: ['goal-progress'] });
    },
  });
}

export interface GoalProgress extends Goal {
  current_value: number;
  percentage: number;
  period_start: string;
  period_end: string;
}

export function useGoalProgress(weekStart?: string) {
  return useQuery<{ goals: GoalProgress[] }>({
    queryKey: ['goal-progress', weekStart],
    queryFn: () =>
      api.get('/goals/progress', { params: { week_start: weekStart } }).then(r => r.data),
    enabled: !!weekStart,
  });
}
