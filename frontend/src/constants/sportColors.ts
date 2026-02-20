/**
 * Consistent sport colors used across the app (calendar, dashboard, charts).
 * Based on neon palette, one distinct color per Strava sport type.
 */
export const SPORT_COLORS_HEX: Record<string, string> = {
  Run: '#fc0101',
  Ride: '#00aaff',
  Swim: '#3b82f6',
  Walk: '#39ff14',
  Hike: '#faff00',
  Squash: '#ff00ff',
  Tennis: '#ff0088',
  Pickleball: '#ff8800',
  Racquetball: '#e879f9',
  WeightTraining: '#8800ff',
  Workout: '#a855f7',
  Yoga: '#00ff88',
  AlpineSki: '#00ffff',
  InlineSkate: '#06b6d4',
  Kayaking: '#0ea5e9',
  RockClimbing: '#f97316',
  StandUpPaddling: '#14b8a6',
  VirtualRun: '#f87171',
  Rest: '#4b5563',
}

/** Fallback color for unknown sport types */
export const DEFAULT_SPORT_COLOR = '#9ca3af'

/** Get color for a sport type, with fallback */
export function getSportColor(sportType: string): string {
  return SPORT_COLORS_HEX[sportType] ?? DEFAULT_SPORT_COLOR
}
