import { useEffect, useMemo, useRef, useState } from 'react'
import { Marker, Pane, Polyline, Tooltip, useMap, useMapEvents } from 'react-leaflet'
import L from 'leaflet'
import clsx from 'clsx'
import {
  useDeleteRoute, useGarminDevices, useSaveRoute, useSendRouteToGarmin,
  type AvoidableWay, type SavedRoute,
} from '../../api/hooks'
import { PLAN_MAX_VIA, coveredPct, type LoopPlanner } from '../../hooks/useLoopPlanner'
import { gpxTrack } from '../../utils/gpx'
import { RouteArrows } from './leafletHelpers'
import { createStartIcon, createViaIcon } from './mapIcons'
import { saveBlob } from './download'

export const PLAN_ACCENT = '#22d3ee'

const AVOIDABLE: [AvoidableWay, string][] = [
  ['main_road', 'Main roads'], ['cycleway', 'Cycle lanes'], ['path', 'Paths'], ['track', 'Dirt tracks'], ['steps', 'Steps'],
]

function downloadGpx(name: string, coordinates: number[][]) {
  const file = name.replace(/[^\w.-]+/g, '-').replace(/^-+|-+$/g, '') || 'z2-route'
  saveBlob(new Blob([gpxTrack(name, coordinates)], { type: 'application/gpx+xml' }), `${file}.gpx`)
}

/** A watch face: marks routes that are on Garmin Connect. */
export function GarminIcon({ className }: { className?: string }) {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"
         strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
      <circle cx="8" cy="8" r="4" />
      <path d="M6 4.3 6.5 1.5h3l.5 2.8M6 11.7l.5 2.8h3l.5-2.8M8 6.5V8l1 .8" />
    </svg>
  )
}

/** The planned loop, or the route being viewed, with the plan's start and
 *  the points it must pass. While planning, tapping the map sets the start
 *  when there is none yet, otherwise adds a point. */
export function LoopPlanLayer({ planner }: { planner: LoopPlanner }) {
  const map = useMap()
  const { loop, start, request, view } = planner
  useMapEvents({
    click(e) {
      if (view) return
      const at: [number, number] = [e.latlng.lat, e.latlng.lng]
      if (start) planner.addVia(at)
      else planner.setStart(at)
    },
  })
  const coordinates = view ? view.coordinates : loop?.geometry.coordinates
  const line = useMemo(
    () => (coordinates?.length ? coordinates.map(([lon, lat]) => [lat, lon] as [number, number]) : null),
    [coordinates],
  )
  const lines = useMemo(() => (line ? [line] : []), [line])
  useEffect(() => {
    if (!line) return
    const bounds = L.latLngBounds(line)
    if (!map.getBounds().contains(bounds)) map.flyToBounds(bounds, { padding: [40, 40], duration: 0.8 })
  }, [map, line])
  const startIcon = useMemo(() => createStartIcon(), [])

  return (
    <>
      {line && (
        <>
          {/* Above the coverage layers (overlay pane, 400), which redraw on every refetch */}
          <Pane name="planned-loop" style={{ zIndex: 450 }}>
            <Polyline positions={line} pathOptions={{ color: PLAN_ACCENT, weight: 8, opacity: 0.22 }} interactive={false} />
            <Polyline positions={line} pathOptions={{ color: PLAN_ACCENT, weight: 3, opacity: 0.95 }} interactive={false} />
          </Pane>
          <RouteArrows lines={lines} />
        </>
      )}
      {view && line && <Marker position={line[0]} icon={startIcon} interactive={false} />}
      {!view && start && (
        <Marker
          position={start}
          icon={startIcon}
          draggable
          eventHandlers={{
            dragend: e => {
              const at = (e.target as L.Marker).getLatLng()
              planner.setStart([at.lat, at.lng])
            },
          }}
        >
          <Tooltip direction="top" offset={[0, -12]}>Start · drag to move</Tooltip>
        </Marker>
      )}
      {!view && request.via.map((at, i) => (
        <Marker key={`${i}-${at[0]}-${at[1]}`} position={at} icon={createViaIcon(i + 1)}
                eventHandlers={{ click: () => planner.removeVia(i) }}>
          <Tooltip direction="top" offset={[0, -10]}>Point {i + 1} · tap to remove</Tooltip>
        </Marker>
      ))}
    </>
  )
}

/** A slider that plans only once let go: every step of a drag would be a request. */
function PlanSlider({ label, value, min, max, step, format, onCommit, isLight }: {
  label: string
  value: number
  min: number
  max: number
  step: number
  format: (v: number) => string
  onCommit: (v: number) => void
  isLight: boolean
}) {
  const [draft, setDraft] = useState<number | null>(null)
  // The drag's last value, read when it ends (the state may not have re-rendered yet)
  const latest = useRef<number | null>(null)
  const commit = () => {
    if (latest.current !== null) onCommit(latest.current)
    latest.current = null
    setDraft(null)
  }
  const shown = draft ?? value
  return (
    <label className="flex items-center gap-2">
      <span className="text-[11px] text-gray-500 w-20 shrink-0">{label}</span>
      <input
        type="range"
        className="w-36 h-6 md:h-4 accent-current"
        style={{ color: PLAN_ACCENT }}
        min={min}
        max={max}
        step={step}
        value={shown}
        onChange={e => { latest.current = Number(e.target.value); setDraft(latest.current) }}
        onPointerUp={commit}
        onKeyUp={commit}
        onBlur={commit}
      />
      <span className={clsx('text-xs font-mono tabular-nums w-16 text-right', isLight ? 'text-gray-700' : 'text-gray-200')}>
        {format(shown)}
      </span>
    </label>
  )
}

/** Pick a watch (the primary one first) and send; "Garmin Connect only" just creates the course. */
function GarminSend({ onSend, busy, done, label = 'Send to Garmin' }: {
  onSend: (deviceId: number | null, deviceName: string | null) => void
  busy: boolean
  done: string | null
  label?: string
}) {
  const { data: devices, error } = useGarminDevices(true)
  const [choice, setChoice] = useState<string | null>(null)
  if (error) return <span className="text-[10px] text-gray-500">Garmin Connect isn’t connected</span>
  const selected = choice ?? (devices?.[0] ? String(devices[0].device_id) : 'none')
  const device = devices?.find(d => String(d.device_id) === selected) ?? null
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      <select value={selected} onChange={e => setChoice(e.target.value)} className="select text-[11px] py-1 px-1.5"
              aria-label="Watch to send the course to" disabled={!devices}>
        {devices?.map(d => <option key={d.device_id} value={d.device_id}>{d.name}</option>)}
        <option value="none">Garmin Connect only</option>
      </select>
      <button className="btn text-[11px] py-1 px-2.5 inline-flex items-center gap-1" disabled={busy || !devices}
              onClick={() => onSend(device?.device_id ?? null, device?.name ?? null)}
              title={device ? `Create the course in Garmin Connect and send it to ${device.name}` : 'Create the course in Garmin Connect'}>
        <GarminIcon /> {busy ? 'Sending…' : label}
      </button>
      {done && <span className="text-[10px] text-emerald-400">{done}</span>}
    </div>
  )
}

function sentMessage(deviceName: string | null): string {
  return deviceName ? `Sent: sync ${deviceName} to get it` : 'In Garmin Connect'
}

/** Planning: distance, new-street share, ways to avoid, the loop's numbers,
 *  and saving it (to the routes list, GPX, Garmin). */
export function LoopPlanPanel({ planner, slug, className, isLight, onClose }: {
  planner: LoopPlanner
  slug: string | undefined
  className: string
  isLight: boolean
  onClose: () => void
}) {
  const { loop, request, planning, error, start, saved } = planner
  const props = loop?.properties
  const saveMutation = useSaveRoute(slug)
  const sendMutation = useSendRouteToGarmin(slug)
  const [name, setName] = useState<string | null>(null)
  const [sent, setSent] = useState<{ planId: string; text: string } | null>(null)
  const defaultName = props ? `Loop ${props.length_km.toFixed(1)} km · ${props.new_km.toFixed(1)} new` : ''
  const routeName = (name ?? defaultName).trim() || defaultName

  const save = async (): Promise<SavedRoute | null> => {
    if (saved) return saved
    if (!loop) return null
    const route = await saveMutation.mutateAsync({ name: routeName, plan_id: loop.properties.plan_id, request })
    planner.markSaved(route)
    return route
  }
  const send = async (deviceId: number | null, deviceName: string | null) => {
    const planId = loop?.properties.plan_id
    const route = await save()
    if (!route || !planId) return
    planner.markSaved(await sendMutation.mutateAsync({ id: route.id, device_id: deviceId }))
    setSent({ planId, text: sentMessage(deviceName) })
  }
  const hint = !start
    ? 'Tap the map to set the start'
    : request.via.length < PLAN_MAX_VIA
      ? `Drag the start to move it · tap the map to add a point the loop must pass (up to ${PLAN_MAX_VIA})`
      : 'Drag the start to move it · tap a numbered point to remove it'

  return (
    <div className={clsx('px-3 py-2 flex flex-col gap-1.5 max-w-[calc(100vw-2rem)]', className)}>
      <div className="flex items-center gap-3">
        <span className="eyebrow text-[9px]">Plan a run</span>
        {props && (
          <span className={clsx('flex items-baseline gap-2', planning && 'opacity-50')}>
            <span className={clsx('text-sm font-mono tabular-nums font-semibold', isLight ? 'text-gray-900' : 'text-gray-100')}>
              {props.length_km.toFixed(1)} km
            </span>
            <span className="text-xs font-mono tabular-nums" style={{ color: PLAN_ACCENT }}>
              {props.new_km.toFixed(1)} km new
            </span>
            <span className="text-[11px] text-gray-500">{coveredPct(props.length_km, props.new_km)}% covered</span>
          </span>
        )}
        {planning && <span className="text-[11px] text-gray-500 animate-pulse">planning…</span>}
        <button onClick={onClose} className={clsx('ml-auto text-[11px]', isLight ? 'text-gray-400 hover:text-gray-700' : 'text-gray-500 hover:text-gray-200')}
                aria-label="Close planner">
          ✕
        </button>
      </div>
      <PlanSlider label="Distance" value={request.distance_km} min={2} max={42} step={0.5}
                  format={v => `${v} km`} onCommit={planner.setDistance} isLight={isLight} />
      <PlanSlider label="New streets" value={Math.round(request.new_share * 100)} min={0} max={100} step={5}
                  format={v => `${v}%`} onCommit={v => planner.setNewShare(v / 100)} isLight={isLight} />
      <div className="flex items-center gap-0.5 flex-wrap">
        <span className="text-[11px] text-gray-500 w-20 shrink-0">Avoid</span>
        {AVOIDABLE.map(([way, label]) => (
          <button key={way} className="chip whitespace-nowrap" data-active={request.avoid.includes(way)}
                  onClick={() => planner.toggleAvoid(way)}>
            {label}
          </button>
        ))}
      </div>
      {error && <span className="text-[11px] text-red-400 max-w-80">{error}</span>}
      <div className="flex items-center gap-1.5 flex-wrap">
        <button className="btn text-[11px] py-1 px-2.5" onClick={planner.another} disabled={planning || !start}
                title="Same distance and points, different streets">
          ↻ Suggest another
        </button>
        {request.via.length > 0 && (
          <button className="btn text-[11px] py-1 px-2.5" onClick={planner.clearVia}>
            Remove {request.via.length === 1 ? 'the point' : 'the points'}
          </button>
        )}
      </div>
      {loop && props && (
        <div className={clsx('flex flex-col gap-1.5 pt-1.5 border-t', isLight ? 'border-gray-200' : 'border-surface-600')}>
          <div className="flex items-center gap-1.5">
            <input
              value={name ?? defaultName}
              onChange={e => setName(e.target.value)}
              className="input text-xs py-1 px-2 w-52"
              aria-label="Route name"
              maxLength={80}
              disabled={!!saved}
            />
            <button className="btn text-[11px] py-1 px-2.5" onClick={() => { save().catch(() => {}) }}
                    disabled={!!saved || saveMutation.isPending} title="Keep it in the routes list below the map">
              {saved ? 'Saved ✓' : saveMutation.isPending ? 'Saving…' : 'Save'}
            </button>
            <button className="btn text-[11px] py-1 px-2.5" onClick={() => downloadGpx(routeName, loop.geometry.coordinates)}
                    title="Save the loop as a GPX file">
              ⤓ GPX
            </button>
          </div>
          <GarminSend
            onSend={(id, deviceName) => { send(id, deviceName).catch(() => {}) }}
            busy={saveMutation.isPending || sendMutation.isPending}
            done={sent && sent.planId === props.plan_id ? sent.text : null}
          />
        </div>
      )}
      <span className="text-[10px] text-gray-500 max-w-80">{hint}</span>
    </div>
  )
}

/** A saved loop or Garmin course on the map: its numbers, GPX, Garmin, delete. */
export function RouteViewPanel({ planner, slug, className, isLight }: {
  planner: LoopPlanner
  slug: string | undefined
  className: string
  isLight: boolean
}) {
  const view = planner.view
  const sendMutation = useSendRouteToGarmin(slug)
  const deleteMutation = useDeleteRoute(slug)
  const [sent, setSent] = useState<string | null>(null)
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  if (!view) return null
  const route = view.selection.kind === 'saved' ? view.selection.route : null

  const send = async (deviceId: number | null, deviceName: string | null) => {
    if (!route) return
    planner.show({ kind: 'saved', route: await sendMutation.mutateAsync({ id: route.id, device_id: deviceId }) })
    setSent(sentMessage(deviceName))
  }

  return (
    <div className={clsx('px-3 py-2 flex flex-col gap-1.5 max-w-[calc(100vw-2rem)]', className)}>
      <div className="flex items-center gap-3">
        <span className="eyebrow text-[9px]">{route ? 'Saved route' : 'Garmin course'}</span>
        {view.garminCourseId !== null && (
          <span className="text-gray-400" title="On Garmin Connect"><GarminIcon /></span>
        )}
        {planner.planning && <span className="text-[11px] text-gray-500 animate-pulse">loading…</span>}
        <button onClick={() => planner.show(null)}
                className={clsx('ml-auto text-[11px]', isLight ? 'text-gray-400 hover:text-gray-700' : 'text-gray-500 hover:text-gray-200')}>
          ← Back to planning
        </button>
      </div>
      <span className={clsx('text-sm font-semibold max-w-80 truncate', isLight ? 'text-gray-900' : 'text-gray-100')} title={view.name}>
        {view.name}
      </span>
      <span className="flex items-baseline gap-2">
        <span className={clsx('text-sm font-mono tabular-nums font-semibold', isLight ? 'text-gray-900' : 'text-gray-100')}>
          {view.length_km.toFixed(1)} km
        </span>
        {view.new_km !== null && view.city_km !== null && (
          <>
            <span className="text-xs font-mono tabular-nums" style={{ color: PLAN_ACCENT }}>
              {view.new_km > 0 ? `${view.new_km.toFixed(1)} km still new` : 'every street run ✓'}
            </span>
            <span className="text-[11px] text-gray-500">{coveredPct(view.city_km, view.new_km)}% covered</span>
          </>
        )}
      </span>
      {view.city_km !== null && view.city_km < 0.8 * view.length_km && (
        <span className="text-[10px] text-gray-500 max-w-80">
          Counted on its {view.city_km.toFixed(1)} km of streets in this city: the rest is off the city’s map
        </span>
      )}
      {view.selection.kind === 'garmin' && view.new_km === null && (
        <span className="text-[10px] text-gray-500 max-w-80">It doesn’t follow this city’s streets, so there’s nothing to count</span>
      )}
      {planner.error && <span className="text-[11px] text-red-400 max-w-80">{planner.error}</span>}
      <div className="flex items-center gap-1.5 flex-wrap">
        <button className="btn text-[11px] py-1 px-2.5" disabled={!view.coordinates.length}
                onClick={() => downloadGpx(view.name, view.coordinates)}>
          ⤓ GPX
        </button>
        {route && !confirmingDelete && (
          <button className="btn text-[11px] py-1 px-2.5" onClick={() => setConfirmingDelete(true)}
                  title="Remove it from the routes list (its Garmin course stays)">
            Delete
          </button>
        )}
        {route && confirmingDelete && (
          <>
            <button className="btn text-[11px] py-1 px-2.5 text-red-400 border-red-500/50" disabled={deleteMutation.isPending}
                    onClick={() => deleteMutation.mutate(route.id, { onSuccess: () => planner.show(null) })}>
              {deleteMutation.isPending ? 'Deleting…' : 'Delete it'}
            </button>
            <button className="btn text-[11px] py-1 px-2.5" onClick={() => setConfirmingDelete(false)}>Cancel</button>
          </>
        )}
      </div>
      {route && (
        <GarminSend
          onSend={(id, deviceName) => { send(id, deviceName).catch(() => {}) }}
          busy={sendMutation.isPending}
          done={sent}
          label={route.garmin_course_id ? 'Send to watch' : 'Send to Garmin'}
        />
      )}
    </div>
  )
}
