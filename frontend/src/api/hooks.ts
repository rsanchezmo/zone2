import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import api from './client';

// Activities
export function usePolylines(sportType?: string, year?: number) {
  return useQuery({
    queryKey: ['polylines', sportType, year],
    queryFn: () =>
      api.get('/activities/polylines', { params: { sport_type: sportType, year: year } })
        .then(r => r.data),
    placeholderData: keepPreviousData,
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
  return useQuery({
    queryKey: ['activities', page, perPage, sportType, year, search, dateFrom, dateTo, sortBy, sortDir, gearId],
    queryFn: () =>
      api.get('/activities', {
        params: {
          page,
          per_page: perPage,
          sport_type: sportType,
          year,
          search: search || undefined,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
          sort_by: sortBy || undefined,
          sort_dir: sortDir || undefined,
          gear_id: gearId || undefined,
        },
      }).then(r => r.data),
    placeholderData: keepPreviousData,
  });
}

export function useActivitiesByDateRange(dateFrom?: string, dateTo?: string) {
  return useQuery({
    queryKey: ['activities-range', dateFrom, dateTo],
    queryFn: () =>
      api.get('/activities', { params: { page: 1, per_page: 100, date_from: dateFrom, date_to: dateTo } })
        .then(r => r.data),
    enabled: !!dateFrom && !!dateTo,
  });
}

export function useActivity(id: number | string) {
  return useQuery({
    queryKey: ['activity', id],
    queryFn: () => api.get(`/activities/${id}`).then(r => r.data),
    enabled: !!id,
  });
}

export function useSimilarActivities(id: number | string) {
  return useQuery({
    queryKey: ['similar-activities', id],
    queryFn: () => api.get(`/activities/${id}/similar`).then(r => r.data),
    enabled: !!id,
  });
}

export function useSportTypes() {
  return useQuery({
    queryKey: ['sport-types'],
    queryFn: () => api.get('/activities/sport-types').then(r => r.data),
    staleTime: 1000 * 60 * 60,
  });
}

export function useYears() {
  return useQuery({
    queryKey: ['years'],
    queryFn: () => api.get('/activities/years').then(r => r.data),
    staleTime: 1000 * 60 * 60,
  });
}

// Stats
export function useWeeklyReport(weekStart?: string) {
  return useQuery({
    queryKey: ['weekly-report', weekStart],
    queryFn: () =>
      api.get('/stats/weekly-report', { params: { week_start: weekStart } }).then(r => r.data),
  });
}

export function useYearInSport(year: number, mainSport: string, comparisonYear?: number) {
  return useQuery({
    queryKey: ['year-in-sport', year, mainSport, comparisonYear],
    queryFn: () =>
      api.get('/stats/year-in-sport', {
        params: { year, main_sport: mainSport, comparison_year: comparisonYear },
      }).then(r => r.data),
    placeholderData: keepPreviousData,
  });
}

export function useEfficiencyFactor(sportType: string, window = 14) {
  return useQuery({
    queryKey: ['efficiency-factor', sportType, window],
    queryFn: () =>
      api.get('/stats/efficiency-factor', { params: { sport_type: sportType, window } })
        .then(r => r.data),
    placeholderData: keepPreviousData,
  });
}

export function usePerformanceFrontier(sportTypes: string) {
  return useQuery({
    queryKey: ['performance-frontier', sportTypes],
    queryFn: () =>
      api.get('/stats/performance-frontier', { params: { sport_types: sportTypes } })
        .then(r => r.data),
  });
}

export function useActivityClock(sportTypes: string) {
  return useQuery({
    queryKey: ['activity-clock', sportTypes],
    queryFn: () =>
      api.get('/stats/activity-clock', { params: { sport_types: sportTypes } })
        .then(r => r.data),
  });
}

export function useCumulativeDistance(year: number, mainSport: string, comparisonYear?: number, yearlyTargetKm?: number) {
  return useQuery({
    queryKey: ['cumulative-distance', year, mainSport, comparisonYear, yearlyTargetKm],
    queryFn: () =>
      api.get('/stats/cumulative-distance', {
        params: { year, main_sport: mainSport, comparison_year: comparisonYear, yearly_target_km: yearlyTargetKm },
      }).then(r => r.data),
    placeholderData: keepPreviousData,
  });
}

export function useWeeklyTotals(weeks = 12, sportType?: string) {
  return useQuery({
    queryKey: ['weekly-totals', weeks, sportType],
    queryFn: () =>
      api.get('/stats/weekly-totals', {
        params: { weeks, sport_type: sportType },
      }).then(r => r.data),
    placeholderData: keepPreviousData,
  });
}

export function useStreaks() {
  return useQuery({
    queryKey: ['streaks'],
    queryFn: () => api.get('/stats/streaks').then(r => r.data),
  });
}

export function usePersonalRecords() {
  return useQuery({
    queryKey: ['personal-records'],
    queryFn: () => api.get('/stats/personal-records').then(r => r.data),
    staleTime: 1000 * 60 * 30,
  });
}

export function useSportTotals() {
  return useQuery({
    queryKey: ['sport-totals'],
    queryFn: () => api.get('/stats/sport-totals').then(r => r.data),
    staleTime: 1000 * 60 * 30,
  });
}

export function useRacePredictions(sportCategory: string) {
  return useQuery({
    queryKey: ['race-predictions', sportCategory],
    queryFn: () =>
      api.get('/stats/race-predictions', { params: { sport_category: sportCategory } }).then(r => r.data),
    staleTime: 1000 * 60 * 30,
    placeholderData: keepPreviousData,
  });
}

export function useRacePredictionsHistory(sportCategory: string, weeks = 52) {
  return useQuery({
    queryKey: ['race-predictions-history', sportCategory, weeks],
    queryFn: () =>
      api.get('/stats/race-predictions/history', {
        params: { sport_category: sportCategory, weeks },
      }).then(r => r.data),
    staleTime: 1000 * 60 * 30,
    placeholderData: keepPreviousData,
  });
}

export function useTrainingLoad(startDate?: string, endDate?: string) {
  return useQuery({
    queryKey: ['training-load', startDate, endDate],
    queryFn: () =>
      api.get('/stats/training-load', { params: { start_date: startDate, end_date: endDate } }).then(r => r.data),
    staleTime: 1000 * 60 * 15,
    placeholderData: keepPreviousData,
  });
}

export function useFitnessChart(startDate?: string, endDate?: string) {
  return useQuery({
    queryKey: ['fitness-chart', startDate, endDate],
    queryFn: () =>
      api.get('/stats/fitness-chart', { params: { start_date: startDate, end_date: endDate } }).then(r => r.data),
    staleTime: 1000 * 60 * 15,
    placeholderData: keepPreviousData,
  });
}

export function useFitnessTrend(sportType: string, startDate?: string, endDate?: string) {
  return useQuery({
    queryKey: ['fitness-trend', sportType, startDate, endDate],
    queryFn: () =>
      api.get('/stats/fitness-trend', { params: { sport_type: sportType, start_date: startDate, end_date: endDate } }).then(r => r.data),
    staleTime: 1000 * 60 * 15,
    placeholderData: keepPreviousData,
  });
}

// Athlete
export function useAthleteProfile() {
  return useQuery({
    queryKey: ['athlete-profile'],
    queryFn: () => api.get('/athlete/profile').then(r => r.data),
    staleTime: 1000 * 60 * 60, // 1 hour
  });
}


export function useAthleteZones() {
  return useQuery({
    queryKey: ['athlete-zones'],
    queryFn: () => api.get('/athlete/zones').then(r => r.data),
    staleTime: 1000 * 60 * 60,
  });
}

export function useZonesSettings() {
  return useQuery({
    queryKey: ['zones-settings'],
    queryFn: () => api.get('/athlete/zones-settings').then(r => r.data),
    staleTime: 1000 * 60 * 60,
  });
}

export function useUpdateZonesSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { source: 'strava' | 'estimated' | 'manual'; manual_zones?: Array<{ min: number; max: number }> }) =>
      api.put('/athlete/zones-settings', payload).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['athlete-zones'] });
      qc.invalidateQueries({ queryKey: ['zones-settings'] });
      // Downstream analytics that use HR zones
      qc.invalidateQueries({ queryKey: ['weekly-report'] });
      qc.invalidateQueries({ queryKey: ['training-load'] });
      qc.invalidateQueries({ queryKey: ['session-scores'] });
      qc.invalidateQueries({ queryKey: ['activity-score'] });
    },
  });
}

export function useRateLimits(isSyncing?: boolean) {
  return useQuery({
    queryKey: ['rate-limits'],
    queryFn: () => api.get('/athlete/rate-limits').then(r => r.data),
    staleTime: isSyncing ? 0 : 1000 * 60 * 2,
    refetchInterval: isSyncing ? 5000 : false,
  });
}

// Sync
export function useSyncStatus() {
  return useQuery({
    queryKey: ['sync-status'],
    queryFn: () => api.get('/sync/status').then(r => r.data),
    refetchInterval: (query) => query.state.data?.syncing ? 2000 : false,
  });
}

export function useTriggerSync() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: { full_sync?: boolean; include_streams?: boolean } = {}) =>
      api.post('/sync', null, { params }).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['sync-status'] });
    },
  });
}

export function useBackfillStreams() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post('/sync/backfill-streams').then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['sync-status'] });
      qc.invalidateQueries({ queryKey: ['cache-completeness'] });
    },
  });
}

export function useCacheCompleteness(isSyncing?: boolean) {
  return useQuery({
    queryKey: ['cache-completeness'],
    queryFn: () => api.get('/sync/cache-completeness').then(r => r.data),
    staleTime: isSyncing ? 0 : 1000 * 60 * 5,
    refetchInterval: isSyncing ? 3000 : false,
  });
}

// Calendar
export function useCalendarSessions(month?: number, year?: number) {
  return useQuery({
    queryKey: ['calendar-sessions', month, year],
    queryFn: () =>
      api.get('/calendar/sessions', { params: { month, year } }).then(r => r.data),
    placeholderData: keepPreviousData,
  });
}

export function useCalendarSessionsByRange(dateFrom?: string, dateTo?: string) {
  return useQuery({
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
      api.post('/calendar/sessions', data).then(r => r.data),
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
      api.put(`/calendar/sessions/${id}`, data).then(r => r.data),
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
    mutationFn: (id: number) => api.delete(`/calendar/sessions/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['calendar-sessions'] });
      qc.invalidateQueries({ queryKey: ['calendar-sessions-range'] });
      qc.invalidateQueries({ queryKey: ['session-scores'] });
      qc.invalidateQueries({ queryKey: ['activity-score'] });
    },
  });
}

export function useSessionScores(dateFrom?: string, dateTo?: string) {
  return useQuery({
    queryKey: ['session-scores', dateFrom, dateTo],
    queryFn: () =>
      api.get('/calendar/sessions/scores', { params: { date_from: dateFrom, date_to: dateTo } }).then(r => r.data),
    enabled: !!dateFrom && !!dateTo,
    staleTime: 1000 * 60 * 5,
  });
}

export function useActivityScore(activityId?: number) {
  return useQuery({
    queryKey: ['activity-score', activityId],
    queryFn: () =>
      api.get(`/calendar/sessions/score-by-activity/${activityId}`).then(r => r.data),
    enabled: !!activityId,
    staleTime: 1000 * 60 * 5,
  });
}

// Goals
export function useGoals(year?: number) {
  return useQuery({
    queryKey: ['goals', year],
    queryFn: () => api.get('/goals/', { params: year ? { year } : {} }).then(r => r.data),
    placeholderData: keepPreviousData,
  });
}

export function useCreateGoal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { year: number; sport_type: string; metric: string; period: string; target_value: number }) =>
      api.post('/goals/', data).then(r => r.data),
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
      api.put(`/goals/${id}`, data).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['goals'] });
      qc.invalidateQueries({ queryKey: ['goal-progress'] });
    },
  });
}

export function useDeleteGoal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.delete(`/goals/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['goals'] });
      qc.invalidateQueries({ queryKey: ['goal-progress'] });
    },
  });
}

export function useGoalProgress(weekStart?: string) {
  return useQuery({
    queryKey: ['goal-progress', weekStart],
    queryFn: () =>
      api.get('/goals/progress', { params: { week_start: weekStart } }).then(r => r.data),
    enabled: !!weekStart,
  });
}

// Race Events
export function useRaceEvents(year?: number) {
  return useQuery({
    queryKey: ['race-events', year],
    queryFn: () => api.get('/races/', { params: year ? { year } : {} }).then(r => r.data),
    placeholderData: keepPreviousData,
  });
}

export function useRaceEventsByRange(dateFrom?: string, dateTo?: string) {
  return useQuery({
    queryKey: ['race-events-range', dateFrom, dateTo],
    queryFn: () =>
      api.get('/races/', { params: { date_from: dateFrom, date_to: dateTo } }).then(r => r.data),
    enabled: !!dateFrom && !!dateTo,
  });
}

export function useUpcomingRaces() {
  return useQuery({
    queryKey: ['upcoming-races'],
    queryFn: () => api.get('/races/upcoming').then(r => r.data),
  });
}

export function useCreateRaceEvent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      api.post('/races/', data).then(r => r.data),
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
      api.put(`/races/${id}`, data).then(r => r.data),
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
    mutationFn: (id: number) => api.delete(`/races/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['race-events'] });
      qc.invalidateQueries({ queryKey: ['race-events-range'] });
      qc.invalidateQueries({ queryKey: ['upcoming-races'] });
    },
  });
}

// Workout Templates
export function useWorkoutTemplates(sportType?: string) {
  return useQuery({
    queryKey: ['workout-templates', sportType],
    queryFn: () =>
      api.get('/workouts', { params: sportType ? { sport_type: sportType } : {} }).then(r => r.data),
    placeholderData: keepPreviousData,
  });
}

export function useCreateWorkoutTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string; sport_type: string; description?: string; segments: Record<string, unknown>[] }) =>
      api.post('/workouts', data).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['workout-templates'] });
    },
  });
}

export function useUpdateWorkoutTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: { id: number } & Record<string, unknown>) =>
      api.put(`/workouts/${id}`, data).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['workout-templates'] });
    },
  });
}

export function useDeleteWorkoutTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.delete(`/workouts/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['workout-templates'] });
    },
  });
}
