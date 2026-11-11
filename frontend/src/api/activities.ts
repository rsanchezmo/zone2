import { useQuery, keepPreviousData } from '@tanstack/react-query';
import api from './client';

/** One sample of the legacy list-of-dicts stream wire format. Keys are only
 * present when the sample has a value for that channel. */
export interface ActivityStreamPoint {
  time?: number;
  distance?: number;
  altitude?: number;
  velocity_smooth?: number;
  heartrate?: number;
  cadence?: number;
  watts?: number;
  temp?: number;
  moving?: boolean;
  grade_smooth?: number;
  /** Runs only: speed on the flat at the same energy cost (Minetti), from the backend. */
  grade_adjusted_speed?: number;
  lat?: number;
  lng?: number;
  /** Pre-columnar wire format; current backend always splits into lat/lng. */
  latlng?: [number, number];
}

export interface ActivityPhoto {
  unique_id: string;
  urls: Record<string, string>;
  caption?: string;
  location?: [number, number];
  [key: string]: unknown;
}

/** Raw Strava km split (splits_metric entries), passed through unmodified. */
export interface ActivitySplitMetric {
  distance?: number | null;
  elapsed_time?: number | null;
  moving_time?: number | null;
  average_speed?: number | null;
  average_grade_adjusted_speed?: number | null;
  average_heartrate?: number | null;
  elevation_difference?: number | null;
  [key: string]: unknown;
}

export interface ActivityBestEffort {
  name?: string;
  elapsed_time?: number | null;
  moving_time?: number | null;
  distance?: number | null;
  pr_rank?: number | null;
  [key: string]: unknown;
}

export interface ActivityLap {
  distance?: number | null;
  elapsed_time?: number | null;
  moving_time?: number | null;
  average_speed?: number | null;
  average_heartrate?: number | null;
  max_heartrate?: number | null;
  average_cadence?: number | null;
  [key: string]: unknown;
}

export interface ActivityGear {
  id?: string;
  name: string;
  nickname?: string | null;
  converted_distance?: number | null;
  distance?: number | null;
  retired?: boolean;
  primary?: boolean;
  [key: string]: unknown;
}

/** Strava's own route-performance comparison across efforts on this route. */
export interface SimilarActivitiesSummary {
  effort_count: number;
  average_speed: number;
  min_average_speed: number;
  mid_average_speed: number;
  max_average_speed: number;
  pr_rank: number | null;
  trend: {
    speeds: number[];
    current_activity_index: number;
    min_speed: number;
    mid_speed: number;
    max_speed: number;
    direction: number;
  } | null;
  [key: string]: unknown;
}

export interface ActivitySegmentEffort {
  name?: string;
  elapsed_time?: number | null;
  distance?: number | null;
  pr_rank?: number | null;
  average_heartrate?: number | null;
  max_heartrate?: number | null;
  average_cadence?: number | null;
  average_watts?: number | null;
  segment?: {
    name?: string;
    average_grade?: number | null;
    city?: string | null;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

/** Strava activity as serialized by the backend list endpoints. Raw Strava
 * fields are normalized to null when absent; derived display fields are only
 * set when computable. Extra raw Strava columns stay reachable through the
 * index signature. */
export interface Activity {
  id: number;
  name: string | null;
  description: string | null;
  sport_type: string;
  distance: number | null;
  moving_time: number | null;
  elapsed_time: number | null;
  total_elevation_gain: number | null;
  start_date: string | null;
  start_date_local: string | null;
  timezone: string | null;
  average_speed: number | null;
  max_speed: number | null;
  average_heartrate: number | null;
  max_heartrate: number | null;
  average_cadence: number | null;
  elev_high: number | null;
  elev_low: number | null;
  start_latlng: number[] | null;
  end_latlng: number[] | null;
  kudos_count: number | null;
  achievement_count: number | null;
  suffer_score: number | null;
  calories: number | null;
  perceived_exertion: number | null;
  total_photo_count: number | null;
  device_name: string | null;
  gear_id: string | null;
  average_watts: number | null;
  max_watts: number | null;
  weighted_average_watts: number | null;
  average_temp: number | null;
  pr_count: number | null;
  workout_type: number | null;
  formatted_pace?: string;
  distance_km?: number;
  moving_time_formatted?: string;
  elapsed_time_formatted?: string;
  formatted_max_speed?: string;
  summary_polyline?: string | null;
  [key: string]: unknown;
}

/** A stop inside the activity (traffic light, auto-pause), excluded from moving time. */
export interface ActivityStop {
  start_km: number;
  /** Elapsed seconds from the activity start. */
  start_s: number;
  duration_s: number;
}

export type DriftVerdict = 'steady' | 'drifting' | 'high';

/** How far HR climbed at a steady grade-adjusted pace, past the first 10 min; runs only. */
export type ActivityDrift =
  | { status: 'no_heart_rate' }
  | { status: 'too_short'; minutes: number; min_minutes: number; skipped_min: number }
  | { status: 'unsteady'; minutes: number; pace_cv_pct: number; max_pace_cv_pct: number }
  | {
      status: 'measured';
      verdict: DriftVerdict;
      decoupling_pct: number;
      drift_bpm_per_10min: number;
      rise_bpm: number;
      minutes: number;
      /** First half, second half. */
      metres_per_beat: [number, number];
      pace_cv_pct: number;
      start_km: number;
      half_km: number;
      end_km: number;
      skipped_min: number;
      steady_below_pct: number;
      /** [km, bpm]: the HR the pace alone explains at the start's cost. */
      no_drift_hr: [number, number][];
    };

export interface RepRecovery {
  start_km: number;
  end_km: number;
  duration_s: number;
  speed_ms: number;
  peak_km: number;
  peak_hr: number | null;
  /** bpm below the peak 30 and 60 s after the rep ended; null when the next rep started first. */
  drop_30: number | null;
  drop_60: number | null;
  /** Seconds to the next rep; null after the last one. */
  recovery_s: number | null;
  /** False when the minute after was walked or stood, which drops HR faster. */
  jogged: boolean;
}

/** How fast HR came down after each rep of an interval session; runs only. */
export type ActivityHrRecovery =
  | { status: 'no_heart_rate' }
  | { status: 'no_reps'; reps: number; min_reps: number }
  | {
      status: 'measured';
      reps: RepRecovery[];
      drop_30_mean: number | null;
      drop_60_mean: number | null;
      jog_speed_ms: number;
    };

/** Detail endpoint adds streams, detected stops and the raw Strava detail sub-payloads. */
export interface ActivityDetail extends Activity {
  streams?: ActivityStreamPoint[] | null;
  stops?: ActivityStop[];
  drift?: ActivityDrift | null;
  hr_recovery?: ActivityHrRecovery | null;
  photos?: ActivityPhoto[] | null;
  splits_metric?: ActivitySplitMetric[] | null;
  best_efforts?: ActivityBestEffort[] | null;
  laps?: ActivityLap[] | null;
  gear?: ActivityGear | null;
  segment_efforts?: ActivitySegmentEffort[] | null;
  similar_activities?: SimilarActivitiesSummary | null;
}

export interface ActivityListResponse {
  items: Activity[];
  total: number;
  page: number;
  per_page: number;
}

export interface ActivityPolyline {
  id: number;
  sport_type: string;
  year: number;
  polyline: string;
  name: string;
}

export function usePolylines(sportType?: string, year?: number, enabled = true, gearId?: string) {
  return useQuery<ActivityPolyline[]>({
    queryKey: ['polylines', sportType, year, gearId],
    queryFn: () =>
      api.get('/activities/polylines', { params: { sport_type: sportType, year: year, gear_id: gearId } })
        .then(r => r.data),
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useActivities(
  page: number,
  perPage = 20,
  sportType?: string,
  year?: number,
  search?: string,
  dateFrom?: string,
  dateTo?: string,
  sortBy?: string,
  sortDir?: string,
  gearId?: string,
) {
  // Normalize before building the query key so '' and undefined filters
  // share a single cache entry.
  const params = {
    page,
    per_page: perPage,
    sport_type: sportType || undefined,
    year,
    search: search || undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    sort_by: sortBy || undefined,
    sort_dir: sortDir || undefined,
    gear_id: gearId || undefined,
  };
  return useQuery<ActivityListResponse>({
    queryKey: ['activities', params],
    queryFn: () => api.get('/activities', { params }).then(r => r.data),
    placeholderData: keepPreviousData,
  });
}

export function useActivitiesByDateRange(dateFrom?: string, dateTo?: string) {
  return useQuery<ActivityListResponse>({
    queryKey: ['activities-range', dateFrom, dateTo],
    // The backend caps per_page at 100, so busy ranges need multiple pages.
    queryFn: async () => {
      const perPage = 100;
      const fetchPage = (page: number) =>
        api.get<ActivityListResponse>('/activities', { params: { page, per_page: perPage, date_from: dateFrom, date_to: dateTo } })
          .then(r => r.data);
      const first = await fetchPage(1);
      const items: Activity[] = [...first.items];
      for (let page = 2; items.length < first.total; page++) {
        const next = await fetchPage(page);
        if (next.items.length === 0) break;
        items.push(...next.items);
      }
      return { ...first, items };
    },
    enabled: !!dateFrom && !!dateTo,
    placeholderData: keepPreviousData,
  });
}

export function useActivitiesOnDates(dates: string[]) {
  return useQuery<{ items: Activity[] }>({
    queryKey: ['activities-on-dates', dates],
    queryFn: () =>
      api.get('/activities/on-dates', { params: { dates: dates.join(',') } }).then(r => r.data),
    enabled: dates.length > 0,
  });
}

export function useActivity(id: number | string) {
  return useQuery<ActivityDetail>({
    queryKey: ['activity', id],
    queryFn: () => api.get(`/activities/${id}`).then(r => r.data),
    enabled: !!id,
  });
}

export function useSimilarActivities(id: number | string) {
  return useQuery<Activity[]>({
    queryKey: ['similar-activities', id],
    queryFn: () => api.get(`/activities/${id}/similar`).then(r => r.data),
    enabled: !!id,
  });
}

export function useSportTypes() {
  return useQuery<string[]>({
    queryKey: ['sport-types'],
    queryFn: () => api.get('/activities/sport-types').then(r => r.data),
    staleTime: 1000 * 60 * 60,
  });
}

export interface RecentPhoto {
  unique_id: string;
  urls: Record<string, string>;
  caption?: string | null;
  activity_id: number;
  activity_name?: string | null;
  sport_type?: string | null;
  start_date_local?: string | null;
}

export function useRecentPhotos(limit = 6) {
  return useQuery<RecentPhoto[]>({
    queryKey: ['recent-photos', limit],
    queryFn: () => api.get('/activities/photos/recent', { params: { limit } }).then(r => r.data),
    staleTime: 5 * 60 * 1000,
  });
}

export function useYears() {
  return useQuery<number[]>({
    queryKey: ['years'],
    queryFn: () => api.get('/activities/years').then(r => r.data),
    staleTime: 1000 * 60 * 60,
  });
}
