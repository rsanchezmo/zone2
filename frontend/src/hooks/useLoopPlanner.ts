import { useState } from 'react'
import { isAxiosError } from 'axios'
import {
  useGarminCourseLine, usePlannedLoop,
  type AvoidableWay, type GarminCourse, type LoopPlanRequest, type PlannedLoop, type SavedRoute,
} from '../api/hooks'

export const PLAN_MAX_VIA = 3

const INITIAL: LoopPlanRequest = { distance_km: 10, start: null, via: [], new_share: 1, avoid: [], seed: 0 }

/** A route shown on the map instead of the plan: a saved loop or a Garmin course. */
export type RouteSelection =
  | { kind: 'saved'; route: SavedRoute }
  | { kind: 'garmin'; course: GarminCourse }

/** Share of a route already run, in %, from its km not run yet. */
export function coveredPct(lengthKm: number, newKm: number): number {
  return Math.max(0, Math.min(100, Math.round(100 * (1 - newKm / Math.max(lengthKm, 0.01)))))
}

export function selectionKey(selection: RouteSelection): string {
  return selection.kind === 'saved' ? `saved-${selection.route.id}` : `garmin-${selection.course.course_id}`
}

export interface RouteView {
  selection: RouteSelection
  name: string
  /** [lon, lat]; empty while a Garmin course's line loads */
  coordinates: number[][]
  length_km: number
  /** Km of it not run yet; null when unknown (outside the city's map) */
  new_km: number | null
  /** Km of it the covered share is of: all of a saved loop, the streets of a Garmin course's part in the city */
  city_km: number | null
  garminCourseId: number | null
}

export interface LoopPlanner {
  request: LoopPlanRequest
  loop: PlannedLoop | undefined
  /** The chosen start, else where the city's runs usually start */
  start: [number, number] | null
  planning: boolean
  error: string | null
  /** The saved route of the loop on screen, once saved */
  saved: SavedRoute | null
  view: RouteView | null
  setDistance: (km: number) => void
  setNewShare: (share: number) => void
  toggleAvoid: (way: AvoidableWay) => void
  setStart: (at: [number, number]) => void
  addVia: (at: [number, number]) => void
  removeVia: (index: number) => void
  clearVia: () => void
  another: () => void
  markSaved: (route: SavedRoute) => void
  show: (selection: RouteSelection | null) => void
  reset: () => void
}

function errorDetail(error: unknown, fallback: string): string {
  const detail = isAxiosError(error) ? error.response?.data?.detail : undefined
  return typeof detail === 'string' ? detail : fallback
}

/** State of the coverage page's run planner; plans only while active and not showing a route. */
export function useLoopPlanner(slug: string | undefined, active: boolean): LoopPlanner {
  const [request, setRequest] = useState<LoopPlanRequest>(INITIAL)
  const [selection, setSelection] = useState<RouteSelection | null>(null)
  const [saved, setSaved] = useState<{ planId: string; route: SavedRoute } | null>(null)
  const query = usePlannedLoop(slug, active && !selection ? request : null)
  const courseLine = useGarminCourseLine(selection?.kind === 'garmin' ? selection.course.course_id : null)

  const loop = query.error ? undefined : query.data
  const start = request.start ?? query.data?.properties.start ?? null
  // The usual start is pinned on the first change, so a failed plan keeps it on the map
  const update = (patch: (r: LoopPlanRequest) => Partial<LoopPlanRequest>) =>
    setRequest(r => ({ ...r, start: r.start ?? start, ...patch(r) }))

  let view: RouteView | null = null
  if (selection?.kind === 'saved') {
    const { route } = selection
    view = {
      selection, name: route.name, coordinates: route.coordinates, length_km: route.distance_km,
      new_km: route.new_km_now, city_km: route.distance_km, garminCourseId: route.garmin_course_id,
    }
  } else if (selection?.kind === 'garmin') {
    const { course } = selection
    view = {
      selection, name: course.name, coordinates: courseLine.data?.coordinates ?? [], length_km: course.distance_km,
      new_km: course.new_km, city_km: course.city_km, garminCourseId: course.course_id,
    }
  }

  return {
    request,
    loop,
    start,
    planning: selection ? courseLine.isFetching : query.isFetching,
    error: selection
      ? (courseLine.error ? errorDetail(courseLine.error, 'Could not load the course') : null)
      : (query.error ? errorDetail(query.error, 'Planning failed') : null),
    saved: saved && loop && saved.planId === loop.properties.plan_id ? saved.route : null,
    view,
    setDistance: km => update(() => ({ distance_km: km })),
    setNewShare: share => update(() => ({ new_share: share })),
    toggleAvoid: way => update(r => ({ avoid: r.avoid.includes(way) ? r.avoid.filter(w => w !== way) : [...r.avoid, way] })),
    setStart: at => update(() => ({ start: at })),
    addVia: at => update(r => ({ via: r.via.length >= PLAN_MAX_VIA ? r.via : [...r.via, at] })),
    removeVia: index => update(r => ({ via: r.via.filter((_, i) => i !== index) })),
    clearVia: () => update(() => ({ via: [] })),
    another: () => update(r => ({ seed: r.seed + 1 })),
    markSaved: route => { if (loop) setSaved({ planId: loop.properties.plan_id, route }) },
    show: setSelection,
    reset: () => { setRequest(INITIAL); setSelection(null); setSaved(null) },
  }
}
