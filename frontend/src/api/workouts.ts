import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import api from './client';

export interface Segment {
  type: 'warmup' | 'work' | 'recovery' | 'cooldown' | 'rest';
  distance_km?: number | null;
  duration_mins?: number | null;
  target_pace_min?: number | null;
  target_pace_max?: number | null;
  target_hr_zone?: number | null;
  target_zone_pct?: number | null;
  repetitions?: number | null;
  recovery_duration_mins?: number | null;
  recovery_distance_km?: number | null;
  label?: string | null;
}

export type GarminSyncState = 'pending' | 'synced' | 'failed';

export interface WorkoutTemplate {
  id: number;
  name: string;
  sport_type: string;
  description: string | null;
  created_at: string;
  segments: Segment[];
  /** Its copy in the Garmin library (runs, while sending is on). */
  garmin_workout_id: number | null;
  garmin_sync_state: GarminSyncState | null;
  garmin_sync_error: string | null;
  /** Planned sessions that use it. */
  uses: number;
}

export interface WorkoutTemplateInput {
  name: string;
  sport_type: string;
  description?: string | null;
  segments: Segment[];
}

export function useWorkoutTemplates(sportType?: string) {
  return useQuery<WorkoutTemplate[]>({
    // One request for every sport; changing the sport filters what's loaded
    queryKey: ['workout-templates'],
    queryFn: () => api.get('/workouts').then(r => r.data),
    select: sportType ? templates => templates.filter(t => t.sport_type === sportType) : undefined,
    // Garmin copies are made in the background: poll until they land
    refetchInterval: q => (q.state.data?.some(t => t.garmin_sync_state === 'pending') ? 2000 : false),
  });
}

/** A workout made in Garmin Connect (z2 leaves these alone), its steps read as segments. */
export interface GarminLibraryWorkout {
  workout_id: number;
  name: string;
  sport_type: string;
  created_at: string | null;
  distance_km: number | null;
  duration_s: number | null;
  segments: Segment[];
}

export function useGarminLibrary(enabled: boolean) {
  return useQuery<GarminLibraryWorkout[]>({
    queryKey: ['garmin-library'],
    queryFn: () => api.get('/workouts/garmin').then(r => r.data),
    enabled,
    staleTime: 1000 * 60 * 10,
    retry: false,
  });
}

export function useCreateWorkoutTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: WorkoutTemplateInput) =>
      api.post<WorkoutTemplate>('/workouts', data).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['workout-templates'] });
    },
  });
}

export function useUpdateWorkoutTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: { id: number } & Partial<WorkoutTemplateInput>) =>
      api.put<WorkoutTemplate>(`/workouts/${id}`, data).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['workout-templates'] });
    },
  });
}

export function useDeleteWorkoutTemplate() {
  const qc = useQueryClient();
  return useMutation({
    // 204 No Content
    mutationFn: (id: number) => api.delete<void>(`/workouts/${id}`).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['workout-templates'] });
    },
  });
}
