import { useState } from 'react'
import { Link } from 'react-router-dom'
import { format, parseISO, differenceInDays } from 'date-fns'
import {
  useRaceEvents, useUpcomingRaces, useCreateRaceEvent, useUpdateRaceEvent, useDeleteRaceEvent,
  useActivitiesByDateRange,
} from '../api/hooks'
import { getSportColor } from '../constants/sportColors'
import { getPaceUnit } from '../utils/formatSpeed'
import SportTypeCombobox from '../components/shared/SportTypeCombobox'
import clsx from 'clsx'
import { useTheme } from '../hooks/useTheme'
import { useToast } from '../hooks/useToast'

export default function RacesPage() {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const { toast } = useToast()
  const [filterYear, setFilterYear] = useState<number>(new Date().getFullYear())

  const { data: allRaces, isLoading } = useRaceEvents(filterYear)
  const { data: upcomingRaces } = useUpcomingRaces()
  const createRace = useCreateRaceEvent()
  const updateRace = useUpdateRaceEvent()
  const deleteRace = useDeleteRaceEvent()

  // For linking past races to activities — fetch the year's activities
  const dateFrom = `${filterYear}-01-01`
  const dateTo = `${filterYear}-12-31`
  const { data: activitiesData } = useActivitiesByDateRange(dateFrom, dateTo)

  // Form state
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
    setDistanceKm(r.distance_km != null ? String(r.distance_km) : '')
    setTargetPace(r.target_pace != null ? String(r.target_pace) : '')
    setDescription((r.description as string) || '')
    setLocation((r.location as string) || '')
    setUrl((r.url as string) || '')
    setShowForm(true)
  }

  function handleSubmit() {
    if (!name.trim() || !date) return
    const payload: Record<string, unknown> = {
      name: name.trim(),
      date,
      sport_type: sportType,
      distance_km: distanceKm ? parseFloat(distanceKm) : null,
      target_pace: targetPace ? parseFloat(targetPace) : null,
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

  // Build activity map by date for linking past races
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

  const today = new Date()
  const upcoming = (allRaces || []).filter((r: Record<string, unknown>) => (r.date as string) >= format(today, 'yyyy-MM-dd'))
  const past = (allRaces || []).filter((r: Record<string, unknown>) => (r.date as string) < format(today, 'yyyy-MM-dd')).reverse()

  const paceUnit = getPaceUnit(sportType)

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="page-title">Races</h2>
        <div className="flex items-center gap-2">
          <select
            value={filterYear}
            onChange={e => setFilterYear(Number(e.target.value))}
            className={clsx('border rounded-lg px-3 py-1.5 text-sm', isLight ? 'bg-white border-gray-200 text-gray-700' : 'bg-surface-700 border-surface-600')}
          >
            {Array.from({ length: 5 }, (_, i) => new Date().getFullYear() + 1 - i).map(y => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
          <button
            onClick={() => { resetForm(); setShowForm(true); setDate(format(today, 'yyyy-MM-dd')) }}
            className={clsx('rounded-lg px-4 py-1.5 text-sm font-medium transition-colors', 'bg-amber-500/20 text-amber-500 border border-amber-500/30 hover:bg-amber-500/30')}
          >
            + Add Race
          </button>
        </div>
      </div>

      {/* Create / Edit form */}
      {showForm && (
        <div className={clsx('rounded-xl p-5 border', isLight ? 'bg-white border-amber-200' : 'bg-surface-800 border-amber-500/20')}>
          <div className="flex items-center justify-between mb-4">
            <div className="text-sm font-semibold flex items-center gap-2 text-amber-500">
              <span>&#9873;</span> {editingId ? 'Edit Race' : 'New Race'}
            </div>
            <button onClick={resetForm} className={clsx('text-gray-400 hover:text-gray-200 text-xs')}>Cancel</button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="md:col-span-2">
              <label className="text-xs text-gray-500 mb-1 block">Race Name *</label>
              <input
                type="text" placeholder="e.g. Berlin Marathon"
                value={name} onChange={e => setName(e.target.value)}
                className={clsx('w-full border rounded-lg px-3 py-2.5 text-sm', isLight ? 'bg-white border-gray-200 text-gray-700' : 'bg-surface-700 border-surface-600')}
                autoFocus
              />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Date *</label>
              <input
                type="date"
                value={date} onChange={e => setDate(e.target.value)}
                className={clsx('w-full border rounded-lg px-3 py-2.5 text-sm', isLight ? 'bg-white border-gray-200 text-gray-700' : 'bg-surface-700 border-surface-600')}
              />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Sport</label>
              <SportTypeCombobox
                value={sportType}
                onChange={setSportType}
                className={clsx('w-full border rounded-lg px-3 py-2.5 text-sm', isLight ? 'bg-white border-gray-200 text-gray-700' : 'bg-surface-700 border-surface-600')}
                isLight={isLight}
              />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Distance (km)</label>
              <input
                type="text" inputMode="decimal" placeholder="42.195"
                value={distanceKm} onChange={e => setDistanceKm(e.target.value)}
                className={clsx('w-full border rounded-lg px-3 py-2.5 text-sm', isLight ? 'bg-white border-gray-200 text-gray-700' : 'bg-surface-700 border-surface-600')}
              />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Target Pace ({paceUnit})</label>
              <input
                type="text" inputMode="decimal" placeholder={paceUnit === 'min/km' ? '5:00' : '30'}
                value={targetPace} onChange={e => setTargetPace(e.target.value)}
                className={clsx('w-full border rounded-lg px-3 py-2.5 text-sm', isLight ? 'bg-white border-gray-200 text-gray-700' : 'bg-surface-700 border-surface-600')}
              />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Location</label>
              <input
                type="text" placeholder="Berlin, Germany"
                value={location} onChange={e => setLocation(e.target.value)}
                className={clsx('w-full border rounded-lg px-3 py-2.5 text-sm', isLight ? 'bg-white border-gray-200 text-gray-700' : 'bg-surface-700 border-surface-600')}
              />
            </div>
            <div className="md:col-span-2">
              <label className="text-xs text-gray-500 mb-1 block">URL</label>
              <input
                type="text" placeholder="https://..."
                value={url} onChange={e => setUrl(e.target.value)}
                className={clsx('w-full border rounded-lg px-3 py-2.5 text-sm', isLight ? 'bg-white border-gray-200 text-gray-700' : 'bg-surface-700 border-surface-600')}
              />
            </div>
            <div className="md:col-span-2">
              <label className="text-xs text-gray-500 mb-1 block">Notes</label>
              <textarea
                placeholder="Goals, strategy, notes..."
                value={description} onChange={e => setDescription(e.target.value)}
                className={clsx('w-full border rounded-lg px-3 py-2.5 text-sm', isLight ? 'bg-white border-gray-200 text-gray-700' : 'bg-surface-700 border-surface-600')}
                rows={3}
              />
            </div>
          </div>
          <div className="flex gap-2 mt-4">
            <button
              onClick={handleSubmit}
              disabled={!name.trim() || !date}
              className={clsx(
                'flex-1 rounded-lg py-2.5 text-sm font-medium transition-colors',
                'bg-amber-500/20 text-amber-500 border border-amber-500/30 hover:bg-amber-500/30',
                'disabled:opacity-40 disabled:cursor-not-allowed',
              )}
            >
              {editingId ? 'Save Changes' : 'Create Race'}
            </button>
            <button onClick={resetForm} className={clsx('px-6 rounded-lg py-2.5 text-sm text-gray-400', isLight ? 'bg-gray-100 hover:text-gray-700' : 'bg-surface-700 hover:text-gray-200')}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className={clsx('rounded-xl p-5 h-24 border animate-pulse', isLight ? 'bg-gray-100 border-gray-200' : 'bg-surface-800 border-surface-600')} />
          ))}
        </div>
      ) : (
        <>
          {/* Upcoming Races */}
          {upcoming.length > 0 && (
            <section>
              <div className="text-xs text-gray-500 uppercase mb-3">Upcoming</div>
              <div className="space-y-3">
                {upcoming.map((r: Record<string, unknown>) => {
                  const daysUntil = differenceInDays(parseISO(r.date as string), today) + 1
                  const sportColor = getSportColor(r.sport_type as string)
                  const isConfirming = confirmDeleteId === (r.id as number)
                  return (
                    <div key={r.id as number} className={clsx(
                      'rounded-xl border p-4 transition-colors',
                      isLight ? 'bg-white border-amber-200 hover:border-amber-300' : 'bg-surface-800 border-amber-500/20 hover:border-amber-500/40',
                    )}>
                      <div className="flex items-start gap-4">
                        {/* Countdown */}
                        <div className={clsx(
                          'flex flex-col items-center justify-center rounded-lg px-3 py-2 shrink-0 min-w-[60px]',
                          isLight ? 'bg-amber-50' : 'bg-amber-500/10',
                        )}>
                          <div className="text-2xl font-bold text-amber-500 leading-none">{daysUntil}</div>
                          <div className="text-[10px] text-amber-500/70 uppercase">day{daysUntil !== 1 ? 's' : ''}</div>
                        </div>

                        {/* Details */}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1">
                            <span className={clsx('text-base font-semibold', isLight ? 'text-gray-800' : 'text-gray-100')}>{r.name as string}</span>
                            <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: sportColor }} />
                            <span className="text-xs text-gray-500">{r.sport_type as string}</span>
                          </div>
                          <div className="flex items-center gap-3 text-xs text-gray-500 flex-wrap">
                            <span>{format(parseISO(r.date as string), 'EEEE, MMM d, yyyy')}</span>
                            {r.distance_km != null && <span className="font-mono">{r.distance_km} km</span>}
                            {r.target_pace != null && <span className="font-mono">{r.target_pace} {getPaceUnit(r.sport_type as string)}</span>}
                            {r.location && <span>{r.location as string}</span>}
                          </div>
                          {r.description && (
                            <div className={clsx('text-xs mt-1.5', isLight ? 'text-gray-500' : 'text-gray-400')}>{r.description as string}</div>
                          )}
                          {r.url && (
                            <a
                              href={r.url as string}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-xs text-amber-500 hover:text-amber-400 mt-1 inline-block"
                              onClick={e => e.stopPropagation()}
                            >
                              Race website &#8599;
                            </a>
                          )}
                        </div>

                        {/* Actions */}
                        <div className="flex items-center gap-2 shrink-0">
                          {isConfirming ? (
                            <>
                              <span className="text-xs text-red-400">Delete?</span>
                              <button onClick={() => { deleteRace.mutate(r.id as number, { onSuccess: () => toast('Race deleted', 'success') }); setConfirmDeleteId(null) }} className="text-red-400 hover:text-red-300 text-xs font-bold">Yes</button>
                              <button onClick={() => setConfirmDeleteId(null)} className="text-xs text-gray-400 hover:text-gray-200">No</button>
                            </>
                          ) : (
                            <>
                              <button onClick={() => startEdit(r)} className="text-xs text-gray-400 hover:text-gray-200">Edit</button>
                              <button onClick={() => setConfirmDeleteId(r.id as number)} className="text-xs text-red-400 hover:text-red-300">Delete</button>
                            </>
                          )}
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            </section>
          )}

          {/* Past Races */}
          {past.length > 0 && (
            <section>
              <div className="text-xs text-gray-500 uppercase mb-3">Past Races</div>
              <div className="space-y-2">
                {past.map((r: Record<string, unknown>) => {
                  const sportColor = getSportColor(r.sport_type as string)
                  const dayActivities = activityByDate[r.date as string] || []
                  const matchedActivity = dayActivities.find(a => a.sport_type === r.sport_type)
                  const isConfirming = confirmDeleteId === (r.id as number)
                  return (
                    <div key={r.id as number} className={clsx(
                      'rounded-xl border p-4 transition-colors',
                      isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600',
                    )}>
                      <div className="flex items-center gap-4">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-0.5">
                            <span className={clsx('text-sm font-medium', isLight ? 'text-gray-700' : 'text-gray-200')}>{r.name as string}</span>
                            <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: sportColor }} />
                            <span className="text-xs text-gray-500">{r.sport_type as string}</span>
                            {matchedActivity && (
                              <Link
                                to={`/activities/${matchedActivity.id}`}
                                className="text-xs text-green-400 hover:text-green-300 flex items-center gap-0.5"
                              >
                                &#10003; View activity
                              </Link>
                            )}
                          </div>
                          <div className="flex items-center gap-3 text-xs text-gray-500 flex-wrap">
                            <span>{format(parseISO(r.date as string), 'MMM d, yyyy')}</span>
                            {r.distance_km != null && <span className="font-mono">{r.distance_km} km</span>}
                            {r.target_pace != null && <span className="font-mono">{r.target_pace} {getPaceUnit(r.sport_type as string)}</span>}
                            {r.location && <span>{r.location as string}</span>}
                            {r.url && (
                              <a href={r.url as string} target="_blank" rel="noopener noreferrer" className="text-amber-500 hover:text-amber-400" onClick={e => e.stopPropagation()}>
                                Website &#8599;
                              </a>
                            )}
                          </div>
                          {r.description && (
                            <div className={clsx('text-xs mt-1', isLight ? 'text-gray-400' : 'text-gray-500')}>{r.description as string}</div>
                          )}
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          {isConfirming ? (
                            <>
                              <span className="text-xs text-red-400">Delete?</span>
                              <button onClick={() => { deleteRace.mutate(r.id as number, { onSuccess: () => toast('Race deleted', 'success') }); setConfirmDeleteId(null) }} className="text-red-400 hover:text-red-300 text-xs font-bold">Yes</button>
                              <button onClick={() => setConfirmDeleteId(null)} className="text-xs text-gray-400 hover:text-gray-200">No</button>
                            </>
                          ) : (
                            <>
                              <button onClick={() => startEdit(r)} className="text-xs text-gray-400 hover:text-gray-200">Edit</button>
                              <button onClick={() => setConfirmDeleteId(r.id as number)} className="text-xs text-red-400 hover:text-red-300">Delete</button>
                            </>
                          )}
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            </section>
          )}

          {upcoming.length === 0 && past.length === 0 && !showForm && (
            <div className={clsx('rounded-xl border p-8 text-center', isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600')}>
              <div className="text-3xl mb-2">&#9873;</div>
              <div className={clsx('text-sm', isLight ? 'text-gray-500' : 'text-gray-400')}>No races for {filterYear}</div>
              <button
                onClick={() => { resetForm(); setShowForm(true); setDate(format(today, 'yyyy-MM-dd')) }}
                className="mt-3 text-sm text-amber-500 hover:text-amber-400"
              >
                Add your first race
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
