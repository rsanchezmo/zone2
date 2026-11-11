import { useQuery } from '@tanstack/react-query';
import api from './client';

export type GearKind = 'shoes' | 'bikes';

/** Gear identity plus the rollup of its synced activities. `strava_distance_km`
 * is Strava's lifetime odometer, `distance_km` only what the local cache holds. */
export interface GearSummary {
  id: string;
  name: string;
  nickname: string | null;
  label: string;
  kind: GearKind;
  primary: boolean;
  retired: boolean;
  brand_name?: string | null;
  model_name?: string | null;
  strava_distance_km: number;
  activities: number;
  distance_km: number;
  moving_time_s: number;
  elevation_m: number;
  first_activity: string | null;
  last_activity: string | null;
  active_days: number;
}

export interface GearTotals {
  prs: number;
  achievements: number;
  calories: number;
  avg_speed_ms: number | null;
  avg_distance_km: number;
  avg_heartrate: number | null;
  days_per_activity: number | null;
}

export interface GearActivityPoint {
  id: number;
  name: string;
  date: string;
  sport_type: string;
  distance_km: number;
  cumulative_km: number;
  speed_ms: number | null;
  heartrate: number | null;
}

export interface GearMonth {
  month: string;
  distance_km: number;
  activities: number;
  moving_time_s: number;
}

export interface GearBestEffort {
  distance_m: number;
  name: string;
  elapsed_time: number;
  activity_id: number;
  activity_name: string;
  date: string;
  all_time_best: boolean;
}

export interface GearExtreme {
  id: number;
  name: string;
  date: string;
  distance_km: number;
  moving_time_s: number;
  speed_ms: number | null;
  elevation_m: number;
}

export interface GearPeer {
  id: string;
  label: string;
  distance_km: number;
  retired: boolean;
}

export interface GearDetail {
  gear: GearSummary;
  totals: GearTotals | null;
  activities: GearActivityPoint[];
  monthly: GearMonth[];
  sport_mix: { sport_type: string; activities: number; distance_km: number }[];
  best_efforts: GearBestEffort[];
  extremes: { longest?: GearExtreme | null; fastest?: GearExtreme | null; biggest_climb?: GearExtreme | null };
  peers: GearPeer[];
}

export function useGearList() {
  return useQuery<{ gear: GearSummary[] }>({
    queryKey: ['gear'],
    queryFn: () => api.get('/gear').then(r => r.data),
    staleTime: 1000 * 60 * 30,
  });
}

export function useGearDetail(gearId: string | undefined) {
  return useQuery<GearDetail>({
    queryKey: ['gear', gearId],
    queryFn: () => api.get(`/gear/${gearId}`).then(r => r.data),
    enabled: !!gearId,
    staleTime: 1000 * 60 * 30,
  });
}
