import { useState } from 'react'
import { Link } from 'react-router-dom'
import { format, parseISO, differenceInDays } from 'date-fns'
import {
  useRaceEvents, useCreateRaceEvent, useUpdateRaceEvent, useDeleteRaceEvent,
  useActivitiesByDateRange,
} from '../api/hooks'
import { getSportColor } from '../constants/sportColors'
import { getPaceUnit, getDistUnit, getSportCategory, formatPace, isSpeedSport, parsePaceInput } from '../utils/formatSpeed'
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

  function startEdit(r: Record<string, unknown>) {
    setEditingId(r.id as number)
    setName(r.name as string)
    setDate(r.date as string)
    setSportType(r.sport_type as string)
    // User enters meters for swimming, km for others — convert km → m for swim display
    const displayDist = r.distance_km != null
      ? (getSportCategory(r.sport_type as string) === 'swimming'
          ? (r.distance_km as number) * 1000
          : (r.distance_km as number))
      : ''
    setDistanceKm(displayDist === '' ? '' : String(displayDist))
    setTargetPace(r.target_pace != null
      ? formatPace(r.target_pace as number, isSpeedSport(r.sport_type as string))
      : '')
    setDescription((r.description as string) || '')
    setLocation((r.location as string) || '')
    setUrl((r.url as string) || '')
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
  const upcoming = (allRaces || []).filter((r: Record<string, unknown>) => (r.date as string) >= format(today, 'yyyy-MM-dd'))
  const past = (allRaces || []).filter((r: Record<string, unknown>) => (r.date as string) < format(today, 'yyyy-MM-dd')).reverse()

  // Fetch activities only across the span of past races, for "View activity" matching.
  const pastDates = past.map((r: Record<string, unknown>) => r.date as string)
  const dateFrom = pastDates.length > 0 ? pastDates[pastDates.length - 1] : undefined
  const dateTo = pastDates.length > 0 ? pastDates[0] : undefined
  const { data: activitiesData } = useActivitiesByDateRange(dateFrom, dateTo)

  const activityByDate: Record<string, Array<{ id: number; name: string; sport_type: string; distance_km: number }>> = {}
  if (activitiesData?.items) {
    for (const a of activitiesData.items) {
      const ds = a.start_date_local ? format(new Date(a.start_date_local), 'yyyy-MM-dd') : null
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
                {upcoming.map((r: Record<string, unknown>) => {
                  const daysUntil = differenceInDays(parseISO(r.date as string), today) + 1
                  const sportColor = getSportColor(r.sport_type as string)
                  const isConfirming = confirmDeleteId === (r.id as number)
                  return (
                    <article
                      key={r.id as number}
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
                          <div
                            className="text-2xl font-mono tabular-nums font-bold leading-none"
                            style={{ color: RACE_ACCENT, letterSpacing: '-0.02em' }}
                          >
                            {daysUntil}
                          </div>
                          <div className="eyebrow mt-1 text-[9px]" style={{ color: `${RACE_ACCENT}cc` }}>
                            day{daysUntil !== 1 ? 's' : ''}
                          </div>
                        </div>

                        {/* Details */}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap mb-1">
                            <span className={clsx('text-base font-semibold tracking-tight', isLight ? 'text-gray-900' : 'text-gray-100')}>{r.name as string}</span>
                            <span
                              className="inline-flex items-center gap-1 text-[10px] uppercase tracking-[0.15em] px-2 py-0.5 rounded-full border font-semibold"
                              style={{ color: sportColor, borderColor: `${sportColor}40`, backgroundColor: `${sportColor}15` }}
                            >
                              <span className="w-1 h-1 rounded-full" style={{ backgroundColor: sportColor }} aria-hidden="true" />
                              {r.sport_type as string}
                            </span>
                          </div>
                          <div className="flex items-center gap-3 text-[11px] text-gray-500 flex-wrap font-mono tabular-nums">
                            <span>{format(parseISO(r.date as string), 'EEE · MMM d, yyyy')}</span>
                            {r.distance_km != null && (
                              <span>
                                {getSportCategory(r.sport_type as string) === 'swimming'
                                  ? `${Math.round((r.distance_km as number) * 1000)} m`
                                  : `${r.distance_km as number} km`}
                              </span>
                            )}
                            {r.target_pace != null && <span>{formatPace(r.target_pace as number, isSpeedSport(r.sport_type as string))} {getPaceUnit(r.sport_type as string)}</span>}
                            {r.location != null && <span className="normal-case">{r.location as string}</span>}
                          </div>
                          {r.description != null && (
                            <div className={clsx('text-xs mt-2 whitespace-pre-line', isLight ? 'text-gray-500' : 'text-gray-400')}>{r.description as string}</div>
                          )}
                          {r.url != null && (
                            <a
                              href={r.url as string}
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
                          onConfirmDelete={() => { deleteRace.mutate(r.id as number, { onSuccess: () => toast('Race deleted', 'success') }); setConfirmDeleteId(null) }}
                          onAskDelete={() => setConfirmDeleteId(r.id as number)}
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
                {past.map((r: Record<string, unknown>) => {
                  const sportColor = getSportColor(r.sport_type as string)
                  const dayActivities = activityByDate[r.date as string] || []
                  const matchedActivity = dayActivities.find(a => a.sport_type === r.sport_type)
                  const isConfirming = confirmDeleteId === (r.id as number)
                  return (
                    <article key={r.id as number} className={clsx(panelClass, 'p-4 transition-colors')}>
                      <div className="flex items-center gap-4">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap mb-0.5">
                            <span className={clsx('text-sm font-semibold tracking-tight', isLight ? 'text-gray-900' : 'text-gray-100')}>{r.name as string}</span>
                            <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: sportColor }} aria-hidden="true" />
                            <span className="text-[10px] uppercase tracking-[0.15em] text-gray-500">{r.sport_type as string}</span>
                            {matchedActivity && (
                              <Link
                                to={`/activities/${matchedActivity.id}`}
                                className="text-[10px] uppercase tracking-[0.15em] text-green-400 hover:text-green-300 inline-flex items-center gap-1"
                              >
                                <CheckIcon size={10} />
                                View activity
                              </Link>
                            )}
                          </div>
                          <div className="flex items-center gap-3 text-[11px] text-gray-500 flex-wrap font-mono tabular-nums">
                            <span>{format(parseISO(r.date as string), 'MMM d, yyyy')}</span>
                            {r.distance_km != null && (
                              <span>
                                {getSportCategory(r.sport_type as string) === 'swimming'
                                  ? `${Math.round((r.distance_km as number) * 1000)} m`
                                  : `${r.distance_km as number} km`}
                              </span>
                            )}
                            {r.target_pace != null && <span>{formatPace(r.target_pace as number, isSpeedSport(r.sport_type as string))} {getPaceUnit(r.sport_type as string)}</span>}
                            {r.location != null && <span className="normal-case">{r.location as string}</span>}
                            {r.url != null && (
                              <a href={r.url as string} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1" style={{ color: RACE_ACCENT }} onClick={e => e.stopPropagation()}>
                                Website <ExternalLinkIcon size={9} />
                              </a>
                            )}
                          </div>
                          {r.description != null && (
                            <div className={clsx('text-xs mt-1.5 whitespace-pre-line', isLight ? 'text-gray-400' : 'text-gray-500')}>{r.description as string}</div>
                          )}
                        </div>
                        <RowActions
                          isConfirming={isConfirming}
                          onEdit={() => startEdit(r)}
                          onConfirmDelete={() => { deleteRace.mutate(r.id as number, { onSuccess: () => toast('Race deleted', 'success') }); setConfirmDeleteId(null) }}
                          onAskDelete={() => setConfirmDeleteId(r.id as number)}
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
  const actionClass = clsx('text-[11px] uppercase tracking-[0.15em]', isLight ? 'text-gray-400 hover:text-gray-700' : 'text-gray-500 hover:text-gray-200')
  return (
    <div className="flex items-center gap-2 shrink-0">
      {isConfirming ? (
        <>
          <span className="text-[11px] uppercase tracking-[0.15em] text-red-400">Delete?</span>
          <button onClick={onConfirmDelete} className="text-red-400 hover:text-red-300 text-[11px] uppercase tracking-[0.15em] font-bold">Yes</button>
          <button onClick={onCancelDelete} className={actionClass}>No</button>
        </>
      ) : (
        <>
          <button onClick={onEdit} className={actionClass}>Edit</button>
          <button onClick={onAskDelete} className="text-red-400/80 hover:text-red-300 text-[11px] uppercase tracking-[0.15em]">Delete</button>
        </>
      )}
    </div>
  )
}
