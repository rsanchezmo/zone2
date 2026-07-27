import { useEffect, useRef } from 'react';
import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import api from './client';
import type { Segment } from '../components/shared/segmentUtils';

// Activities

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

/** Detail endpoint adds streams and the raw Strava detail sub-payloads. */
export interface ActivityDetail extends Activity {
  streams?: ActivityStreamPoint[] | null;
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

// Stats

export interface WeeklyReport {
  week_start: string;
  week_end: string;
  total_activities: number;
  total_distance_km: number;
  total_elevation_m: number;
  total_time_hours: number;
  active_days: number;
  /** weekday (0=Mon .. 6=Sun) -> count */
  activities_per_day: Record<number, number>;
  distance_per_day_km: Record<number, number>;
  distance_per_sport_km: Record<string, number>;
  activities_per_sport: Record<string, number>;
  time_per_sport_hours: Record<string, number>;
  sports_per_day: Record<number, string[]>;
  time_per_sport_per_day_mins: Record<string, Record<number, number>>;
  activities_titles_per_day_per_sport: Record<string, Record<number, string[]>>;
  /** zone (1-5) -> % of HR samples */
  hr_zone_distribution: Record<number, number>;
  hr_histogram: { min_bpm: number; counts: number[] } | null;
  most_active_day: number | null;
  longest_activity_km: number;
  longest_activity_name: string | null;
  /** zone (1-5) -> [min_hr, max_hr] */
  hr_zone_ranges: Record<number, [number, number]>;
}

export interface WeeklyReportResponse {
  current: WeeklyReport;
  previous: WeeklyReport | null;
}

export function useWeeklyReport(weekStart?: string) {
  return useQuery<WeeklyReportResponse>({
    queryKey: ['weekly-report', weekStart],
    queryFn: () =>
      api.get('/stats/weekly-report', { params: { week_start: weekStart } }).then(r => r.data),
  });
}

export interface YearInSportMain {
  total_activities: number;
  total_distance_km: number;
  total_elevation_m: number;
  total_time_hours: number;
  average_distance_km: number;
  active_days: number;
  activities_per_month: Record<number, number>;
  distance_per_month_km: Record<number, number>;
  most_active_weekday: number | null;
  month_most_activities: number | null;
  month_most_km: number | null;
  month_least_km: number | null;
  longest_activity_km: number;
  longest_activity_mins: number;
  longest_activity_km_id: string | null;
  longest_activity_mins_id: string | null;
  /** m/s — format on display */
  fastest_activity_speed: number;
  fastest_activity_speed_id: string | null;
  /** m/s — format on display */
  average_speed: number;
  activities_per_week: number;
}

export interface YearInSportAll {
  total_activities: number;
  total_distance_km: number;
  total_time_hours: number;
  active_days: number;
  activities_per_week: number;
  activities_per_sport: Record<string, number>;
  most_active_weekday: number | null;
  most_active_month: number | null;
  sport_most_done: string | null;
}

export interface YearInSportResponse {
  main_sport: YearInSportMain;
  all_sports: YearInSportAll;
  year: number;
  sport: string;
  comparison?: {
    main_sport: YearInSportMain;
    all_sports: YearInSportAll;
    year: number;
  };
}

export function useYearInSport(year: number, mainSport: string, comparisonYear?: number) {
  return useQuery<YearInSportResponse>({
    queryKey: ['year-in-sport', year, mainSport, comparisonYear],
    queryFn: () =>
      api.get('/stats/year-in-sport', {
        params: { year, main_sport: mainSport, comparison_year: comparisonYear },
      }).then(r => r.data),
    placeholderData: keepPreviousData,
  });
}

export interface CumulativeDistancePoint {
  day: number;
  date: string;
  km: number;
  target?: number;
}

export interface CumulativeDistanceResponse {
  year: number;
  sport: string;
  data: CumulativeDistancePoint[];
  comparison?: { year: number; data: CumulativeDistancePoint[] };
}

export function useCumulativeDistance(
  year: number,
  mainSport: string,
  comparisonYear?: number,
  yearlyTargetKm?: number,
  opts?: { enabled?: boolean },
) {
  return useQuery<CumulativeDistanceResponse>({
    queryKey: ['cumulative-distance', year, mainSport, comparisonYear, yearlyTargetKm],
    queryFn: () =>
      api.get('/stats/cumulative-distance', {
        params: { year, main_sport: mainSport, comparison_year: comparisonYear, yearly_target_km: yearlyTargetKm },
      }).then(r => r.data),
    enabled: opts?.enabled ?? true,
    placeholderData: keepPreviousData,
  });
}

export interface WeeklyTotal {
  week_start: string;
  week_end: string;
  week_label: string;
  total_distance_km: number;
  total_activities: number;
}

export interface WeeklyTotalsResponse {
  data: WeeklyTotal[];
  weeks: number;
  sport_type: string | null;
}

export function useWeeklyTotals(weeks = 12, sportType?: string) {
  return useQuery<WeeklyTotalsResponse>({
    queryKey: ['weekly-totals', weeks, sportType],
    queryFn: () =>
      api.get('/stats/weekly-totals', {
        params: { weeks, sport_type: sportType },
      }).then(r => r.data),
    placeholderData: keepPreviousData,
  });
}

export interface Streaks {
  current_streak: number;
  longest_streak: number;
  longest_streak_start: string | null;
  longest_streak_end: string | null;
  // Week-streak fields are omitted when there are no activities at all.
  current_week_streak?: number;
  longest_week_streak?: number;
  longest_week_streak_start?: string | null;
  longest_week_streak_end?: string | null;
}

export function useStreaks() {
  return useQuery<Streaks>({
    queryKey: ['streaks'],
    queryFn: () => api.get('/stats/streaks').then(r => r.data),
  });
}

export interface PersonalRecord {
  distance_m: number;
  label: string;
  time_s: number;
  activity_id: number;
  activity_name: string;
  date: string;
}

/** Keyed by sport category (running / cycling / swimming); categories without
 * records are omitted. */
export type PersonalRecordsResponse = Record<string, PersonalRecord[]>;

export function usePersonalRecords() {
  return useQuery<PersonalRecordsResponse>({
    queryKey: ['personal-records'],
    queryFn: () => api.get('/stats/personal-records').then(r => r.data),
    staleTime: 1000 * 60 * 30,
  });
}

export interface SportTotals {
  distance_km: number;
  time_s: number;
  count: number;
}

/** Keyed by sport category; categories without activities are omitted. */
export type SportTotalsResponse = Record<string, SportTotals>;

export function useSportTotals() {
  return useQuery<SportTotalsResponse>({
    queryKey: ['sport-totals'],
    queryFn: () => api.get('/stats/sport-totals').then(r => r.data),
    staleTime: 1000 * 60 * 30,
  });
}

export interface RacePrediction {
  distance_m: number;
  label: string;
  pr_time_s: number | null;
  pr_date: string | null;
  source: 'predicted' | 'personal_record';
  predicted_time_s: number | null;
  predicted_time_low_s: number | null;
  predicted_time_high_s: number | null;
  models: Record<string, number | null>;
  garmin_time_s?: number;
}

export interface RacePredictionsResponse {
  predictions: RacePrediction[];
  athlete_vdot: number | null;
  fitted_exponent: number | null;
  confidence: 'high' | 'medium' | 'low';
  sport_category: string;
  garmin_predictions: Record<string, unknown> | null;
  race_day_calibration: {
    factor: number;
    n_races: number;
    band_low_mult: number | null;
    band_high_mult: number | null;
  };
  data_quality: {
    total_activities: number;
    prs_available: number;
    recent_prs: number;
    sufficient: boolean;
    warnings: string[];
    window_days: number;
  };
}

export function useRacePredictions(sportCategory: string) {
  return useQuery<RacePredictionsResponse>({
    queryKey: ['race-predictions', sportCategory],
    queryFn: () =>
      api.get('/stats/race-predictions', { params: { sport_category: sportCategory } }).then(r => r.data),
    staleTime: 1000 * 60 * 30,
    placeholderData: keepPreviousData,
  });
}

export interface RacePredictionHistoryEntry {
  distance_m: number;
  label: string;
  predicted_time_s: number | null;
  predicted_time_low_s: number | null;
  predicted_time_high_s: number | null;
}

export interface RacePredictionHistoryPoint {
  end_date: string;
  athlete_vdot: number | null;
  fitted_exponent: number | null;
  n_inputs: number;
  predictions: RacePredictionHistoryEntry[];
}

export interface RacePredictionsHistoryResponse {
  sport_category: string;
  weeks: number;
  points: RacePredictionHistoryPoint[];
}

export function useRacePredictionsHistory(sportCategory: string, weeks = 52) {
  return useQuery<RacePredictionsHistoryResponse>({
    queryKey: ['race-predictions-history', sportCategory, weeks],
    queryFn: () =>
      api.get('/stats/race-predictions/history', {
        params: { sport_category: sportCategory, weeks },
      }).then(r => r.data),
    staleTime: 1000 * 60 * 30,
    placeholderData: keepPreviousData,
  });
}

export interface RelativeEffortWeek {
  week_start: string;
  relative_effort: number;
  band_low: number;
  band_high: number;
  status: 'below' | 'in_range' | 'above';
}

export interface WeeklyRelativeEffortResponse {
  weeks: RelativeEffortWeek[];
  scale: number;
  sports: string[];
}

export function useWeeklyRelativeEffort(sportType?: string) {
  return useQuery<WeeklyRelativeEffortResponse>({
    queryKey: ['relative-effort-weekly', sportType],
    queryFn: () =>
      api.get('/stats/relative-effort/weekly', { params: { sport_type: sportType } }).then(r => r.data),
    staleTime: 1000 * 60 * 15,
    placeholderData: keepPreviousData,
  });
}

// Athlete

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

export function useAthleteProfile() {
  return useQuery<AthleteProfile>({
    queryKey: ['athlete-profile'],
    queryFn: () => api.get('/athlete/profile').then(r => r.data),
    staleTime: 1000 * 60 * 60, // 1 hour
  });
}

// Gear

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

export interface HrZoneBound {
  min: number;
  max: number;
}

export type HrZonesSource = 'strava' | 'estimated' | 'manual';

export interface AthleteZonesResponse {
  heart_rate: {
    zones: HrZoneBound[] | null;
    max_hr: number | null;
    source: HrZonesSource;
    requested_source: HrZonesSource;
    fallback_reason: string | null;
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

// Sync

export interface SyncStatus {
  syncing: boolean;
  last_error: string | null;
  last_sync_at: string | null;
  total_activities: number;
  needs_sync: boolean;
  last_activity_date: string | null;
  earliest_activity_date: string | null;
  athlete_name: string | null;
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
    onSuccess: () => {
      // Prefix match: routes pass string ids while useActivity keys on
      // numbers, so an exact ['activity', id] filter would miss the entry.
      qc.invalidateQueries({ queryKey: ['activity'] });
      qc.invalidateQueries({ queryKey: ['activities'] });
      qc.invalidateQueries({ queryKey: ['polylines'] });
      qc.invalidateQueries({ queryKey: ['similar-activities'] });
      qc.invalidateQueries({ queryKey: ['personal-records'] });
      qc.invalidateQueries({ queryKey: ['sport-totals'] });
      qc.invalidateQueries({ queryKey: ['weekly-report'] });
      qc.invalidateQueries({ queryKey: ['session-scores'] });
      qc.invalidateQueries({ queryKey: ['activity-score'] });
      qc.invalidateQueries({ queryKey: ['cache-completeness'] });
    },
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

// Calendar

export interface TrainingSession {
  id: number;
  date: string;
  title: string;
  sport_type: string;
  description: string | null;
  planned_distance_km: number | null;
  planned_duration_mins: number | null;
  planned_intensity: string | null;
  target_avg_pace: number | null;
  target_pace_min: number | null;
  target_pace_max: number | null;
  target_hr_zone: number | null;
  target_zone_pct: number | null;
  segments: Segment[] | null;
  workout_template_id: number | null;
  completed: boolean;
  created_at: string;
}

export function useCalendarSessions(month?: number, year?: number) {
  return useQuery<TrainingSession[]>({
    queryKey: ['calendar-sessions', month, year],
    queryFn: () =>
      api.get('/calendar/sessions', { params: { month, year } }).then(r => r.data),
    placeholderData: keepPreviousData,
  });
}

export function useCalendarSessionsByRange(dateFrom?: string, dateTo?: string) {
  return useQuery<TrainingSession[]>({
    queryKey: ['calendar-sessions-range', dateFrom, dateTo],
    queryFn: () =>
      api.get('/calendar/sessions', { params: { date_from: dateFrom, date_to: dateTo } }).then(r => r.data),
    enabled: !!dateFrom && !!dateTo,
  });
}

export function useCreateSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      api.post<TrainingSession>('/calendar/sessions', data).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['calendar-sessions'] });
      qc.invalidateQueries({ queryKey: ['calendar-sessions-range'] });
      qc.invalidateQueries({ queryKey: ['session-scores'] });
      qc.invalidateQueries({ queryKey: ['activity-score'] });
    },
  });
}

export function useUpdateSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: { id: number } & Record<string, unknown>) =>
      api.put<TrainingSession>(`/calendar/sessions/${id}`, data).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['calendar-sessions'] });
      qc.invalidateQueries({ queryKey: ['calendar-sessions-range'] });
      qc.invalidateQueries({ queryKey: ['session-scores'] });
      qc.invalidateQueries({ queryKey: ['activity-score'] });
    },
  });
}

export function useDeleteSession() {
  const qc = useQueryClient();
  return useMutation({
    // 204 No Content
    mutationFn: (id: number) => api.delete<void>(`/calendar/sessions/${id}`).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['calendar-sessions'] });
      qc.invalidateQueries({ queryKey: ['calendar-sessions-range'] });
      qc.invalidateQueries({ queryKey: ['session-scores'] });
      qc.invalidateQueries({ queryKey: ['activity-score'] });
    },
  });
}

export type CalendarFeedUrl = { token: string; url: string; env_managed: boolean; last_fetched_at: string | null };

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

// Goals

export interface Goal {
  id: number;
  year: number;
  /** Sport type or '__all__'. */
  sport_type: string;
  /** 'distance_km' | 'time_hours' | 'activities' | 'elevation_m' */
  metric: string;
  /** 'weekly' | 'monthly' | 'yearly' */
  period: string;
  target_value: number;
  created_at: string;
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
    mutationFn: (data: { year: number; sport_type: string; metric: string; period: string; target_value: number }) =>
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
    mutationFn: ({ id, ...data }: { id: number } & Record<string, unknown>) =>
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

// Race Events

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

export function useRaceEvents(year?: number) {
  return useQuery<RaceEvent[]>({
    queryKey: ['race-events', year],
    queryFn: () => api.get('/races/', { params: year ? { year } : {} }).then(r => r.data),
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
    mutationFn: (data: Record<string, unknown>) =>
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
    mutationFn: ({ id, ...data }: { id: number } & Record<string, unknown>) =>
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

// Workout Templates

export interface WorkoutTemplate {
  id: number;
  name: string;
  sport_type: string;
  description: string | null;
  created_at: string;
  segments: Segment[];
}

export function useWorkoutTemplates(sportType?: string) {
  return useQuery<WorkoutTemplate[]>({
    queryKey: ['workout-templates', sportType],
    queryFn: () =>
      api.get('/workouts', { params: sportType ? { sport_type: sportType } : {} }).then(r => r.data),
    placeholderData: keepPreviousData,
  });
}

export function useCreateWorkoutTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string; sport_type: string; description?: string; segments: Segment[] }) =>
      api.post<WorkoutTemplate>('/workouts', data).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['workout-templates'] });
    },
  });
}

export function useUpdateWorkoutTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: { id: number } & Record<string, unknown>) =>
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

// Garmin Connect (watch-level daily stats)

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

/** One day of a metric's slim chart summary (see strava/garmin_extractors.py);
 * the fields vary per metric, so everything beyond the date stays unknown. */
export type GarminTrendRow = Record<string, unknown> & { date: string };

export interface GarminTrends {
  start_date: string;
  end_date: string;
  days: number;
  metrics: Record<string, GarminTrendRow[]>;
}

export function useGarminTrends(days: number = 30) {
  return useQuery<GarminTrends>({
    queryKey: ['garmin-trends', days],
    queryFn: () => api.get('/garmin/trends', { params: { days } }).then(r => r.data),
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

// Coverage (street map matching)
export interface CoverageSummary {
  slug: string;
  city_name: string;
  num_matched_activities: number;
  bbox: [number, number, number, number]; // south, west, north, east
  total_network_km: number;
  traversed_km: number;
  coverage_pct: number;
  num_unique_streets: number;
}

export interface DistrictCoverage {
  name: string;
  total_km: number;
  covered_km: number;
  coverage_pct: number;
  num_streets: number;
  num_covered_streets: number;
  bbox: [number, number, number, number]; // south, west, north, east
  geometry?: GeoJSON.Polygon | GeoJSON.MultiPolygon;
}

export interface AreaCoverage {
  total_km: number;
  covered_km: number;
  coverage_pct: number;
  num_streets: number;
  num_covered_streets: number;
}

export type CoverageEdges = GeoJSON.FeatureCollection<
  GeoJSON.LineString,
  { name: string | null; times?: number }
>;

export function useCoverageCities() {
  return useQuery<CoverageSummary[]>({
    queryKey: ['coverage-cities'],
    queryFn: () => api.get('/coverage/cities').then(r => r.data),
    placeholderData: keepPreviousData,
  });
}

export function useCoverageEdges(slug?: string) {
  return useQuery<CoverageEdges>({
    queryKey: ['coverage-edges', slug],
    queryFn: () => api.get(`/coverage/${slug}/edges`, { params: { covered: true, counts: true } }).then(r => r.data),
    enabled: !!slug,
    staleTime: 5 * 60 * 1000,
    placeholderData: keepPreviousData,
  });
}

export function useCoverageDistricts(slug?: string, adminLevel = 9) {
  return useQuery<DistrictCoverage[]>({
    queryKey: ['coverage-districts', slug, adminLevel],
    queryFn: () =>
      api.get(`/coverage/${slug}/districts`, {
        params: { admin_level: adminLevel, geometry: true },
      }).then(r => r.data),
    enabled: !!slug,
    staleTime: 5 * 60 * 1000,
    placeholderData: keepPreviousData,
  });
}

export function useCoverageArea(slug?: string) {
  return useMutation<AreaCoverage, unknown, [number, number][]>({
    mutationFn: (points) =>
      api.post(`/coverage/${slug}/area`, { points }).then(r => r.data),
  });
}

export interface AddCityStatus {
  running: boolean;
  city_name: string | null;
  slug: string | null;
  error: string | null;
  progress: string | null;
  started_at: number | null;
}

export function useAddCity() {
  const qc = useQueryClient();
  return useMutation<{ status: string }, unknown, string>({
    mutationFn: (cityName) =>
      api.post('/coverage/add', null, { params: { city_name: cityName } }).then(r => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['coverage-add-status'] }),
  });
}

export interface GeocodeResult {
  query: string;
  display_name: string;
  lat: number;
  lon: number;
  bbox: { south: number; west: number; north: number; east: number };
}

/** Resolve a city query to its OSM location before downloading or flying to it. */
export function useGeocodeCity() {
  return useMutation<GeocodeResult, unknown, string>({
    mutationFn: (q) => api.get('/coverage/geocode', { params: { q } }).then(r => r.data),
  });
}

export function useDeleteCity() {
  const qc = useQueryClient();
  return useMutation<{ status: string }, unknown, string>({
    mutationFn: (slug) => api.delete(`/coverage/${slug}`).then(r => r.data),
    onSuccess: (_data, slug) => {
      qc.invalidateQueries({ queryKey: ['coverage-cities'] });
      // Drop the deleted city's cached map data outright — it would
      // otherwise survive for the full gcTime and resurface stale.
      qc.removeQueries({ queryKey: ['coverage-edges', slug] });
      qc.removeQueries({ queryKey: ['coverage-districts', slug] });
      qc.removeQueries({ queryKey: ['coverage-uncovered', slug] });
    },
  });
}

export function useAddCityStatus(polling = false) {
  return useQuery<AddCityStatus>({
    queryKey: ['coverage-add-status'],
    queryFn: () => api.get('/coverage/add/status').then(r => r.data),
    // Poll while the caller is interested or a download is in flight
    // (so a page reload mid-download keeps tracking it).
    refetchInterval: (query) => (polling || query.state.data?.running ? 3000 : false),
  });
}

export function useCoverageSyncStatus(slug?: string, polling = false) {
  return useQuery<{ running: boolean; last_error: string | null }>({
    queryKey: ['coverage-sync-status', slug],
    queryFn: () => api.get(`/coverage/${slug}/sync/status`).then(r => r.data),
    enabled: !!slug,
    // Poll while the caller is interested or a sync is in flight
    // (so a page reload mid-sync keeps tracking it).
    refetchInterval: (query) => (polling || query.state.data?.running ? 3000 : false),
  });
}

export function useTriggerCoverageSync(slug?: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ status: string }>(`/coverage/${slug}/sync`).then(r => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['coverage-sync-status', slug] }),
  });
}

export function useUncoveredEdges(slug?: string, bbox?: string) {
  return useQuery<CoverageEdges>({
    queryKey: ['coverage-uncovered', slug, bbox],
    queryFn: () =>
      api.get(`/coverage/${slug}/edges`, { params: { covered: false, bbox } }).then(r => r.data),
    enabled: !!slug && !!bbox,
    staleTime: 5 * 60 * 1000,
    placeholderData: keepPreviousData,
  });
}
