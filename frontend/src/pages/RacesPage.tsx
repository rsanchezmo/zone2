import { useState } from 'react'
import { Link } from 'react-router-dom'
import { format, parseISO, differenceInCalendarDays } from 'date-fns'
import {
  useRaceEvents, useCreateRaceEvent, useUpdateRaceEvent, useDeleteRaceEvent,
  useActivitiesOnDates, type Activity, type RaceEvent, type RaceEventInput,
} from '../api/hooks'
import { getSportColor } from '../constants/sportColors'
import { getPaceUnit, formatPace, isSpeedSport, formatDistExact } from '../utils/formatSpeed'
import { localDateStr } from '../utils/dates'
import RaceEventForm from '../components/shared/RaceEventForm'
import RowActions from '../components/shared/RowActions'
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
  // The race being edited; null while adding one
  const [editing, setEditing] = useState<RaceEvent | null>(null)
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null)

  function closeForm() {
    setShowForm(false)
    setEditing(null)
  }

  function startEdit(r: RaceEvent) {
    setEditing(r)
    setShowForm(true)
  }

  function handleSubmit(race: RaceEventInput) {
    if (editing) {
      updateRace.mutate({ id: editing.id, ...race }, {
        onSuccess: () => { toast('Race updated', 'success'); closeForm() },
      })
    } else {
      createRace.mutate(race, {
        onSuccess: () => { toast('Race created', 'success'); closeForm() },
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
          onClick={() => { setEditing(null); setShowForm(true) }}
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
              {editing ? 'Edit race' : 'New race'}
            </div>
            <button onClick={closeForm} className={clsx('text-[11px] uppercase tracking-[0.15em]', isLight ? 'text-gray-400 hover:text-gray-600' : 'text-gray-500 hover:text-gray-200')}>Close</button>
          </div>
          <RaceEventForm
            key={editing?.id ?? 'new'}
            initial={editing}
            date={format(today, 'yyyy-MM-dd')}
            accent={RACE_ACCENT}
            onSubmit={handleSubmit}
            onCancel={closeForm}
          />
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
                              <span>{formatDistExact(r.distance_km, r.sport_type)}</span>
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
                              <span>{formatDistExact(r.distance_km, r.sport_type)}</span>
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
                onClick={() => { setEditing(null); setShowForm(true) }}
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
