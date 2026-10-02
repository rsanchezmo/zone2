import { useMemo, useState } from 'react'
import clsx from 'clsx'
import { useTheme } from '../../hooks/useTheme'
import { useGarminEvents, useActivitiesByDateRange, type GarminAutoEvent } from '../../api/hooks'
import { getSportColor, DEFAULT_SPORT_COLOR } from '../../constants/sportColors'
import ChartPanel from '../shared/ChartPanel'
import { formatDurationHM } from '../../utils/formatSpeed'
import { ACCENT, fmtDayDate } from './garmin'

/* ── Move IQ auto-detected events ──────────────────────────────────── */

/** Garmin Move IQ activityType → Strava sport key, so events reuse the
 *  shared sport color map. */
const MOVEIQ_SPORT: Record<string, string> = {
  running: 'Run',
  walking: 'Walk',
  hiking: 'Hike',
  cycling: 'Ride',
  biking: 'Ride',
  swimming: 'Swim',
  rowing: 'Rowing',
  elliptical: 'Elliptical',
}

/** One color per sport across recorded and detected segments in this panel.
 *  Ride is re-pinned because its blue is nearly Swim's on a thin lane. */
const LANE_COLOR_OVERRIDES: Record<string, string> = {
  Ride: '#facc15',
}

function laneColor(sportKey: string): string {
  return LANE_COLOR_OVERRIDES[sportKey] ?? getSportColor(sportKey)
}

/** Detected type → Strava sport key, so a Move IQ swim and a recorded Swim
 *  share one legend entry and color. Unmapped types just get capitalized. */
function moveIqSportKey(type: string | null): string {
  if (!type) return 'Movement'
  const t = type.toLowerCase()
  return MOVEIQ_SPORT[t] ?? t.charAt(0).toUpperCase() + t.slice(1)
}

function moveIqColor(type: string | null): string {
  if (!type) return DEFAULT_SPORT_COLOR
  return laneColor(moveIqSportKey(type))
}

function moveIqLabel(e: GarminAutoEvent): string {
  const t = e.activity_sub_type ?? e.activity_type
  if (!t) return 'Movement'
  return t.charAt(0).toUpperCase() + t.slice(1)
}

/** Local timestamps arrive as `YYYY-MM-DDTHH:MM:SS.0`; slice the clock out
 *  rather than Date-parsing into a shifted zone. */
function eventClock(ts: string | null): string {
  return ts ? ts.slice(11, 16) : '–'
}

/** A recorded activity's span on a day lane, minutes since local midnight. */
interface RecordedInterval {
  start: number
  end: number
  sport: string
}

function clockFromMinutes(min: number): string {
  const m = Math.max(0, Math.round(min))
  return `${String(Math.floor(m / 60) % 24).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`
}

/** Minutes since local midnight, for positioning on a day lane. */
function eventDayOffset(ts: string | null): number | null {
  if (!ts || ts.length < 16) return null
  const h = Number(ts.slice(11, 13))
  const m = Number(ts.slice(14, 16))
  if (Number.isNaN(h) || Number.isNaN(m)) return null
  return h * 60 + m
}

const EVENTS_RANGE_OPTIONS = [7, 14, 30]
const LANE_HOUR_TICKS = [6, 12, 18]

/** Recorded activities and the movement the watch detected that no recording covers, one lane per day. */
export default function MoveIqPanel() {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const [eventRange, setEventRange] = useState<number>(14)
  const { data: eventsData } = useGarminEvents(eventRange)

  // Recorded activities over the same window, to tell truly-uncaptured movement
  // apart from Move IQ noise fired during a recorded workout (padel reads as
  // "swimming", a recorded swim also emits a swim event, …).
  const eventRangeDates = useMemo(() => {
    const iso = (d: Date) =>
      `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    const end = new Date()
    const start = new Date()
    start.setDate(end.getDate() - (eventRange - 1))
    return { from: iso(start), to: iso(end) }
  }, [eventRange])
  const { data: rangeActivities } = useActivitiesByDateRange(eventRangeDates.from, eventRangeDates.to)

  // Recorded intervals per local day, in minutes since midnight. start_date_local
  // is sliced as a string — Date-parsing it would shift the fake-UTC local zone.
  const recordedByDay = useMemo(() => {
    const map = new Map<string, RecordedInterval[]>()
    for (const a of rangeActivities?.items ?? []) {
      const ts = a.start_date_local
      const startMin = eventDayOffset(ts)
      if (ts == null || startMin == null) continue
      const date = ts.slice(0, 10)
      const interval = { start: startMin, end: startMin + (a.moving_time ?? 0) / 60, sport: a.sport_type }
      const list = map.get(date)
      if (list) list.push(interval)
      else map.set(date, [interval])
    }
    return map
  }, [rangeActivities])

  // One lane per day (newest first): recorded activities as primary segments,
  // plus the Move IQ events no recording covers. A detected event with half
  // its span inside a recording is redundant noise (padel reads as "swimming")
  // and is dropped; brushing a workout's edge by a minute doesn't count.
  const { eventDays, legendSports, recordedTotalMins, detectedTotalMins } = useMemo(() => {
    const isCovered = (e: GarminAutoEvent): boolean => {
      const startMin = eventDayOffset(e.start_local)
      if (startMin == null) return false
      const dur = e.duration_mins ?? 0
      const endMin = startMin + dur
      for (const r of recordedByDay.get(e.date) ?? []) {
        const intersection = Math.min(endMin, r.end) - Math.max(startMin, r.start)
        if (intersection > 0 && (dur === 0 || intersection >= dur / 2)) return true
      }
      return false
    }

    const dayMap = new Map<string, { recorded: RecordedInterval[]; events: GarminAutoEvent[] }>()
    let recordedTotalMins = 0
    for (const [date, recorded] of recordedByDay) {
      dayMap.set(date, { recorded, events: [] })
      recordedTotalMins += recorded.reduce((s, r) => s + (r.end - r.start), 0)
    }
    let detectedTotalMins = 0
    for (const e of eventsData?.events ?? []) {
      if (isCovered(e)) continue
      detectedTotalMins += e.duration_mins ?? 0
      const entry = dayMap.get(e.date)
      if (entry) entry.events.push(e)
      else dayMap.set(e.date, { recorded: [], events: [e] })
    }

    const sports = new Map<string, string>()
    for (const { recorded, events } of dayMap.values()) {
      for (const r of recorded) sports.set(r.sport, laneColor(r.sport))
      for (const e of events) {
        const key = moveIqSportKey(e.activity_type)
        sports.set(key, laneColor(key))
      }
    }

    return {
      eventDays: [...dayMap.entries()]
        .sort((a, b) => (a[0] < b[0] ? 1 : -1))
        .map(([date, { recorded, events }]) => ({
          date,
          recorded,
          events,
          totalMins: recorded.reduce((s, r) => s + (r.end - r.start), 0)
            + events.reduce((s, e) => s + (e.duration_mins ?? 0), 0),
        })),
      legendSports: [...sports.entries()].sort((a, b) => a[0].localeCompare(b[0])),
      recordedTotalMins,
      detectedTotalMins,
    }
  }, [eventsData, recordedByDay])

  return (
    <section className="space-y-4">
      <div className="section-head pt-2">
        <span className="eyebrow">Auto-detected</span>
      </div>
      <ChartPanel
        title="Move IQ"
        sublabel={`last ${eventsData?.days ?? eventRange}d · recorded activities + watch-detected movement (hidden when a recording covers it)`}
        accent={ACCENT}
        toolbar={
          <div className="flex items-center gap-0.5" role="tablist">
            {EVENTS_RANGE_OPTIONS.map(d => (
              <button key={d} className="chip"
                data-active={d === eventRange}
                onClick={() => setEventRange(d)}>
                {d}d
              </button>
            ))}
          </div>
        }
        legend={eventDays.length > 0 ? (
          <>
            <span className="inline-flex items-center gap-1.5 text-[11px] text-gray-500">
              <span className="w-2 h-3.5 rounded-[2px] bg-gray-400" />
              <span>Recorded</span>
              <span className="font-mono tabular-nums">{formatDurationHM(recordedTotalMins * 60)}</span>
            </span>
            <span className="inline-flex items-center gap-1.5 text-[11px] text-gray-500">
              <span className="w-2 h-2 rounded-[2px] bg-gray-400" />
              <span>Detected</span>
              <span className="font-mono tabular-nums">{formatDurationHM(detectedTotalMins * 60)}</span>
            </span>
            {legendSports.map(([name, color]) => (
              <span key={name} className="inline-flex items-center gap-1.5 text-[11px] text-gray-500">
                <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: color }} />
                <span>{name}</span>
              </span>
            ))}
          </>
        ) : undefined}
      >
        {eventDays.length === 0 ? (
          <div className={clsx('text-xs py-6 text-center', isLight ? 'text-gray-400' : 'text-gray-600')}>
            No auto-detected events cached yet — run a sync to pull them.
          </div>
        ) : (
          <div className="space-y-2.5">
            {/* Hour axis, aligned with the lanes below */}
            <div className="flex items-center gap-3">
              <span className="w-24 shrink-0" />
              <div className="relative flex-1 h-4">
                {LANE_HOUR_TICKS.map(h => (
                  <span
                    key={h}
                    className="absolute -translate-x-1/2 text-[10px] font-mono text-gray-500"
                    style={{ left: `${(h / 24) * 100}%` }}
                  >
                    {String(h).padStart(2, '0')}
                  </span>
                ))}
              </div>
              <span className="w-14 shrink-0" />
            </div>
            {eventDays.map(day => (
              <div key={day.date} className="flex items-center gap-3">
                <span className={clsx('text-xs font-mono tabular-nums w-24 shrink-0', isLight ? 'text-gray-500' : 'text-gray-400')}>
                  {fmtDayDate(day.date)}
                </span>
                <div className={clsx('relative flex-1 h-7 rounded', isLight ? 'bg-gray-100' : 'bg-surface-700/40')}>
                  {LANE_HOUR_TICKS.map(h => (
                    <span
                      key={h}
                      className="absolute top-0 bottom-0 w-px"
                      style={{ left: `${(h / 24) * 100}%`, backgroundColor: isLight ? '#e5e7eb' : '#ffffff14' }}
                    />
                  ))}
                  {day.recorded.map((r, i) => {
                    const durMin = Math.min(r.end, 1440) - r.start
                    return (
                      <span
                        key={`rec-${i}`}
                        className="absolute top-0 bottom-0 rounded-[3px]"
                        style={{
                          left: `${(r.start / 1440) * 100}%`,
                          width: `${Math.max((durMin / 1440) * 100, 0.4)}%`,
                          minWidth: 4,
                          backgroundColor: laneColor(r.sport),
                        }}
                        title={`Recorded ${r.sport} ${clockFromMinutes(r.start)}–${clockFromMinutes(r.end)} · ${Math.round(r.end - r.start)} min`}
                      />
                    )
                  })}
                  {day.events.map((e, i) => {
                    const startMin = eventDayOffset(e.start_local)
                    if (startMin == null) return null
                    const color = moveIqColor(e.activity_type)
                    const durMin = Math.min(e.duration_mins ?? 0, 1440 - startMin)
                    const intensity = (e.moderate_mins ?? 0) + (e.vigorous_mins ?? 0)
                    return (
                      <span
                        key={i}
                        className="absolute top-1.5 bottom-1.5 rounded-[2px]"
                        style={{
                          left: `${(startMin / 1440) * 100}%`,
                          width: `${Math.max((durMin / 1440) * 100, 0.4)}%`,
                          minWidth: 4,
                          backgroundColor: color,
                        }}
                        title={`Detected ${moveIqLabel(e)} ${eventClock(e.start_local)}–${eventClock(e.end_local)} · ${e.duration_mins ?? 0} min${intensity > 0 ? ` · ${intensity} intensity min` : ''}`}
                      />
                    )
                  })}
                </div>
                <span className="text-[11px] text-gray-500 font-mono tabular-nums w-14 text-right shrink-0">
                  {formatDurationHM(day.totalMins * 60)}
                </span>
              </div>
            ))}
          </div>
        )}
      </ChartPanel>
    </section>
  )
}
