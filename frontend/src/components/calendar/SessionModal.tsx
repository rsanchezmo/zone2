import { useState, useRef, type ReactNode } from 'react'
import {
  startOfMonth, endOfMonth, eachDayOfInterval, format, addMonths, subMonths, isSameMonth, isToday,
  startOfWeek, endOfWeek, parseISO,
} from 'date-fns'
import {
  useWorkoutTemplates, useCreateWorkoutTemplate, type RaceEvent, type RaceEventInput, type SessionScoresResponse,
  type TrainingSession, type WorkoutTemplate,
} from '../../api/hooks'
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
import RaceEventForm from '../shared/RaceEventForm'
import { SESSION_GOALS, SESSION_GOAL_KEYS, type SessionGoalKey } from '../../constants/sessionGoals'
import RowActions from '../shared/RowActions'
import { rowActionClass } from '../shared/rowActionClass'
import Modal from '../shared/Modal'
import { errorDetail } from '../../api/client'
import { useToast } from '../../hooks/useToast'
import WatchStatus from './WatchStatus'

const RACE_ACCENT = '#f59e0b'

/** A day's planned sessions and race events, and the form to add or edit them. */
export default function SessionModal({
  date, sessions, scores, races, onAdd, onCopy, onUpdate, onDelete,
  onAddRace, onUpdateRace, onDeleteRace, onClose,
}: {
  date: string
  sessions: TrainingSession[]
  scores: SessionScoresResponse | undefined
  races: RaceEvent[]
  onAdd: (data: Record<string, unknown>) => void
  onCopy: (session: TrainingSession, targetDate: string) => void
  onUpdate: (id: number, data: Record<string, unknown>) => void
  onDelete: (id: number) => void
  onAddRace: (race: RaceEventInput) => void
  onUpdateRace: (id: number, race: RaceEventInput) => void
  onDeleteRace: (id: number) => void
  onClose: () => void
}) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const [sportType, setSportType] = useState('Run')
  const [description, setDescription] = useState('')
  const [editingId, setEditingId] = useState<number | null>(null)
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null)
  const [copyingSessionId, setCopyingSessionId] = useState<number | null>(null)
  const [copyMonth, setCopyMonth] = useState(() => startOfMonth(parseISO(date)))
  const [activeGoals, setActiveGoals] = useState<Set<SessionGoalKey>>(new Set())
  const [plannedDistanceKm, setPlannedDistanceKm] = useState<string>('')
  const [plannedDurationMins, setPlannedDurationMins] = useState<string>('')
  const [targetAvgPace, setTargetAvgPace] = useState<string>('')
  const [targetPaceMin, setTargetPaceMin] = useState<string>('')
  const [targetPaceMax, setTargetPaceMax] = useState<string>('')
  const [targetHrZone, setTargetHrZone] = useState<string>('')
  const [targetZonePct, setTargetZonePct] = useState<string>('80')
  const [showGoalPicker, setShowGoalPicker] = useState(false)
  const [segments, setSegments] = useState<Segment[]>([])
  const [workoutTemplateId, setWorkoutTemplateId] = useState<number | null>(null)
  const [showTemplatePicker, setShowTemplatePicker] = useState(false)
  const [saveTemplateName, setSaveTemplateName] = useState('')
  const [showSaveTemplate, setShowSaveTemplate] = useState(false)
  const [showRaceForm, setShowRaceForm] = useState(false)
  // The race being edited; null while adding one
  const [editingRace, setEditingRace] = useState<RaceEvent | null>(null)
  const [confirmDeleteRaceId, setConfirmDeleteRaceId] = useState<number | null>(null)

  const formRef = useRef<HTMLDivElement>(null)
  const editingSession = sessions.find(s => s.id === editingId) ?? null
  const editColor = editingSession ? getSportColor(editingSession.sport_type) : null

  const { data: templates } = useWorkoutTemplates(sportType)
  const createTemplate = useCreateWorkoutTemplate()
  const { toast } = useToast()

  function startEditRace(r: RaceEvent) {
    setEditingRace(r)
    setShowRaceForm(true)
  }

  function closeRaceForm() {
    setShowRaceForm(false)
    setEditingRace(null)
  }

  function startEdit(s: TrainingSession) {
    setEditingId(s.id)
    setSportType(s.sport_type)
    setDescription(s.description || '')
    const goals = new Set<SessionGoalKey>()
    const hasSegments = s.segments && Array.isArray(s.segments) && s.segments.length > 0
    // Don't show distance as a separate goal if it was auto-computed from segments
    if (s.planned_distance_km != null && !hasSegments) {
      goals.add('distance')
      setPlannedDistanceKm(toInputDist(s.planned_distance_km, s.sport_type))
    } else { setPlannedDistanceKm('') }
    if (s.planned_duration_mins != null) { goals.add('duration'); setPlannedDurationMins(String(s.planned_duration_mins)) } else { setPlannedDurationMins('') }
    // User enters M:SS (or decimal) for pace sports, X.X for speed sports — format stored decimal back into M:SS for display
    const useSpeed = isSpeedSport(s.sport_type)
    if (s.target_avg_pace != null) { goals.add('avg_pace'); setTargetAvgPace(formatPace(s.target_avg_pace, useSpeed)) } else { setTargetAvgPace('') }
    if (s.target_pace_min != null || s.target_pace_max != null) { goals.add('pace_range') }
    setTargetPaceMin(s.target_pace_min != null ? formatPace(s.target_pace_min, useSpeed) : '')
    setTargetPaceMax(s.target_pace_max != null ? formatPace(s.target_pace_max, useSpeed) : '')
    if (s.target_hr_zone != null) { goals.add('hr_zone') }
    setTargetHrZone(s.target_hr_zone != null ? String(s.target_hr_zone) : '')
    setTargetZonePct(s.target_zone_pct != null ? String(s.target_zone_pct) : '80')
    if (hasSegments && s.segments) {
      goals.add('segments')
      setSegments(s.segments)
      setWorkoutTemplateId(s.workout_template_id ?? null)
    } else {
      setSegments([])
      setWorkoutTemplateId(null)
    }
    setActiveGoals(goals)
    setShowGoalPicker(false)
    setShowTemplatePicker(false)
    formRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  function cancelEdit() {
    setEditingId(null)
    setSportType('Run')
    setDescription('')
    setActiveGoals(new Set())
    setPlannedDistanceKm('')
    setPlannedDurationMins('')
    setTargetAvgPace('')
    setTargetPaceMin('')
    setTargetPaceMax('')
    setTargetHrZone('')
    setTargetZonePct('80')
    setShowGoalPicker(false)
    setSegments([])
    setWorkoutTemplateId(null)
    setShowTemplatePicker(false)
  }

  /** Saving the session saves its workout anyway; this names it first. */
  function saveAsWorkout() {
    const name = saveTemplateName.trim()
    if (!name) return
    createTemplate.mutate({ name, sport_type: sportType, segments }, {
      onSuccess: t => { setWorkoutTemplateId(t.id); toast(`Saved as “${t.name}”`, 'success') },
      onError: e => toast(errorDetail(e, 'Could not save the workout'), 'error'),
    })
    setShowSaveTemplate(false)
    setSaveTemplateName('')
  }

  function buildPayload() {
    const data: Record<string, unknown> = {
      sport_type: sportType,
      description: description || undefined,
    }
    // Distance
    data.planned_distance_km = activeGoals.has('distance') ? fromInputDist(plannedDistanceKm, sportType) : null
    // Duration
    if (activeGoals.has('duration') && plannedDurationMins) {
      data.planned_duration_mins = parseFloat(plannedDurationMins)
    } else {
      data.planned_duration_mins = null
    }
    // Avg Pace
    const useSpeed = isSpeedSport(sportType)
    if (activeGoals.has('avg_pace') && targetAvgPace) {
      data.target_avg_pace = parsePaceInput(targetAvgPace, useSpeed)
    } else {
      data.target_avg_pace = null
    }
    // Pace Range
    if (activeGoals.has('pace_range')) {
      data.target_pace_min = targetPaceMin ? parsePaceInput(targetPaceMin, useSpeed) : null
      data.target_pace_max = targetPaceMax ? parsePaceInput(targetPaceMax, useSpeed) : null
    } else {
      data.target_pace_min = null
      data.target_pace_max = null
    }
    // HR Zone
    if (activeGoals.has('hr_zone') && targetHrZone) {
      data.target_hr_zone = parseInt(targetHrZone)
      data.target_zone_pct = targetZonePct ? parseFloat(targetZonePct) : 80
    } else {
      data.target_hr_zone = null
      data.target_zone_pct = null
    }
    // Structured Workout
    if (activeGoals.has('segments') && segments.length > 0) {
      data.segments = segments
      data.workout_template_id = workoutTemplateId
      // Auto-compute planned distance from segments for activity matching
      const totalKm = segments.reduce((sum, s) => {
        const dist = s.distance_km ?? 0
        const reps = s.repetitions ?? 1
        const recDist = s.recovery_distance_km ?? 0
        return sum + (dist * reps) + (recDist * Math.max(0, reps - 1))
      }, 0)
      if (totalKm > 0 && !data.planned_distance_km) {
        data.planned_distance_km = Math.round(totalKm * 10) / 10
      }
    } else {
      data.segments = null
      data.workout_template_id = null
    }
    return data
  }

  function addGoal(key: SessionGoalKey) {
    setActiveGoals(prev => new Set(prev).add(key))
    setShowGoalPicker(false)
    if (key === 'distance' && !plannedDistanceKm) setPlannedDistanceKm('10')
    if (key === 'duration' && !plannedDurationMins) setPlannedDurationMins('60')
    if (key === 'avg_pace' && !targetAvgPace) {
      setTargetAvgPace(getPaceUnit(sportType) === 'min/km' ? '5.5' : '28')
    }
    if (key === 'pace_range') {
      if (!targetPaceMin) setTargetPaceMin(getPaceUnit(sportType) === 'min/km' ? '5.0' : '25')
      if (!targetPaceMax) setTargetPaceMax(getPaceUnit(sportType) === 'min/km' ? '6.0' : '32')
    }
    if (key === 'hr_zone' && !targetHrZone) setTargetHrZone('2')
  }

  function removeGoal(key: SessionGoalKey) {
    setActiveGoals(prev => {
      const next = new Set(prev)
      next.delete(key)
      return next
    })
    // Clear values for removed goal
    if (key === 'distance') setPlannedDistanceKm('')
    if (key === 'duration') setPlannedDurationMins('')
    if (key === 'avg_pace') setTargetAvgPace('')
    if (key === 'pace_range') { setTargetPaceMin(''); setTargetPaceMax('') }
    if (key === 'hr_zone') { setTargetHrZone(''); setTargetZonePct('80') }
    if (key === 'segments') { setSegments([]); setWorkoutTemplateId(null); setShowTemplatePicker(false) }
  }

  const paceUnit = getPaceUnit(sportType)
  return (
    <Modal onClose={onClose} className="p-6 max-w-md max-h-[85vh]">
        <div className="flex items-center justify-between mb-5">
          <div>
            <div className="eyebrow mb-0.5">{format(parseISO(date), 'EEEE')}</div>
            <h3
              className={clsx('text-lg font-semibold tracking-tight tabular-nums', isLight ? 'text-gray-900' : 'text-gray-100')}
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
                      <div className={clsx('mt-1 p-2 border rounded-lg', isLight ? 'bg-gray-50 border-gray-200' : 'bg-surface-700/50 border-surface-600')}>
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
              value={sportType}
              onChange={setSportType}
              className="input w-full"
              isLight={isLight}
            />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Description</label>
            <textarea
              placeholder="e.g. Easy 10k recovery run"
              value={description}
              onChange={e => setDescription(e.target.value)}
              className="input w-full"
              rows={3}
            />
          </div>

          {/* Goal cards */}
          {activeGoals.size > 0 && (
            <div className="space-y-2">
              {activeGoals.has('distance') && (
                <GoalCard goal="distance" onRemove={() => removeGoal('distance')}>
                  <div className="flex items-center gap-2">
                    <input
                      type="text" inputMode="decimal" placeholder="10"
                      value={plannedDistanceKm} onChange={e => setPlannedDistanceKm(e.target.value)}
                      className="input w-24"
                    />
                    <span className="text-xs text-gray-500">{getDistUnit(sportType)}</span>
                  </div>
                </GoalCard>
              )}

              {activeGoals.has('duration') && (
                <GoalCard goal="duration" onRemove={() => removeGoal('duration')}>
                  <div className="flex items-center gap-2">
                    <input
                      type="text" inputMode="decimal" placeholder="60"
                      value={plannedDurationMins} onChange={e => setPlannedDurationMins(e.target.value)}
                      className="input w-24"
                    />
                    <span className="text-xs text-gray-500">min</span>
                  </div>
                </GoalCard>
              )}

              {activeGoals.has('avg_pace') && (
                <GoalCard goal="avg_pace" onRemove={() => removeGoal('avg_pace')}>
                  <div className="flex items-center gap-2">
                    <input
                      type="text" inputMode="decimal" placeholder={paceUnit === 'min/km' ? '5:10' : '28'}
                      value={targetAvgPace} onChange={e => setTargetAvgPace(e.target.value)}
                      className="input w-24"
                    />
                    <span className="text-xs text-gray-500">{paceUnit}</span>
                  </div>
                </GoalCard>
              )}

              {activeGoals.has('pace_range') && (
                <GoalCard goal="pace_range" onRemove={() => removeGoal('pace_range')}>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="eyebrow mb-1 block">
                        {paceUnit === 'min/km' ? 'Fastest' : 'Min speed'} ({paceUnit})
                      </label>
                      <input
                        type="text" inputMode="decimal" placeholder={paceUnit === 'min/km' ? '4:50' : '25'}
                        value={targetPaceMin} onChange={e => setTargetPaceMin(e.target.value)}
                        className="input w-full"
                      />
                    </div>
                    <div>
                      <label className="eyebrow mb-1 block">
                        {paceUnit === 'min/km' ? 'Slowest' : 'Max speed'} ({paceUnit})
                      </label>
                      <input
                        type="text" inputMode="decimal" placeholder={paceUnit === 'min/km' ? '5:20' : '32'}
                        value={targetPaceMax} onChange={e => setTargetPaceMax(e.target.value)}
                        className="input w-full"
                      />
                    </div>
                  </div>
                </GoalCard>
              )}

              {activeGoals.has('hr_zone') && (
                <GoalCard goal="hr_zone" onRemove={() => removeGoal('hr_zone')}>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="eyebrow mb-1 block">Zone</label>
                      <select value={targetHrZone} onChange={e => setTargetHrZone(e.target.value)} className="select w-full">
                        <option value="">Select</option>
                        {[1, 2, 3, 4, 5].map(z => <option key={z} value={z}>Zone {z}</option>)}
                      </select>
                    </div>
                    <div>
                      <label className="eyebrow mb-1 block">Target %</label>
                      <input
                        type="text" inputMode="decimal" placeholder="80"
                        value={targetZonePct} onChange={e => setTargetZonePct(e.target.value)}
                        className="input w-full"
                      />
                    </div>
                  </div>
                </GoalCard>
              )}

              {activeGoals.has('segments') && (
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
                              setSegments(t.segments || [])
                              setWorkoutTemplateId(t.id)
                              setShowTemplatePicker(false)
                            }}
                            className={clsx(
                              'w-full text-left text-xs rounded px-2 py-1.5 border transition-colors',
                              workoutTemplateId === t.id
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
                      <div className="text-[10px] text-gray-500 mt-1">No templates for {sportType}</div>
                    )}
                  </div>
                  <SegmentListBuilder
                    segments={segments}
                    onChange={setSegments}
                    paceUnit={paceUnit}
                    sportType={sportType}
                    compact
                  />
                  {/* Save as template */}
                  {segments.length > 0 && (
                    <div className="mt-2">
                      {!showSaveTemplate ? (
                        <button
                          onClick={() => { setShowSaveTemplate(true); setSaveTemplateName(description || '') }}
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
                  const isActive = activeGoals.has(key)
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
              onClick={() => {
                const payload = buildPayload()
                if (editingId) {
                  onUpdate(editingId, payload)
                  cancelEdit()
                } else {
                  onAdd(payload)
                  setDescription('')
                  setActiveGoals(new Set())
                  setPlannedDistanceKm('')
                  setPlannedDurationMins('')
                  setTargetAvgPace('')
                  setTargetPaceMin('')
                  setTargetPaceMax('')
                  setTargetHrZone('')
                  setTargetZonePct('80')
                  setShowGoalPicker(false)
                  setSegments([])
                  setWorkoutTemplateId(null)
                  setShowTemplatePicker(false)
                }
              }}
              className={clsx('flex-1 rounded py-2 text-sm font-medium transition-colors', isLight ? 'bg-gray-900 text-white hover:bg-gray-800' : 'bg-white/15 text-gray-100 border border-white/20 hover:bg-white/20')}
            >
              {editingId ? 'Save Changes' : 'Add'}
            </button>
            {editingId ? (
              <button onClick={cancelEdit} className={clsx('flex-1 rounded py-2 text-sm text-gray-400', isLight ? 'bg-gray-100 hover:text-gray-700' : 'bg-surface-700 hover:text-gray-200')}>
                Discard Changes
              </button>
            ) : (
              <button onClick={onClose} className={clsx('flex-1 rounded py-2 text-sm text-gray-400', isLight ? 'bg-gray-100 hover:text-gray-700' : 'bg-surface-700 hover:text-gray-200')}>
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
