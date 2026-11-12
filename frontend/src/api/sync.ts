import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import api from './client';
import { invalidateActivityQueries } from './invalidation';

export interface SyncStatus {
  /** Whether z2 holds a Strava token the athlete granted and Strava still accepts */
  connected: boolean;
  syncing: boolean;
  last_error: string | null;
  last_sync_at: string | null;
  total_activities: number;
  needs_sync: boolean;
  last_activity_date: string | null;
  earliest_activity_date: string | null;
  athlete_name: string | null;
  cache_version: number;
}

export function useSyncStatus() {
  return useQuery<SyncStatus>({
    queryKey: ['sync-status'],
    queryFn: () => api.get('/sync/status').then(r => r.data),
    refetchInterval: (query) => query.state.data?.syncing ? 2000 : false,
  });
}

export function useTriggerSync() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: { full_sync?: boolean; include_streams?: boolean } = {}) =>
      api.post<{ status: string }>('/sync', null, { params }).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['sync-status'] });
    },
  });
}

export function useResyncActivity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, includeStreams = false }: { id: number | string; includeStreams?: boolean }) =>
      api.post<{ status: string }>(`/sync/activity/${id}`, null, { params: { include_streams: includeStreams } }).then(r => r.data),
    onSuccess: () => invalidateActivityQueries(qc),
  });
}

export function useBackfillStreams() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ status: string }>('/sync/backfill-streams').then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['sync-status'] });
      qc.invalidateQueries({ queryKey: ['cache-completeness'] });
    },
  });
}

export interface CacheCompletenessSection {
  complete: number;
  missing: number;
  total_expected: number;
}

export interface CacheCompleteness {
  total: number;
  streams: CacheCompletenessSection;
  photos: CacheCompletenessSection;
  detail: CacheCompletenessSection;
  missing_streams_ids: number[];
  missing_photos_ids: number[];
  missing_detail_ids: number[];
}

export function useCacheCompleteness(isSyncing?: boolean) {
  return useQuery<CacheCompleteness>({
    queryKey: ['cache-completeness'],
    queryFn: () => api.get('/sync/cache-completeness').then(r => r.data),
    staleTime: isSyncing ? 0 : 1000 * 60 * 5,
    refetchInterval: isSyncing ? 3000 : false,
  });
}
