/**
 * Date helpers for API date strings.
 *
 * The backend serializes `start_date_local` as local wall time with a fake
 * UTC offset (e.g. "2026-07-12T23:00:00+00:00"), so it must never be parsed
 * with `new Date(...)` directly — that re-shifts it by the browser timezone
 * and can move an activity to the wrong calendar day.
 */

/** Local calendar date ("yyyy-MM-dd") of an API datetime or date string, without timezone shifting. */
export function localDateStr(value: string): string {
  return value.slice(0, 10)
}

/** Parse a date-only string or API local datetime as local wall time (date-only → local midnight). */
export function parseLocalDate(value: string): Date {
  const stripped = value.replace(/(Z|[+-]\d{2}:?\d{2})$/, '')
  return new Date(stripped.includes('T') ? stripped : `${stripped}T00:00:00`)
}

/** Today's local calendar date as "yyyy-MM-dd". */
export function todayLocalStr(): string {
  const d = new Date()
  const m = (d.getMonth() + 1).toString().padStart(2, '0')
  const day = d.getDate().toString().padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}
