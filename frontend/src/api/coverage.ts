import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import api from './client';

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

// 9 = administrative districts, 10 = neighbourhoods, 'hex' = the H3 grid
export type DistrictLevel = 9 | 10 | 'hex';

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

/** An activity's route matched to a coverage city's streets; lines run in
 * travel order. `new_km`: the streets it walked for the first time there. */
export type ActivityRoute = GeoJSON.FeatureCollection<
  GeoJSON.MultiLineString,
  { slug: string; city_name: string; new_km: number }
>;

/** One month of a city's coverage growth: km of streets walked for the first
 * time, the runs matched that month, and the running total. */
export interface CoverageTimelineMonth {
  month: string; // YYYY-MM
  new_km: number;
  runs: number;
  cumulative_km: number;
}

export function useCoverageTimeline(slug?: string) {
  return useQuery<{ months: CoverageTimelineMonth[] }>({
    queryKey: ['coverage-timeline', slug],
    queryFn: () => api.get(`/coverage/${slug}/timeline`).then(r => r.data),
    enabled: !!slug,
    staleTime: 5 * 60 * 1000,
    placeholderData: keepPreviousData,
  });
}

/** The activity's matched route, or null when no coverage city has matched it. */
export function useActivityRoute(id: number) {
  return useQuery<ActivityRoute | null>({
    queryKey: ['activity-route', id],
    queryFn: () => api.get<ActivityRoute>(`/coverage/routes/${id}`)
      .then(r => (r.data.features.length > 0 ? r.data : null)),
    enabled: !!id,
    staleTime: 5 * 60 * 1000,
  });
}

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

export function useCoverageDistricts(slug?: string, level: DistrictLevel = 9) {
  return useQuery<DistrictCoverage[]>({
    queryKey: ['coverage-districts', slug, level],
    queryFn: () =>
      (level === 'hex'
        ? api.get(`/coverage/${slug}/hexes`, { params: { geometry: true } })
        : api.get(`/coverage/${slug}/districts`, { params: { admin_level: level, geometry: true } })
      ).then(r => r.data),
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

/** An exploration loop: coordinates [lon, lat] in running order, from and back to `start` ([lat, lon]). */
export type PlannedLoop = GeoJSON.Feature<GeoJSON.LineString, {
  length_km: number; new_km: number; start: [number, number]; plan_id: string;
}>;

/** Kinds of way a planned loop can avoid (streets are always allowed). */
export type AvoidableWay = 'main_road' | 'cycleway' | 'path' | 'track' | 'steps';

export interface LoopPlanRequest {
  distance_km: number;
  /** [lat, lon]; the city's usual run start when null */
  start: [number, number] | null;
  via: [number, number][];
  /** Share of the loop wanted on streets not run yet */
  new_share: number;
  avoid: AvoidableWay[];
  seed: number;
}

export function usePlannedLoop(slug: string | undefined, request: LoopPlanRequest | null) {
  return useQuery<PlannedLoop>({
    queryKey: ['coverage-plan', slug, request],
    queryFn: () => api.post(`/coverage/${slug}/plan`, request).then(r => r.data),
    enabled: !!slug && !!request,
    staleTime: Infinity,
    // No loop through the chosen points is an answer, shown by the planner
    retry: false,
    meta: { inlineError: true },
    placeholderData: keepPreviousData,
  });
}

/** A loop saved from the planner. */
export interface SavedRoute {
  id: number;
  name: string;
  distance_km: number;
  /** New km when planned, and still not run since (null once the city's street map changed) */
  new_km: number;
  new_km_now: number | null;
  garmin_course_id: number | null;
  created_at: string;
  /** [lon, lat] in running order */
  coordinates: number[][];
}

export function useSavedRoutes(slug?: string) {
  return useQuery<SavedRoute[]>({
    queryKey: ['saved-routes', slug],
    queryFn: () => api.get(`/coverage/${slug}/plans`).then(r => r.data),
    enabled: !!slug,
    placeholderData: keepPreviousData,
  });
}

export function useSaveRoute(slug?: string) {
  const qc = useQueryClient();
  return useMutation<SavedRoute, unknown, { name: string; plan_id: string; request: LoopPlanRequest }>({
    mutationFn: body => api.post(`/coverage/${slug}/plans`, body).then(r => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['saved-routes', slug] }),
  });
}

export function useDeleteRoute(slug?: string) {
  const qc = useQueryClient();
  return useMutation<unknown, unknown, number>({
    mutationFn: id => api.delete(`/coverage/${slug}/plans/${id}`).then(r => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['saved-routes', slug] }),
  });
}

/** Creates the route's Garmin course (once) and, with a device, queues it for that watch. */
export function useSendRouteToGarmin(slug?: string) {
  const qc = useQueryClient();
  return useMutation<SavedRoute, unknown, { id: number; device_id: number | null }>({
    mutationFn: ({ id, device_id }) => api.post(`/coverage/${slug}/plans/${id}/garmin`, { device_id }).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['saved-routes', slug] });
      qc.invalidateQueries({ queryKey: ['garmin-courses'] });
    },
  });
}

/** A Garmin course starting in a coverage city. */
export interface GarminCourse {
  course_id: number;
  name: string;
  distance_km: number;
  /** [lat, lon] */
  start: [number | null, number | null];
  sport: string | null;
  created_at: string | null;
  /** Km of streets of its part in the city, and of those not run yet; null when it doesn't match the city's streets */
  city_km: number | null;
  new_km: number | null;
}

export interface GarminDevice {
  device_id: number;
  name: string;
  primary: boolean;
}

/** The user's Garmin courses starting in the city; none when Garmin isn't connected. */
export function useCityGarminCourses(slug?: string) {
  return useQuery<GarminCourse[]>({
    queryKey: ['garmin-courses', slug],
    queryFn: () => api.get(`/coverage/${slug}/garmin-courses`).then(r => r.data),
    enabled: !!slug,
    retry: false,
    meta: { inlineError: true },
  });
}

export function useGarminDevices(enabled: boolean) {
  return useQuery<GarminDevice[]>({
    queryKey: ['garmin-devices'],
    queryFn: () => api.get('/garmin/devices').then(r => r.data),
    enabled,
    staleTime: 60 * 60 * 1000,
    retry: false,
    meta: { inlineError: true },
  });
}

/** A Garmin course's line, [lon, lat]. */
export function useGarminCourseLine(courseId: number | null) {
  return useQuery<{ coordinates: number[][] }>({
    queryKey: ['garmin-course-line', courseId],
    queryFn: () => api.get(`/garmin/courses/${courseId}/points`).then(r => r.data),
    enabled: courseId !== null,
    staleTime: Infinity,
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

export interface GeocodeSuggestion {
  query: string;
  display_name: string;
  area_km2: number;
}

export interface GeocodeResult {
  query: string;
  display_name: string;
  lat: number;
  lon: number;
  bbox: { south: number; west: number; north: number; east: number };
  /** The place is only a point in OSM, so it has no area to cover */
  point_only?: boolean;
  /** For a point-only place, the area around it that can be added instead */
  suggestion?: GeocodeSuggestion | null;
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
