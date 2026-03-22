/**
 * Centralized pace/speed formatting utilities.
 * Mirrors the backend logic in strava/strava_utils.py exactly.
 */

const CYCLING_SPORTS = new Set([
  'ride', 'virtualride', 'ebikeride', 'handcycle', 'velomobile',
  'gravelride', 'mountainbikeride', 'emountainbikeride', 'rollerski',
])
const SWIMMING_SPORTS = new Set(['swim'])
const WATER_SPORTS = new Set([
  'canoeing', 'standuppaddling', 'kayaking', 'surfing', 'kitesurf',
  'rowing', 'windsurf', 'sail',
])
const SPEED_SPORTS = new Set([
  'squash', 'tennis', 'pickleball', 'racquetball', 'badminton', 'tabletennis', 'padel',
  'weighttraining', 'workout', 'yoga', 'pilates', 'crossfit', 'highintensityintervaltraining',
  'elliptical', 'stairstepper', 'dance', 'rockclimbing', 'alpineski', 'backcountryski',
  'nordicski', 'snowboard', 'iceskate', 'inlineskate', 'skateboard',
  'soccer', 'basketball', 'volleyball', 'cricket', 'golf',
])

export type SportCategory = 'cycling' | 'swimming' | 'water' | 'speed' | 'running'

export function getSportCategory(sportType: string | undefined | null): SportCategory {
  const key = (sportType ?? '').toLowerCase().replace(/\s/g, '')
  if (CYCLING_SPORTS.has(key)) return 'cycling'
  if (SWIMMING_SPORTS.has(key)) return 'swimming'
  if (WATER_SPORTS.has(key)) return 'water'
  if (SPEED_SPORTS.has(key)) return 'speed'
  return 'running'
}

export function isSpeedSport(sportType: string | undefined | null): boolean {
  const cat = getSportCategory(sportType)
  return cat === 'cycling' || cat === 'water' || cat === 'speed'
}

/** Convert m/s to sport-appropriate numeric value and unit. */
export function convertSpeed(speedMs: number, sportType: string | undefined | null): { value: number; unit: string } {
  if (speedMs <= 0) return { value: 0, unit: 'N/A' }
  const cat = getSportCategory(sportType)
  if (cat === 'swimming') {
    return { value: (100 / speedMs) / 60, unit: 'min/100m' }
  } else if (cat === 'cycling' || cat === 'water' || cat === 'speed') {
    return { value: speedMs * 3.6, unit: 'km/h' }
  }
  return { value: (1000 / speedMs) / 60, unit: 'min/km' }
}

/** Format a pace value (min/km or min/100m) as M:SS. */
export function formatPace(value: number, useSpeed: boolean): string {
  if (useSpeed) return value.toFixed(1)
  const m = Math.floor(value)
  let s = Math.round((value - m) * 60)
  if (s === 60) return `${m + 1}:00`
  return `${m}:${s.toString().padStart(2, '0')}`
}

/** Format speed in m/s to a full display string based on sport type (e.g. "5:30 /km", "25.3 km/h"). */
export function formatSpeed(speedMs: number, sportType: string | undefined | null): string {
  if (speedMs <= 0) return 'N/A'
  const { value, unit } = convertSpeed(speedMs, sportType)
  const cat = getSportCategory(sportType)
  if (cat === 'cycling' || cat === 'water' || cat === 'speed') {
    return `${value.toFixed(1)} ${unit}`
  }
  // Pace-based: format as M:SS /unit
  const m = Math.floor(value)
  let s = Math.round((value - m) * 60)
  if (s === 60) return `${m + 1}:00 /${unit.replace('min/', '')}`
  return `${m}:${s.toString().padStart(2, '0')} /${unit.replace('min/', '')}`
}

/** Get the pace/speed unit label for a sport type. */
export function getPaceUnit(sportType: string | undefined | null): string {
  const cat = getSportCategory(sportType)
  if (cat === 'swimming') return 'min/100m'
  if (cat === 'cycling' || cat === 'water' || cat === 'speed') return 'km/h'
  return 'min/km'
}

/** Format a distance in km to a display string, using meters for swimming. */
export function formatDist(km: number, sportType: string | undefined | null, decimals: number = 1): string {
  if (getSportCategory(sportType) === 'swimming') {
    const m = Math.round(km * 1000)
    return `${m.toLocaleString()} m`
  }
  return `${km.toFixed(decimals)} km`
}

/** Compact distance format for chart axis ticks (e.g., "5k" for 5000m swimming, "10" for 10km). */
export function formatDistAxis(km: number, sportType: string | undefined | null): string {
  if (getSportCategory(sportType) === 'swimming') {
    const m = Math.round(km * 1000)
    if (m >= 1000) return `${(m / 1000).toFixed(m % 1000 === 0 ? 0 : 1)}k`
    return `${m}`
  }
  return `${km}`
}

/** Get the distance unit label for a sport type. */
export function getDistUnit(sportType: string | undefined | null): string {
  return getSportCategory(sportType) === 'swimming' ? 'm' : 'km'
}

/** Convert km value to the appropriate display value (meters for swimming, km otherwise). */
export function distValue(km: number, sportType: string | undefined | null, decimals: number = 1): string {
  if (getSportCategory(sportType) === 'swimming') {
    return String(Math.round(km * 1000))
  }
  return km.toFixed(decimals)
}

/** Format a PR pace from time and distance (used by PersonalRecordsPage). */
export function formatPrPace(seconds: number, distanceM: number, category: string): string {
  if (category === 'cycling') {
    const kmh = (distanceM / seconds) * 3.6
    return `${kmh.toFixed(1)} km/h`
  }
  if (category === 'swimming') {
    const per100 = (seconds / distanceM) * 100
    const m = Math.floor(per100 / 60)
    const s = Math.round(per100 % 60)
    return `${m}:${s.toString().padStart(2, '0')} /100m`
  }
  const perKm = (seconds / distanceM) * 1000
  const m = Math.floor(perKm / 60)
  const s = Math.round(perKm % 60)
  return `${m}:${s.toString().padStart(2, '0')} /km`
}
