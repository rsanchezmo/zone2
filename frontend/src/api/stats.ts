import { useQuery, keepPreviousData } from '@tanstack/react-query';
import api from './client';

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
    enabled: !!weekStart,
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

export type TrainingPaceZone = 'E' | 'M' | 'T' | 'I' | 'R';

export interface TrainingPace {
  zone: TrainingPaceZone;
  speed_min_mps: number;
  speed_max_mps: number;
}

export type FadeVerdict = 'holds_pace' | 'typical' | 'fades';

export interface FadeAnchor {
  distance_m: number;
  time_s: number;
  date: string;
  activity_id: number;
  activity_name: string;
  is_race: boolean;
  weight_share: number;
}

/** How much slower the athlete gets as distance grows: the weighted Riegel
 *  exponent the predictions use, with the efforts behind it. */
export interface Fade {
  exponent: number;
  stderr: number | null;
  typical: number;
  /** Null when too few independent efforts to bound the exponent. */
  verdict: FadeVerdict | null;
  /** Strongest first. */
  anchors: FadeAnchor[];
}

export interface RacePredictionsResponse {
  predictions: RacePrediction[];
  athlete_vdot: number | null;
  fitted_exponent: number | null;
  /** Running only. */
  fade: Fade | null;
  /** Daniels' paces at the VDOT the calibrated predictions imply; running only. */
  training_paces: { vdot: number; paces: TrainingPace[] } | null;
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

export interface FitnessDay {
  date: string;
  load: number;
  fitness: number;
  fatigue: number;
  form: number;
  /** Form as a share of fitness: comparable across load scales. */
  form_pct: number | null;
  /** From planned sessions rather than logged activities. */
  projected: boolean;
}

export interface FitnessFormResponse {
  series: FitnessDay[];
  fitness_days?: number;
  fatigue_days?: number;
  races: { date: string; name: string }[];
  /** Garmin's own acute and chronic training load, on its own scale. */
  garmin: { date: string; acute: number | null; chronic: number | null }[];
}

export function useFitnessForm(days: number) {
  return useQuery<FitnessFormResponse>({
    queryKey: ['fitness-form', days],
    queryFn: () => api.get('/stats/fitness', { params: { days } }).then(r => r.data),
    staleTime: 1000 * 60 * 5,
    placeholderData: keepPreviousData,
  });
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
