import { useState } from 'react'
import { Link } from 'react-router-dom'
import { format, parseISO, differenceInCalendarDays } from 'date-fns'
import {
  useRaceEvents, useCreateRaceEvent, useUpdateRaceEvent, useDeleteRaceEvent,
  useActivitiesOnDates, type Activity, type RaceEvent,
} from '../api/hooks'
import { getSportColor } from '../constants/sportColors'
import { getPaceUnit, getDistUnit, getSportCategory, formatPace, isSpeedSport, parsePaceInput } from '../utils/formatSpeed'
import { localDateStr } from '../utils/dates'
import SportTypeCombobox from '../components/shared/SportTypeCombobox'
import DatePicker from '../components/shared/DatePicker'
import { FlagIcon, CheckIcon, ExternalLinkIcon } from '../components/icons'
import clsx from 'clsx'
import { useTheme } from '../hooks/useTheme'
import { useToast } from '../hooks/useToast'

const RACE_ACCENT = '#eab308' // amber — race identity across the page

export default function RacesPage() {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const { toast } = useToast()

  const { data: allRaces, isLoading } = useRaceEvents()
  const createRace = useCreateRaceEvent()
  const updateRace = useUpdateRaceEvent()
  const deleteRace = useDeleteRaceEvent()

  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [name, setName] = useState('')
  const [date, setDate] = useState('')
  const [sportType, setSportType] = useState('Run')
  const [distanceKm, setDistanceKm] = useState('')
  const [targetPace, setTargetPace] = useState('')
  const [description, setDescription] = useState('')
  const [location, setLocation] = useState('')
  const [url, setUrl] = useState('')
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null)

  function resetForm() {
    setShowForm(false)
    setEditingId(null)
    setName(''); setDate(''); setSportType('Run'); setDistanceKm('')
    setTargetPace(''); setDescription(''); setLocation(''); setUrl('')
  }

  function startEdit(r: RaceEvent) {
    setEditingId(r.id)
    setName(r.name)
    setDate(r.date)
    setSportType(r.sport_type)
    // User enters meters for swimming, km for others — convert km → m for swim display
    const displayDist = r.distance_km != null
      ? (getSportCategory(r.sport_type) === 'swimming'
          ? r.distance_km * 1000
          : r.distance_km)
      : ''
    setDistanceKm(displayDist === '' ? '' : String(displayDist))
    setTargetPace(r.target_pace != null
      ? formatPace(r.target_pace, isSpeedSport(r.sport_type))
      : '')
    setDescription(r.description || '')
    setLocation(r.location || '')
    setUrl(r.url || '')
    setShowForm(true)
  }

  function handleSubmit() {
    if (!name.trim() || !date) return
    // User enters meters for swimming, km for others — always store as km
    const parsedDist = distanceKm ? parseFloat(distanceKm) : null
    const distanceKmPayload = parsedDist !== null
      ? (getSportCategory(sportType) === 'swimming' ? parsedDist / 1000 : parsedDist)
      : null
    const payload: Record<string, unknown> = {
      name: name.trim(),
      date,
      sport_type: sportType,
      distance_km: distanceKmPayload,
      target_pace: targetPace ? parsePaceInput(targetPace, isSpeedSport(sportType)) : null,
      description: description || null,
      location: location || null,
      url: url || null,
    }
    if (editingId) {
      updateRace.mutate({ id: editingId, ...payload }, {
        onSuccess: () => { toast('Race updated', 'success'); resetForm() },
      })
    } else {
      createRace.mutate(payload, {
        onSuccess: () => { toast('Race created', 'success'); resetForm() },
      })
    }
  }

  const today = new Date()
  const upcoming = (allRaces || []).filter(r => r.date >= format(today, 'yyyy-MM-dd'))
  const past = (allRaces || []).filter(r => r.date < format(today, 'yyyy-MM-dd')).reverse()

  // Fetch only the activities on past race days, for "View activity" matching.
  const pastDates = past.map(r => r.date)
  const { data: activitiesData } = useActivitiesOnDates(pastDates)

  const activityByDate: Record<string, Activity[]> = {}
  if (activitiesData?.items) {
    for (const a of activitiesData.items) {
      const ds = a.start_date_local ? localDateStr(a.start_date_local) : null
      if (ds) {
        if (!activityByDate[ds]) activityByDate[ds] = []
        activityByDate[ds].push(a)
      }
    }
  }

  const paceUnit = getPaceUnit(sportType)

  const panelClass = clsx(
    'panel',
    isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600',
  )

  return (
    <div className="max-w-4xl mx-auto space-y-10 pb-12">
      {/* ── Breadcrumb header ─────────────────────────── */}
      <header className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-baseline gap-2">
          <span className="eyebrow">Races</span>
        </div>
        <button
          onClick={() => { resetForm(); setShowForm(true); setDate(format(today, 'yyyy-MM-dd')) }}
          className="btn"
          style={{
            borderColor: `${RACE_ACCENT}40`,
            color: RACE_ACCENT,
            backgroundColor: `${RACE_ACCENT}15`,
          }}
        >
          + Add race
        </button>
      </header>

      {/* ── Create / Edit form ────────────────────────── */}
      {showForm && (
        <section className={clsx(panelClass, 'hero-brackets p-5 md:p-6 space-y-4')} style={{ ['--card-accent' as string]: RACE_ACCENT }}>
          <div className="flex items-center justify-between">
            <div className="eyebrow flex items-center gap-2" style={{ color: RACE_ACCENT }}>
              <FlagIcon size={11} />
              {editingId ? 'Edit race' : 'New race'}
            </div>
            <button onClick={resetForm} className={clsx('text-[11px] uppercase tracking-[0.15em]', isLight ? 'text-gray-400 hover:text-gray-600' : 'text-gray-500 hover:text-gray-200')}>Close</button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="md:col-span-2">
              <label className="eyebrow mb-1.5 block">Race name *</label>
              <input
                type="text" placeholder="e.g. Berlin Marathon"
                value={name} onChange={e => setName(e.target.value)}
                className="input w-full"
                autoFocus
              />
            </div>
            <div>
              <label className="eyebrow mb-1.5 block">Date *</label>
              <DatePicker
                value={date}
                onChange={setDate}
                inputClassName="w-full"
              />
            </div>
            <div>
              <label className="eyebrow mb-1.5 block">Sport</label>
              <SportTypeCombobox
                value={sportType}
                onChange={setSportType}
                className="input w-full"
                isLight={isLight}
              />
            </div>
            <div>
              <label className="eyebrow mb-1.5 block">Distance ({getDistUnit(sportType)})</label>
              <input
                type="text" inputMode="decimal"
                placeholder={getSportCategory(sportType) === 'swimming' ? '1500' : '42.195'}
                value={distanceKm} onChange={e => setDistanceKm(e.target.value)}
                className="input w-full"
              />
            </div>
            <div>
              <label className="eyebrow mb-1.5 block">Target pace ({paceUnit})</label>
              <input
                type="text" inputMode="decimal" placeholder={paceUnit === 'min/km' ? '5:00' : '30'}
                value={targetPace} onChange={e => setTargetPace(e.target.value)}
                className="input w-full"
              />
            </div>
            <div>
              <label className="eyebrow mb-1.5 block">Location</label>
              <input
                type="text" placeholder="Berlin, Germany"
                value={location} onChange={e => setLocation(e.target.value)}
                className="input w-full"
              />
            </div>
            <div className="md:col-span-2">
              <label className="eyebrow mb-1.5 block">URL</label>
              <input
                type="text" placeholder="https://…"
                value={url} onChange={e => setUrl(e.target.value)}
                className="input w-full"
              />
            </div>
            <div className="md:col-span-2">
              <label className="eyebrow mb-1.5 block">Notes</label>
              <textarea
                placeholder="Goals, strategy, notes…"
                value={description} onChange={e => setDescription(e.target.value)}
                className="input w-full"
                rows={3}
              />
            </div>
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleSubmit}
              disabled={!name.trim() || !date}
              className="btn flex-1 !text-sm !py-2"
              style={{
                borderColor: `${RACE_ACCENT}50`,
                color: RACE_ACCENT,
                backgroundColor: `${RACE_ACCENT}15`,
              }}
            >
              {editingId ? 'Save changes' : 'Create race'}
            </button>
            <button onClick={resetForm} className="btn !text-sm !py-2 px-6">Cancel</button>
          </div>
        </section>
      )}

      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className={clsx(panelClass, 'p-5 h-24 animate-pulse')} />
          ))}
        </div>
      ) : (
        <>
          {/* ── Upcoming ─────────────────────────────── */}
          {upcoming.length > 0 && (
            <section>
              <div className="section-head mb-4"><span className="eyebrow" style={{ color: RACE_ACCENT }}>Upcoming</span></div>
              <div className="space-y-3 stagger-children">
                {upcoming.map(r => {
                  const daysUntil = differenceInCalendarDays(parseISO(r.date), today)
                  const sportColor = getSportColor(r.sport_type)
                  const isConfirming = confirmDeleteId === r.id
                  return (
                    <article
                      key={r.id}
                      className={clsx(panelClass, 'p-4 transition-colors')}
                      style={{ borderLeftWidth: 2, borderLeftColor: RACE_ACCENT }}
                    >
                      <div className="flex items-start gap-4">
                        {/* Countdown block */}
                        <div
                          className="flex flex-col items-center justify-center rounded-lg px-3 py-2 shrink-0 min-w-[68px] border"
                          style={{
                            backgroundColor: `${RACE_ACCENT}10`,
                            borderColor: `${RACE_ACCENT}30`,
                          }}
                        >
                          {daysUntil === 0 ? (
                            <div
                              className="text-sm font-mono font-bold leading-none uppercase tracking-[0.1em]"
                              style={{ color: RACE_ACCENT }}
                            >
                              Today
                            </div>
                          ) : (
                            <>
                              <div
                                className="text-2xl font-mono tabular-nums font-bold leading-none"
                                style={{ color: RACE_ACCENT, letterSpacing: '-0.02em' }}
                              >
                                {daysUntil}
                              </div>
                              <div className="eyebrow mt-1 text-[9px]" style={{ color: `${RACE_ACCENT}cc` }}>
                                day{daysUntil !== 1 ? 's' : ''}
                              </div>
                            </>
                          )}
                        </div>

                        {/* Details */}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap mb-1">
                            <span className={clsx('text-base font-semibold tracking-tight', isLight ? 'text-gray-900' : 'text-gray-100')}>{r.name}</span>
                            <span
                              className="inline-flex items-center gap-1 text-[10px] uppercase tracking-[0.15em] px-2 py-0.5 rounded-full border font-semibold"
                              style={{ color: sportColor, borderColor: `${sportColor}40`, backgroundColor: `${sportColor}15` }}
                            >
                              <span className="w-1 h-1 rounded-full" style={{ backgroundColor: sportColor }} aria-hidden="true" />
                              {r.sport_type}
                            </span>
                          </div>
                          <div className="flex items-center gap-3 text-[11px] text-gray-500 flex-wrap font-mono tabular-nums">
                            <span>{format(parseISO(r.date), 'EEE · MMM d, yyyy')}</span>
                            {r.distance_km != null && (
                              <span>
                                {getSportCategory(r.sport_type) === 'swimming'
                                  ? `${Math.round(r.distance_km * 1000)} m`
                                  : `${r.distance_km} km`}
                              </span>
                            )}
                            {r.target_pace != null && <span>{formatPace(r.target_pace, isSpeedSport(r.sport_type))} {getPaceUnit(r.sport_type)}</span>}
                            {r.location != null && <span className="normal-case">{r.location}</span>}
                          </div>
                          {r.description != null && (
                            <div className={clsx('text-xs mt-2 whitespace-pre-line', isLight ? 'text-gray-500' : 'text-gray-400')}>{r.description}</div>
                          )}
                          {r.url != null && (
                            <a
                              href={r.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-[11px] mt-1.5 inline-flex items-center gap-1"
                              style={{ color: RACE_ACCENT }}
                              onClick={e => e.stopPropagation()}
                            >
                              Race website <ExternalLinkIcon size={10} />
                            </a>
                          )}
                        </div>

                        {/* Actions */}
                        <RowActions
                          isConfirming={isConfirming}
                          onEdit={() => startEdit(r)}
                          onConfirmDelete={() => { deleteRace.mutate(r.id, { onSuccess: () => toast('Race deleted', 'success') }); setConfirmDeleteId(null) }}
                          onAskDelete={() => setConfirmDeleteId(r.id)}
                          onCancelDelete={() => setConfirmDeleteId(null)}
                        />
                      </div>
                    </article>
                  )
                })}
              </div>
            </section>
          )}

          {/* ── Past ───────────────────────────────── */}
          {past.length > 0 && (
            <section>
              <div className="section-head mb-4"><span className="eyebrow">Past races</span></div>
              <div className="space-y-2 stagger-children">
                {past.map(r => {
                  const sportColor = getSportColor(r.sport_type)
                  const dayActivities = activityByDate[r.date] || []
                  // Among same-sport activities that day, prefer the one closest to
                  // the race distance (falls back to the longest) so warm-ups don't win.
                  const raceKm = r.distance_km
                  const matchedActivity = dayActivities
                    .filter(a => a.sport_type === r.sport_type)
                    .sort((a, b) => raceKm != null
                      ? Math.abs((a.distance_km ?? 0) - raceKm) - Math.abs((b.distance_km ?? 0) - raceKm)
                      : (b.distance_km ?? 0) - (a.distance_km ?? 0))[0]
                  const isConfirming = confirmDeleteId === r.id
                  return (
                    <article key={r.id} className={clsx(panelClass, 'p-4 transition-colors')}>
                      <div className="flex items-center gap-4">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap mb-0.5">
                            <span className={clsx('text-sm font-semibold tracking-tight', isLight ? 'text-gray-900' : 'text-gray-100')}>{r.name}</span>
                            <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: sportColor }} aria-hidden="true" />
                            <span className="text-[10px] uppercase tracking-[0.15em] text-gray-500">{r.sport_type}</span>
                            {matchedActivity && (
                              <Link
                                to={`/activities/${matchedActivity.id}`}
                                className="action-link text-[10px] uppercase tracking-[0.15em] text-green-400 hover:text-green-300"
                              >
                                <CheckIcon size={10} />
                                View activity
                              </Link>
                            )}
                          </div>
                          <div className="flex items-center gap-3 text-[11px] text-gray-500 flex-wrap font-mono tabular-nums">
                            <span>{format(parseISO(r.date), 'MMM d, yyyy')}</span>
                            {r.distance_km != null && (
                              <span>
                                {getSportCategory(r.sport_type) === 'swimming'
                                  ? `${Math.round(r.distance_km * 1000)} m`
                                  : `${r.distance_km} km`}
                              </span>
                            )}
                            {r.target_pace != null && <span>{formatPace(r.target_pace, isSpeedSport(r.sport_type))} {getPaceUnit(r.sport_type)}</span>}
                            {r.location != null && <span className="normal-case">{r.location}</span>}
                            {r.url != null && (
                              <a href={r.url} target="_blank" rel="noopener noreferrer" className="action-link" style={{ color: RACE_ACCENT }} onClick={e => e.stopPropagation()}>
                                Website <ExternalLinkIcon size={9} />
                              </a>
                            )}
                          </div>
                          {r.description != null && (
                            <div className={clsx('text-xs mt-1.5 whitespace-pre-line', isLight ? 'text-gray-400' : 'text-gray-500')}>{r.description}</div>
                          )}
                        </div>
                        <RowActions
                          isConfirming={isConfirming}
                          onEdit={() => startEdit(r)}
                          onConfirmDelete={() => { deleteRace.mutate(r.id, { onSuccess: () => toast('Race deleted', 'success') }); setConfirmDeleteId(null) }}
                          onAskDelete={() => setConfirmDeleteId(r.id)}
                          onCancelDelete={() => setConfirmDeleteId(null)}
                        />
                      </div>
                    </article>
                  )
                })}
              </div>
            </section>
          )}

          {upcoming.length === 0 && past.length === 0 && !showForm && (
            <div className={clsx(panelClass, 'p-10 text-center flex flex-col items-center gap-3')}>
              <div style={{ color: RACE_ACCENT }}><FlagIcon size={32} /></div>
              <div className={clsx('text-sm', isLight ? 'text-gray-500' : 'text-gray-500')}>No races yet</div>
              <button
                onClick={() => { resetForm(); setShowForm(true); setDate(format(today, 'yyyy-MM-dd')) }}
                className="text-[11px] uppercase tracking-[0.15em] font-semibold"
                style={{ color: RACE_ACCENT }}
              >
                Add your first race →
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}

// ────────────────────────────────────────────────────────
// RowActions — edit/delete controls (with confirm-delete state)
// ────────────────────────────────────────────────────────

function RowActions({
  isConfirming,
  onEdit,
  onConfirmDelete,
  onAskDelete,
  onCancelDelete,
}: {
  isConfirming: boolean
  onEdit: () => void
  onConfirmDelete: () => void
  onAskDelete: () => void
  onCancelDelete: () => void
}) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const actionBase = 'action-link text-[11px] uppercase tracking-[0.15em]'
  const actionClass = clsx(actionBase, isLight ? 'text-gray-400 hover:text-gray-700' : 'text-gray-500 hover:text-gray-200')
  return (
    <div className="flex items-center gap-2 shrink-0">
      {isConfirming ? (
        <>
          <span className="text-[11px] uppercase tracking-[0.15em] text-red-400">Delete?</span>
          <button onClick={onConfirmDelete} className={clsx(actionBase, 'text-red-400 hover:text-red-300 font-bold')}>Yes</button>
          <button onClick={onCancelDelete} className={actionClass}>No</button>
        </>
      ) : (
        <>
          <button onClick={onEdit} className={actionClass}>Edit</button>
          <button onClick={onAskDelete} className={clsx(actionBase, 'text-red-400/80 hover:text-red-300')}>Delete</button>
        </>
      )}
    </div>
  )
}
