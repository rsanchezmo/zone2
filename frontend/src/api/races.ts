import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import api from './client';

export interface RaceEvent {
  id: number;
  name: string;
  date: string;
  sport_type: string;
  distance_km: number | null;
  target_pace: number | null;
  description: string | null;
  location: string | null;
  url: string | null;
  created_at: string;
}

export type RaceEventInput = Omit<RaceEvent, 'id' | 'created_at'>;

export function useRaceEvents() {
  return useQuery<RaceEvent[]>({
    queryKey: ['race-events'],
    queryFn: () => api.get('/races/').then(r => r.data),
    placeholderData: keepPreviousData,
  });
}

export function useRaceEventsByRange(dateFrom?: string, dateTo?: string) {
  return useQuery<RaceEvent[]>({
    queryKey: ['race-events-range', dateFrom, dateTo],
    queryFn: () =>
      api.get('/races/', { params: { date_from: dateFrom, date_to: dateTo } }).then(r => r.data),
    enabled: !!dateFrom && !!dateTo,
  });
}

export function useUpcomingRaces() {
  return useQuery<RaceEvent[]>({
    queryKey: ['upcoming-races'],
    queryFn: () => api.get('/races/upcoming').then(r => r.data),
  });
}

export function useCreateRaceEvent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: RaceEventInput) =>
      api.post<RaceEvent>('/races/', data).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['race-events'] });
      qc.invalidateQueries({ queryKey: ['race-events-range'] });
      qc.invalidateQueries({ queryKey: ['upcoming-races'] });
    },
  });
}

export function useUpdateRaceEvent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: { id: number } & Partial<RaceEventInput>) =>
      api.put<RaceEvent>(`/races/${id}`, data).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['race-events'] });
      qc.invalidateQueries({ queryKey: ['race-events-range'] });
      qc.invalidateQueries({ queryKey: ['upcoming-races'] });
    },
  });
}

export function useDeleteRaceEvent() {
  const qc = useQueryClient();
  return useMutation({
    // 204 No Content
    mutationFn: (id: number) => api.delete<void>(`/races/${id}`).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['race-events'] });
      qc.invalidateQueries({ queryKey: ['race-events-range'] });
      qc.invalidateQueries({ queryKey: ['upcoming-races'] });
    },
  });
}
