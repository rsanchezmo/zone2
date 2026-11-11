import { useState, useRef, type ReactNode } from 'react'
import {
  startOfMonth, endOfMonth, eachDayOfInterval, format, addMonths, subMonths, isSameMonth, isToday,
  startOfWeek, endOfWeek, parseISO,
} from 'date-fns'
import { useWorkoutTemplates, useCreateWorkoutTemplate, type WorkoutTemplate } from '../../api/workouts'
import type { RaceEvent, RaceEventInput } from '../../api/races'
import type { SessionFields, SessionScoresResponse, TrainingSession } from '../../api/calendar'
import { getSportColor } from '../../constants/sportColors'
import {
  getPaceUnit, getDistUnit, formatPace, isSpeedSport, parsePaceInput, toInputDist, fromInputDist,
  formatDistExact,
} from '../../utils/formatSpeed'
import { scoreColor } from '../../utils/scoreColor'
import { WEEKDAY_LETTERS } from '../../constants/weekdays'
import SportTypeCombobox from '../shared/SportTypeCombobox'
import { FlagIcon } from '../icons'
import clsx from 'clsx'
import { useTheme } from '../../hooks/useTheme'
import SegmentListBuilder, { SegmentSummary, type Segment } from '../shared/SegmentListBuilder'
import { segmentsTotalKm } from '../shared/segmentUtils'
import RaceEventForm from '../shared/RaceEventForm'
import { SESSION_GOALS, SESSION_GOAL_KEYS, type SessionGoalKey } from '../../constants/sessionGoals'
import RowActions from '../shared/RowActions'
import { rowActionClass } from '../shared/rowActionClass'
import Modal from '../shared/Modal'
import { errorDetail } from '../../api/client'
import { useToast } from '../../hooks/useToast'
import WatchStatus from './WatchStatus'
import PlanTag from '../coach/PlanTag'

const RACE_ACCENT = '#f59e0b'

/** The session form while it is filled in: amounts stay as typed until saved. */
interface SessionDraft {
  sportType: string
  description: string
  goals: Set<SessionGoalKey>
  plannedDistanceKm: string
  plannedDurationMins: string
  targetAvgPace: string
  targetPaceMin: string
  targetPaceMax: string
  targetHrZone: string
  targetZonePct: string
  segments: Segment[]
  workoutTemplateId: number | null
}

function emptyDraft(sportType: string): SessionDraft {
  return {
    sportType,
    description: '',
    goals: new Set(),
    plannedDistanceKm: '',
    plannedDurationMins: '',
    targetAvgPace: '',
    targetPaceMin: '',
    targetPaceMax: '',
    targetHrZone: '',
    targetZonePct: '80',
    segments: [],
    workoutTemplateId: null,
  }
}

/** A goal's fields once it is removed. */
const GOAL_CLEARED: Record<SessionGoalKey, Partial<SessionDraft>> = {
  distance: { plannedDistanceKm: '' },
  duration: { plannedDurationMins: '' },
  avg_pace: { targetAvgPace: '' },
  pace_range: { targetPaceMin: '', targetPaceMax: '' },
  hr_zone: { targetHrZone: '', targetZonePct: '80' },
  segments: { segments: [], workoutTemplateId: null },
}

/** A goal's starting values when it is added, keeping any already typed. */
function goalDefaults(key: SessionGoalKey, d: SessionDraft): Partial<SessionDraft> {
  const perKm = getPaceUnit(d.sportType) === 'min/km'
  switch (key) {
    case 'distance': return { plannedDistanceKm: d.plannedDistanceKm || '10' }
    case 'duration': return { plannedDurationMins: d.plannedDurationMins || '60' }
    case 'avg_pace': return { targetAvgPace: d.targetAvgPace || (perKm ? '5.5' : '28') }
    case 'pace_range': return {
      targetPaceMin: d.targetPaceMin || (perKm ? '5.0' : '25'),
      targetPaceMax: d.targetPaceMax || (perKm ? '6.0' : '32'),
    }
    case 'hr_zone': return { targetHrZone: d.targetHrZone || '2' }
    case 'segments': return {}
  }
}

function draftFromSession(s: TrainingSession): SessionDraft {
  const segments = Array.isArray(s.segments) ? s.segments : []
  const hasSegments = segments.length > 0
  // Paces are stored as decimals: shown as M:SS for pace sports, X.X for speed sports
  const useSpeed = isSpeedSport(s.sport_type)
  const goals = new Set<SessionGoalKey>()
  // A distance computed from the segments is not a goal of its own
  if (s.planned_distance_km != null && !hasSegments) goals.add('distance')
  if (s.planned_duration_mins != null) goals.add('duration')
  if (s.target_avg_pace != null) goals.add('avg_pace')
  if (s.target_pace_min != null || s.target_pace_max != null) goals.add('pace_range')
  if (s.target_hr_zone != null) goals.add('hr_zone')
  if (hasSegments) goals.add('segments')
  return {
    sportType: s.sport_type,
    description: s.description || '',
    goals,
    plannedDistanceKm: s.planned_distance_km != null && !hasSegments ? toInputDist(s.planned_distance_km, s.sport_type) : '',
    plannedDurationMins: s.planned_duration_mins != null ? String(s.planned_duration_mins) : '',
    targetAvgPace: s.target_avg_pace != null ? formatPace(s.target_avg_pace, useSpeed) : '',
    targetPaceMin: s.target_pace_min != null ? formatPace(s.target_pace_min, useSpeed) : '',
    targetPaceMax: s.target_pace_max != null ? formatPace(s.target_pace_max, useSpeed) : '',
    targetHrZone: s.target_hr_zone != null ? String(s.target_hr_zone) : '',
    targetZonePct: s.target_zone_pct != null ? String(s.target_zone_pct) : '80',
    segments,
    workoutTemplateId: hasSegments ? s.workout_template_id ?? null : null,
  }
}

/** The fields to save: a goal not in the form is sent as null, which clears it. */
function sessionFields(d: SessionDraft): SessionFields {
  const useSpeed = isSpeedSport(d.sportType)
  const withRange = d.goals.has('pace_range')
  const withZone = d.goals.has('hr_zone') && d.targetHrZone !== ''
  const withSegments = d.goals.has('segments') && d.segments.length > 0
  const distance = d.goals.has('distance') ? fromInputDist(d.plannedDistanceKm, d.sportType) : null
  // Without a distance goal the segments' total stands in, so the activity can be matched
  const segmentsKm = withSegments ? segmentsTotalKm(d.segments) : 0
  return {
    sport_type: d.sportType,
    description: d.description || null,
    planned_distance_km: segmentsKm > 0 && !distance ? Math.round(segmentsKm * 10) / 10 : distance,
    planned_duration_mins: d.goals.has('duration') && d.plannedDurationMins ? parseFloat(d.plannedDurationMins) : null,
    target_avg_pace: d.goals.has('avg_pace') && d.targetAvgPace ? parsePaceInput(d.targetAvgPace, useSpeed) : null,
    target_pace_min: withRange && d.targetPaceMin ? parsePaceInput(d.targetPaceMin, useSpeed) : null,
    target_pace_max: withRange && d.targetPaceMax ? parsePaceInput(d.targetPaceMax, useSpeed) : null,
    target_hr_zone: withZone ? parseInt(d.targetHrZone) : null,
    target_zone_pct: withZone ? (d.targetZonePct ? parseFloat(d.targetZonePct) : 80) : null,
    segments: withSegments ? d.segments : null,
    workout_template_id: withSegments ? d.workoutTemplateId : null,
  }
}

/** A day's planned sessions and race events, and the form to add or edit them. */
export default function SessionModal({
  date, sessions, scores, races, onAdd, onCopy, onUpdate, onDelete,
  onAddRace, onUpdateRace, onDeleteRace, onClose,
}: {
  date: string
  sessions: TrainingSession[]
  scores: SessionScoresResponse | undefined
  races: RaceEvent[]
  onAdd: (fields: SessionFields) => void
  onCopy: (session: TrainingSession, targetDate: string) => void
  onUpdate: (id: number, fields: SessionFields) => void
  onDelete: (id: number) => void
  onAddRace: (race: RaceEventInput) => void
  onUpdateRace: (id: number, race: RaceEventInput) => void
  onDeleteRace: (id: number) => void
  onClose: () => void
}) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const [editingId, setEditingId] = useState<number | null>(null)
  const [draft, setDraft] = useState<SessionDraft>(() => emptyDraft('Run'))
  const [showGoalPicker, setShowGoalPicker] = useState(false)
  const [showTemplatePicker, setShowTemplatePicker] = useState(false)
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null)
  const [copyingSessionId, setCopyingSessionId] = useState<number | null>(null)
  const [copyMonth, setCopyMonth] = useState(() => startOfMonth(parseISO(date)))
  const [saveTemplateName, setSaveTemplateName] = useState('')
  const [showSaveTemplate, setShowSaveTemplate] = useState(false)
  const [showRaceForm, setShowRaceForm] = useState(false)
  // The race being edited; null while adding one
  const [editingRace, setEditingRace] = useState<RaceEvent | null>(null)
  const [confirmDeleteRaceId, setConfirmDeleteRaceId] = useState<number | null>(null)

  const formRef = useRef<HTMLDivElement>(null)
  const editingSession = sessions.find(s => s.id === editingId) ?? null
  const editColor = editingSession ? getSportColor(editingSession.sport_type) : null

  const { data: templates } = useWorkoutTemplates(draft.sportType)
  const createTemplate = useCreateWorkoutTemplate()
  const { toast } = useToast()

  const patch = (fields: Partial<SessionDraft>) => setDraft(d => ({ ...d, ...fields }))

  /** Fills the form, or empties it, and closes its pickers. */
  function loadForm(id: number | null, next: SessionDraft) {
    setEditingId(id)
    setDraft(next)
    setShowGoalPicker(false)
    setShowTemplatePicker(false)
  }

  function startEditRace(r: RaceEvent) {
    setEditingRace(r)
    setShowRaceForm(true)
  }

  function closeRaceForm() {
    setShowRaceForm(false)
    setEditingRace(null)
  }

  function startEdit(s: TrainingSession) {
    loadForm(s.id, draftFromSession(s))
    formRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  function cancelEdit() {
    loadForm(null, emptyDraft('Run'))
  }

  function save() {
    const fields = sessionFields(draft)
    if (editingId) {
      onUpdate(editingId, fields)
      cancelEdit()
      return
    }
    onAdd(fields)
    loadForm(null, emptyDraft(draft.sportType))
  }

  /** Saving the session saves its workout anyway; this names it first. */
  function saveAsWorkout() {
    const name = saveTemplateName.trim()
    if (!name) return
    createTemplate.mutate({ name, sport_type: draft.sportType, segments: draft.segments }, {
      onSuccess: t => { patch({ workoutTemplateId: t.id }); toast(`Saved as “${t.name}”`, 'success') },
      onError: e => toast(errorDetail(e, 'Could not save the workout'), 'error'),
    })
    setShowSaveTemplate(false)
    setSaveTemplateName('')
  }

  function addGoal(key: SessionGoalKey) {
    patch({ ...goalDefaults(key, draft), goals: new Set(draft.goals).add(key) })
    setShowGoalPicker(false)
  }

  function removeGoal(key: SessionGoalKey) {
    const goals = new Set(draft.goals)
    goals.delete(key)
    patch({ ...GOAL_CLEARED[key], goals })
    if (key === 'segments') setShowTemplatePicker(false)
  }

  const paceUnit = getPaceUnit(draft.sportType)
  return (
    <Modal onClose={onClose} className="p-6 max-w-md max-h-[85vh]">
        <div className="flex items-center justify-between mb-5">
          <div>
            <div className="eyebrow mb-0.5">{format(parseISO(date), 'EEEE')}</div>
            <h3
              className="text-lg font-semibold tracking-tight tabular-nums text-fg-strong"
              style={{ letterSpacing: '-0.02em' }}
            >
              {format(parseISO(date), 'MMM d, yyyy')}
            </h3>
          </div>
          <button
            onClick={onClose}
            className={clsx('p-1 rounded transition-colors', isLight ? 'text-gray-400 hover:text-gray-700 hover:bg-black/5' : 'text-gray-500 hover:text-gray-200 hover:bg-white/5')}
            aria-label="Close"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" aria-hidden="true"><path d="M18 6L6 18M6 6l12 12" /></svg>
          </button>
        </div>

        {/* Race Events section */}
        {(races.length > 0 || showRaceForm) && (
          <div className="mb-4 space-y-2">
            <div className="eyebrow flex items-center gap-1.5">
              <span className="text-amber-500"><FlagIcon size={10} /></span> Race events
            </div>
            {races.map(r => (
              <div key={r.id} className="rounded p-2 border transition-colors flex items-center justify-between gap-2"
                style={{ borderColor: `${RACE_ACCENT}60`, backgroundColor: `${RACE_ACCENT}08` }}
              >
                <div className="flex items-center gap-2 min-w-0 cursor-pointer" onClick={() => startEditRace(r)}>
                  <span style={{ color: RACE_ACCENT }}><FlagIcon size={11} /></span>
                  <span className="text-sm font-medium" style={{ color: RACE_ACCENT }}>{r.name}</span>
                  {r.distance_km != null && (
                    <span className="text-xs text-gray-400">{formatDistExact(r.distance_km, r.sport_type)}</span>
                  )}
                  {r.location != null && <span className="text-xs text-gray-500 truncate">{r.location}</span>}
                </div>
                <RowActions
                  isConfirming={confirmDeleteRaceId === r.id}
                  onEdit={() => startEditRace(r)}
                  onConfirmDelete={() => { onDeleteRace(r.id); setConfirmDeleteRaceId(null) }}
                  onAskDelete={() => setConfirmDeleteRaceId(r.id)}
                  onCancelDelete={() => setConfirmDeleteRaceId(null)}
                />
              </div>
            ))}
            {showRaceForm && (
              <div className="pt-1">
                <RaceEventForm
                  key={editingRace?.id ?? 'new'}
                  initial={editingRace}
                  date={date}
                  dateField={false}
                  accent={RACE_ACCENT}
                  onSubmit={race => {
                    if (editingRace) onUpdateRace(editingRace.id, race)
                    else onAddRace(race)
                    closeRaceForm()
                  }}
                  onCancel={closeRaceForm}
                />
              </div>
            )}
          </div>
        )}
        {!showRaceForm && (
          <button
            onClick={() => { setEditingRace(null); setShowRaceForm(true) }}
            className="mb-3 text-[11px] uppercase tracking-[0.15em] flex items-center gap-1.5 text-amber-500/70 hover:text-amber-500 transition-colors"
          >
            <FlagIcon size={10} /> Add race event
          </button>
        )}

        {sessions.length > 0 && (
          <div className="mb-4 space-y-2">
            <div className="eyebrow">Planned Sessions</div>
            {sessions.map(s => {
              const sColor = getSportColor(s.sport_type as string)
              const isConfirming = confirmDeleteId === (s.id as number)
              const isEditing = editingId === s.id
              const sessionScore = scores?.[String(s.id as number)]
              return (
                <div key={s.id as number}>
                  <div className={clsx('rounded p-2 border transition-colors', isEditing ? 'border-solid' : 'border-dashed')}
                    style={{
                      borderColor: isEditing ? sColor : `${sColor}60`,
                      backgroundColor: isEditing ? `${sColor}25` : `${sColor}10`,
                      boxShadow: isEditing ? `0 0 0 1px ${sColor}` : undefined,
                    }}
                  >
                    <div className="flex items-center justify-between">
                      <div className={clsx('flex items-center gap-2 min-w-0', !isEditing && 'cursor-pointer')} onClick={() => { if (!isEditing) startEdit(s) }}>
                        <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: sColor }} />
                        <span className="text-sm" style={{ color: sColor }}>{String(s.sport_type)}</span>
                        {s.plan_name && <PlanTag name={s.plan_name} />}
                        {!!s.description && (
                          <span className="text-xs text-gray-400 truncate">{String(s.description)}</span>
                        )}
                        {sessionScore && (
                          <span
                            className="text-xs font-bold font-mono px-1.5 py-0.5 rounded"
                            style={{ color: scoreColor(sessionScore.overall_score as number), backgroundColor: `${scoreColor(sessionScore.overall_score as number)}15` }}
                          >
                            {sessionScore.overall_score as number}
                          </span>
                        )}
                      </div>
                      <div className="shrink-0 ml-2">
                        {isEditing ? (
                          <span className="eyebrow text-[10px] font-semibold" style={{ color: sColor }}>Editing below</span>
                        ) : (
                          <RowActions
                            isConfirming={isConfirming}
                            onEdit={() => startEdit(s)}
                            onConfirmDelete={() => { onDelete(s.id); setConfirmDeleteId(null) }}
                            onAskDelete={() => setConfirmDeleteId(s.id)}
                            onCancelDelete={() => setConfirmDeleteId(null)}
                            extra={
                              <button
                                onClick={() => setCopyingSessionId(copyingSessionId === s.id ? null : s.id)}
                                className={rowActionClass(isLight, copyingSessionId === s.id)}
                              >Copy</button>
                            }
                          />
                        )}
                      </div>
                    </div>
                    {/* Segment summary */}
                    {!!s.segments && Array.isArray(s.segments) && (s.segments as Segment[]).length > 0 && (
                      <div className="mt-1.5">
                        <SegmentSummary segments={s.segments as Segment[]} />
                      </div>
                    )}
                    <WatchStatus session={s} label className="mt-1.5 flex max-w-full" />
                  </div>
                  {copyingSessionId === (s.id as number) && (() => {
                    const mStart = startOfWeek(startOfMonth(copyMonth), { weekStartsOn: 1 })
                    const mEnd = endOfWeek(endOfMonth(copyMonth), { weekStartsOn: 1 })
                    const mDays = eachDayOfInterval({ start: mStart, end: mEnd })
                    return (
                      <div className={clsx('mt-1 p-2 border rounded-lg', isLight ? 'bg-gray-50 border-surface-600' : 'bg-surface-700/50 border-surface-600')}>
                        <div className="flex items-center justify-between mb-2">
                          <button onClick={() => setCopyMonth(m => subMonths(m, 1))} className="text-gray-400 hover:text-gray-200 text-xs px-1">&lt;</button>
                          <span className="text-xs text-gray-300 font-medium">{format(copyMonth, 'MMM yyyy')}</span>
                          <button onClick={() => setCopyMonth(m => addMonths(m, 1))} className="text-gray-400 hover:text-gray-200 text-xs px-1">&gt;</button>
                        </div>
                        <div className="grid grid-cols-7 gap-0.5 text-center">
                          {WEEKDAY_LETTERS.map((d, i) => (
                            <div key={i} className="text-[9px] text-gray-600 py-0.5">{d}</div>
                          ))}
                          {mDays.map(d => {
                            const ds = format(d, 'yyyy-MM-dd')
                            const inM = isSameMonth(d, copyMonth)
                            const isCurrent = ds === date
                            return (
                              <button
                                key={ds}
                                disabled={isCurrent}
                                onClick={() => {
                                  onCopy(s, ds)
                                  setCopyingSessionId(null)
                                }}
                                className={clsx(
                                  'text-[10px] py-1 rounded transition-colors',
                                  isCurrent ? 'text-gray-600 cursor-not-allowed' : 'hover:bg-blue-400/20 hover:text-blue-400',
                                  inM ? 'text-gray-400' : 'text-gray-600',
                                  isToday(d) && 'font-bold text-gray-100',
                                )}
                              >
                                {format(d, 'd')}
                              </button>
                            )
                          })}
                        </div>
                      </div>
                    )
                  })()}
                </div>
              )
            })}
          </div>
        )}

        <div
          ref={formRef}
          className={clsx('space-y-3 scroll-mt-2 transition-colors', editColor && 'rounded-lg border p-3 -mx-3')}
          style={editColor ? { borderColor: `${editColor}80`, backgroundColor: `${editColor}0d` } : undefined}
        >
          {editingSession && editColor ? (
            <div className="eyebrow flex items-center gap-1.5 min-w-0" style={{ color: editColor }}>
              <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: editColor }} />
              <span className="truncate">Editing {editingSession.sport_type}{editingSession.description ? ` · ${editingSession.description}` : ''}</span>
            </div>
          ) : (
            <div className="eyebrow">Add Session</div>
          )}
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Session Type</label>
            <SportTypeCombobox
              value={draft.sportType}
              onChange={sportType => patch({ sportType })}
              className="input w-full"
              isLight={isLight}
            />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Description</label>
            <textarea
              placeholder="e.g. Easy 10k recovery run"
              value={draft.description}
              onChange={e => patch({ description: e.target.value })}
              className="input w-full"
              rows={3}
            />
          </div>

          {/* Goal cards */}
          {draft.goals.size > 0 && (
            <div className="space-y-2">
              {draft.goals.has('distance') && (
                <GoalCard goal="distance" onRemove={() => removeGoal('distance')}>
                  <div className="flex items-center gap-2">
                    <input
                      type="text" inputMode="decimal" placeholder="10"
                      value={draft.plannedDistanceKm} onChange={e => patch({ plannedDistanceKm: e.target.value })}
                      className="input w-24"
                    />
                    <span className="text-xs text-gray-500">{getDistUnit(draft.sportType)}</span>
                  </div>
                </GoalCard>
              )}

              {draft.goals.has('duration') && (
                <GoalCard goal="duration" onRemove={() => removeGoal('duration')}>
                  <div className="flex items-center gap-2">
                    <input
                      type="text" inputMode="decimal" placeholder="60"
                      value={draft.plannedDurationMins} onChange={e => patch({ plannedDurationMins: e.target.value })}
                      className="input w-24"
                    />
                    <span className="text-xs text-gray-500">min</span>
                  </div>
                </GoalCard>
              )}

              {draft.goals.has('avg_pace') && (
                <GoalCard goal="avg_pace" onRemove={() => removeGoal('avg_pace')}>
                  <div className="flex items-center gap-2">
                    <input
                      type="text" inputMode="decimal" placeholder={paceUnit === 'min/km' ? '5:10' : '28'}
                      value={draft.targetAvgPace} onChange={e => patch({ targetAvgPace: e.target.value })}
                      className="input w-24"
                    />
                    <span className="text-xs text-gray-500">{paceUnit}</span>
                  </div>
                </GoalCard>
              )}

              {draft.goals.has('pace_range') && (
                <GoalCard goal="pace_range" onRemove={() => removeGoal('pace_range')}>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="eyebrow mb-1 block">
                        {paceUnit === 'min/km' ? 'Fastest' : 'Min speed'} ({paceUnit})
                      </label>
                      <input
                        type="text" inputMode="decimal" placeholder={paceUnit === 'min/km' ? '4:50' : '25'}
                        value={draft.targetPaceMin} onChange={e => patch({ targetPaceMin: e.target.value })}
                        className="input w-full"
                      />
                    </div>
                    <div>
                      <label className="eyebrow mb-1 block">
                        {paceUnit === 'min/km' ? 'Slowest' : 'Max speed'} ({paceUnit})
                      </label>
                      <input
                        type="text" inputMode="decimal" placeholder={paceUnit === 'min/km' ? '5:20' : '32'}
                        value={draft.targetPaceMax} onChange={e => patch({ targetPaceMax: e.target.value })}
                        className="input w-full"
                      />
                    </div>
                  </div>
                </GoalCard>
              )}

              {draft.goals.has('hr_zone') && (
                <GoalCard goal="hr_zone" onRemove={() => removeGoal('hr_zone')}>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="eyebrow mb-1 block">Zone</label>
                      <select value={draft.targetHrZone} onChange={e => patch({ targetHrZone: e.target.value })} className="select w-full">
                        <option value="">Select</option>
                        {[1, 2, 3, 4, 5].map(z => <option key={z} value={z}>Zone {z}</option>)}
                      </select>
                    </div>
                    <div>
                      <label className="eyebrow mb-1 block">Target %</label>
                      <input
                        type="text" inputMode="decimal" placeholder="80"
                        value={draft.targetZonePct} onChange={e => patch({ targetZonePct: e.target.value })}
                        className="input w-full"
                      />
                    </div>
                  </div>
                </GoalCard>
              )}

              {draft.goals.has('segments') && (
                <GoalCard goal="segments" onRemove={() => removeGoal('segments')}>
                  {/* Template picker */}
                  <div className="mb-2">
                    <button
                      onClick={() => setShowTemplatePicker(v => !v)}
                      className="text-[11px] rounded px-2 py-1 border transition-all"
                      style={{ borderColor: '#22d3ee40', color: '#22d3ee', backgroundColor: '#22d3ee10' }}
                    >
                      {showTemplatePicker ? 'Hide templates' : 'Pick from library'}
                    </button>
                    {showTemplatePicker && templates && templates.length > 0 && (
                      <div className="mt-1.5 space-y-1 max-h-32 overflow-y-auto">
                        {templates.map((t: WorkoutTemplate) => (
                          <button
                            key={t.id}
                            onClick={() => {
                              patch({ segments: t.segments || [], workoutTemplateId: t.id })
                              setShowTemplatePicker(false)
                            }}
                            className={clsx(
                              'w-full text-left text-xs rounded px-2 py-1.5 border transition-colors',
                              draft.workoutTemplateId === t.id
                                ? 'border-blue-400/40 bg-blue-400/10 text-blue-400'
                                : 'border-surface-600 hover:border-surface-500 text-gray-300'
                            )}
                          >
                            <div className="font-medium">{t.name}</div>
                            <SegmentSummary segments={t.segments || []} />
                          </button>
                        ))}
                      </div>
                    )}
                    {showTemplatePicker && (!templates || templates.length === 0) && (
                      <div className="text-[10px] text-gray-500 mt-1">No templates for {draft.sportType}</div>
                    )}
                  </div>
                  <SegmentListBuilder
                    segments={draft.segments}
                    onChange={segments => patch({ segments })}
                    paceUnit={paceUnit}
                    sportType={draft.sportType}
                    compact
                  />
                  {/* Save as template */}
                  {draft.segments.length > 0 && (
                    <div className="mt-2">
                      {!showSaveTemplate ? (
                        <button
                          onClick={() => { setShowSaveTemplate(true); setSaveTemplateName(draft.description || '') }}
                          className="text-[11px] rounded px-2 py-1 border transition-all"
                          style={{ borderColor: '#a855f740', color: '#a855f7', backgroundColor: '#a855f710' }}
                        >
                          Save as workout
                        </button>
                      ) : (
                        <div className="flex items-center gap-1.5">
                          <input
                            type="text"
                            placeholder="Workout name"
                            value={saveTemplateName}
                            onChange={e => setSaveTemplateName(e.target.value)}
                            className="input flex-1 text-xs py-1"
                            autoFocus
                            onKeyDown={e => {
                              if (e.key === 'Enter') saveAsWorkout()
                              if (e.key === 'Escape') { setShowSaveTemplate(false) }
                            }}
                          />
                          <button
                            onClick={saveAsWorkout}
                            className="text-[11px] rounded px-2 py-1 border transition-all"
                            style={{ borderColor: '#22c55e40', color: '#22c55e', backgroundColor: '#22c55e10' }}
                          >
                            Save
                          </button>
                          <button
                            onClick={() => setShowSaveTemplate(false)}
                            className="text-gray-500 hover:text-gray-300 text-xs px-1"
                          >
                            {'\u2715'}
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </GoalCard>
              )}
            </div>
          )}

          {/* Add Goal button + chip picker */}
          <div>
            <button
              onClick={() => setShowGoalPicker(v => !v)}
              className="text-xs flex items-center gap-1 transition-colors rounded-md px-2 py-1"
              style={{
                color: showGoalPicker ? '#ef4444' : '#9ca3af',
                backgroundColor: showGoalPicker ? '#ef444410' : 'transparent',
              }}
            >
              <span className="text-sm">{showGoalPicker ? '−' : '+'}</span>
              <span>{showGoalPicker ? 'Cancel' : 'Add Goal'}</span>
            </button>
            {showGoalPicker && (
              <div className="flex flex-wrap gap-1.5 mt-2">
                {SESSION_GOAL_KEYS.map(key => {
                  const { label, color, Icon } = SESSION_GOALS[key]
                  const isActive = draft.goals.has(key)
                  return (
                    <button
                      key={key}
                      disabled={isActive}
                      onClick={() => addGoal(key)}
                      className="text-xs rounded-full px-2.5 py-1 border transition-all inline-flex items-center gap-1.5"
                      style={{
                        borderColor: isActive ? '#4b5563' : `${color}50`,
                        color: isActive ? '#6b7280' : color,
                        backgroundColor: isActive ? 'transparent' : `${color}10`,
                        opacity: isActive ? 0.5 : 1,
                        cursor: isActive ? 'not-allowed' : 'pointer',
                      }}
                    >
                      {Icon && <Icon size={10} />} {label}
                    </button>
                  )
                })}
              </div>
            )}
          </div>

          <div className="flex gap-2 pt-2">
            <button
              onClick={save}
              className={clsx('flex-1 rounded py-2 text-sm font-medium transition-colors', isLight ? 'bg-gray-900 text-white hover:bg-gray-800' : 'bg-white/15 text-gray-100 border border-white/20 hover:bg-white/20')}
            >
              {editingId ? 'Save Changes' : 'Add'}
            </button>
            {editingId ? (
              <button onClick={cancelEdit} className={clsx('flex-1 rounded py-2 text-sm text-gray-400', isLight ? 'bg-surface-700 hover:text-gray-700' : 'bg-surface-700 hover:text-gray-200')}>
                Discard Changes
              </button>
            ) : (
              <button onClick={onClose} className={clsx('flex-1 rounded py-2 text-sm text-gray-400', isLight ? 'bg-surface-700 hover:text-gray-700' : 'bg-surface-700 hover:text-gray-200')}>
                Cancel
              </button>
            )}
          </div>
        </div>
    </Modal>
  )
}

/** A session target's card in the editor: its colour bar, label and remove button around its inputs. */
function GoalCard({ goal, onRemove, children }: { goal: SessionGoalKey; onRemove: () => void; children: ReactNode }) {
  const { label, color, Icon } = SESSION_GOALS[goal]
  return (
    <div className="flex rounded-lg overflow-hidden border" style={{ borderColor: `${color}20` }}>
      <div className="w-1 shrink-0" style={{ backgroundColor: color }} />
      <div className="flex-1 p-2.5" style={{ backgroundColor: `${color}08` }}>
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-xs font-medium flex items-center gap-1.5" style={{ color }}>
            {Icon && <Icon size={11} />} {label}
          </span>
          <button onClick={onRemove} className="text-gray-500 hover:text-gray-300 text-xs leading-none px-1" aria-label={`Remove ${label}`}>✕</button>
        </div>
        {children}
      </div>
    </div>
  )
}
