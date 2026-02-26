/**
 * Consistent sport colors used across the app (calendar, dashboard, charts).
 * Covers all Strava-supported sport types, grouped by category with distinct colors.
 */
export const SPORT_COLORS_HEX: Record<string, string> = {
  // Foot Sports
  Run: '#ef4444',
  Hike: '#eab308',
  TrailRun: '#f97316',
  Wheelchair: '#b8860b',
  Walk: '#22c55e',

  // Cycle Sports
  Ride: '#00aaff',
  EBikeRide: '#00ccee',
  MountainBikeRide: '#0077cc',
  EMountainBikeRide: '#0099dd',
  GravelRide: '#5588cc',
  Velomobile: '#44aadd',
  Handcycle: '#66bbee',

  // Water Sports
  Canoeing: '#1e90ff',
  StandUpPaddling: '#14b8a6',
  Kayaking: '#0ea5e9',
  Surfing: '#00bcd4',
  Kitesurf: '#26c6da',
  Swim: '#3b82f6',
  Rowing: '#4fc3f7',
  Windsurf: '#00acc1',
  Sail: '#80deea',

  // Winter Sports
  IceSkate: '#b0e0e6',
  NordicSki: '#a0d2db',
  AlpineSki: '#67e8f9',
  Snowboard: '#7fdbff',
  BackcountrySki: '#90caf9',
  Snowshoe: '#b3e5fc',

  // Racquet Sports
  Squash: '#d946ef',
  Tennis: '#ff0088',
  Pickleball: '#ff8800',
  Racquetball: '#e879f9',
  Badminton: '#f472b6',
  TableTennis: '#fb7185',
  Padel: '#ff6ec7',

  // Fitness & Training
  WeightTraining: '#8800ff',
  Workout: '#a855f7',
  Yoga: '#34d399',
  Pilates: '#34d399',
  Crossfit: '#c084fc',
  HighIntensityIntervalTraining: '#d946ef',
  Elliptical: '#a78bfa',
  StairStepper: '#818cf8',
  Dance: '#f0abfc',

  // Team & Field Sports
  Soccer: '#22c55e',
  Basketball: '#f59e0b',
  Volleyball: '#fbbf24',
  Cricket: '#84cc16',
  Football: '#16a34a',

  // Other
  RockClimbing: '#f97316',
  InlineSkate: '#06b6d4',
  Skateboard: '#67e8f9',
  RollerSki: '#38bdf8',
  Golf: '#4ade80',
  VirtualRun: '#f87171',
  VirtualRide: '#60a5fa',

  // Planning
  Rest: '#4b5563',
}

/** Fallback color for unknown sport types */
export const DEFAULT_SPORT_COLOR = '#9ca3af'

/** Get color for a sport type, with fallback */
export function getSportColor(sportType: string): string {
  return SPORT_COLORS_HEX[sportType] ?? DEFAULT_SPORT_COLOR
}
