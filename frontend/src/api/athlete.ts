import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import api from './client';

export interface AthleteGear {
  id: string;
  name: string;
  nickname?: string | null;
  primary?: boolean;
  retired?: boolean;
  distance?: number | null;
  converted_distance?: number | null;
  [key: string]: unknown;
}

/** Raw Strava athlete payload (plus merged retired gear). Only the fields the
 * app consumes are typed; the rest stays reachable through the index
 * signature. */
export interface AthleteProfile {
  id?: number;
  username?: string | null;
  firstname?: string | null;
  lastname?: string | null;
  city?: string | null;
  state?: string | null;
  country?: string | null;
  sex?: string | null;
  premium?: boolean;
  summit?: boolean;
  created_at?: string;
  updated_at?: string;
  profile?: string | null;
  profile_medium?: string | null;
  weight?: number | null;
  ftp?: number | null;
  follower_count?: number | null;
  friend_count?: number | null;
  shoes?: AthleteGear[];
  bikes?: AthleteGear[];
  [key: string]: unknown;
}

export interface AppConfig {
  carto_api_key: string | null;
}

/** Runtime backend settings. Effectively immutable for the life of the tab,
 * so it never refetches — every map mounts against the same cached value.
 * `pending` distinguishes "key not fetched yet" from "no key configured", so
 * a keyed setup doesn't paint the OSM fallback for one frame on first load. */
export function useAppConfig() {
  const { data, isPending } = useQuery<AppConfig>({
    queryKey: ['app-config'],
    queryFn: () => api.get('/config').then(r => r.data),
    staleTime: Infinity,
  });
  return { cartoApiKey: data?.carto_api_key, pending: isPending };
}

/** Sends the browser to Strava's consent page, which comes back to the backend's callback and
 *  from there to this page, with `?strava=connected` or `?strava_error=…`. */
export function useConnectStrava() {
  return useMutation({
    mutationFn: () =>
      api.post<{ url: string }>('/athlete/strava/connect', {
        origin: window.location.origin,
        return_to: window.location.pathname + window.location.search,
      }).then(r => r.data),
    onSuccess: ({ url }) => window.location.assign(url),
  });
}

export function useAthleteProfile() {
  return useQuery<AthleteProfile>({
    queryKey: ['athlete-profile'],
    queryFn: () => api.get('/athlete/profile').then(r => r.data),
    staleTime: 1000 * 60 * 60, // 1 hour
  });
}

export interface HrZoneBound {
  min: number;
  max: number;
}

export type HrZonesSource = 'strava' | 'estimated' | 'manual' | 'garmin';

export interface AthleteZonesResponse {
  heart_rate: {
    zones: HrZoneBound[] | null;
    max_hr: number | null;
    source: HrZonesSource;
    requested_source: HrZonesSource;
    fallback_reason: string | null;
    /** Lactate threshold the zones are built on (Garmin only) */
    threshold_hr: number | null;
  };
}

export function useAthleteZones() {
  return useQuery<AthleteZonesResponse>({
    queryKey: ['athlete-zones'],
    queryFn: () => api.get('/athlete/zones').then(r => r.data),
    staleTime: 1000 * 60 * 60,
  });
}

export interface ZonesSettings {
  source: HrZonesSource;
  manual_zones: HrZoneBound[] | null;
  garmin_available: boolean;
}

export function useZonesSettings() {
  return useQuery<ZonesSettings>({
    queryKey: ['zones-settings'],
    queryFn: () => api.get('/athlete/zones-settings').then(r => r.data),
    staleTime: 1000 * 60 * 60,
  });
}

export function useUpdateZonesSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { source: HrZonesSource; manual_zones?: HrZoneBound[] }) =>
      api.put<{ source: HrZonesSource }>('/athlete/zones-settings', payload).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['athlete-zones'] });
      qc.invalidateQueries({ queryKey: ['zones-settings'] });
      // Downstream analytics that use HR zones
      qc.invalidateQueries({ queryKey: ['weekly-report'] });
      qc.invalidateQueries({ queryKey: ['relative-effort-weekly'] });
      qc.invalidateQueries({ queryKey: ['session-scores'] });
      qc.invalidateQueries({ queryKey: ['activity-score'] });
      qc.invalidateQueries({ queryKey: ['plan-accomplishment'] });
    },
  });
}

export interface RateLimitWindow {
  limit: number;
  usage: number;
}

export interface RateLimits {
  fifteen_min: RateLimitWindow;
  daily: RateLimitWindow;
  known: boolean;
}

export function useRateLimits(isSyncing?: boolean) {
  return useQuery<RateLimits>({
    queryKey: ['rate-limits'],
    queryFn: () => api.get('/athlete/rate-limits').then(r => r.data),
    staleTime: isSyncing ? 0 : 1000 * 60 * 2,
    refetchInterval: isSyncing ? 5000 : false,
  });
}
