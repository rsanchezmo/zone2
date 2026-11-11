import type { QueryClient } from '@tanstack/react-query';

/** Every query computed from the synced activities. */
const ACTIVITY_QUERY_KEYS = [
  'activities', 'activities-range', 'activities-on-dates', 'activity', 'similar-activities',
  'polylines', 'sport-types', 'years', 'recent-photos', 'activity-cost',
  'weekly-report', 'year-in-sport', 'cumulative-distance', 'streaks', 'personal-records',
  'sport-totals', 'weekly-totals', 'race-predictions', 'race-predictions-history',
  'relative-effort-weekly', 'fitness-form', 'briefing', 'gear', 'cache-completeness',
  'session-scores', 'activity-score', 'plan-accomplishment', 'goal-progress',
  'coach-plans', 'coach-plan',
] as const;

/** Refetch what a sync or a re-fetched activity can change, and nothing else: an unfiltered
 *  invalidation would also refetch static config and cause a visible refetch storm. Keys match
 *  by prefix, so string and numeric ids alike are caught. */
export function invalidateActivityQueries(qc: QueryClient) {
  for (const key of ACTIVITY_QUERY_KEYS) qc.invalidateQueries({ queryKey: [key] });
}

/** Everything the pages show, so they refetch after the coach changed or synced your data. */
export function refreshPages(qc: QueryClient) {
  qc.invalidateQueries({ predicate: q => !String(q.queryKey[0]).startsWith('agent-') });
}
