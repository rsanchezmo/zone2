import { useState } from 'react'
import {
  useWorkoutTemplates, useCreateWorkoutTemplate,
  useUpdateWorkoutTemplate, useDeleteWorkoutTemplate,
} from '../api/hooks'
import { getSportColor } from '../constants/sportColors'
import { getPaceUnit } from '../utils/formatSpeed'
import SportTypeCombobox from '../components/shared/SportTypeCombobox'
import SegmentListBuilder, { SegmentSummary, type Segment } from '../components/shared/SegmentListBuilder'
import clsx from 'clsx'
import { useTheme } from '../hooks/useTheme'
import { useToast } from '../hooks/useToast'

const SPORT_FILTERS = ['All', 'Run', 'Ride', 'Swim', 'Walk', 'Hike'] as const

export default function WorkoutsPage() {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const { toast } = useToast()
  const [sportFilter, setSportFilter] = useState<string>('All')
  const [editingTemplate, setEditingTemplate] = useState<Record<string, unknown> | null>(null)
  const [showBuilder, setShowBuilder] = useState(false)
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null)

  // Form state
  const [name, setName] = useState('')
  const [sportType, setSportType] = useState('Run')
  const [description, setDescription] = useState('')
  const [segments, setSegments] = useState<Segment[]>([])

  const queryFilter = sportFilter === 'All' ? undefined : sportFilter
  const { data: templates, isLoading } = useWorkoutTemplates(queryFilter)
  const createTemplate = useCreateWorkoutTemplate()
  const updateTemplate = useUpdateWorkoutTemplate()
  const deleteTemplate = useDeleteWorkoutTemplate()

  const panelClass = clsx(
    'panel',
    isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600',
  )
  const inputClass = 'input w-full'

  function resetForm() {
    setName('')
    setSportType('Run')
    setDescription('')
    setSegments([])
    setEditingTemplate(null)
    setShowBuilder(false)
  }

  function startEdit(t: Record<string, unknown>) {
    setEditingTemplate(t)
    setName(t.name as string)
    setSportType(t.sport_type as string)
    setDescription((t.description as string) || '')
    setSegments((t.segments as Segment[]) || [])
    setShowBuilder(true)
  }

  function handleSave() {
    if (!name.trim() || segments.length === 0) return
    const payload = {
      name: name.trim(),
      sport_type: sportType,
      description: description.trim() || undefined,
      segments: segments as unknown as Record<string, unknown>[],
    }
    if (editingTemplate) {
      updateTemplate.mutate({ id: editingTemplate.id as number, ...payload }, {
        onSuccess: () => { resetForm(); toast('Workout updated', 'success') },
        onError: () => toast('Failed to update workout', 'error'),
      })
    } else {
      createTemplate.mutate(payload, {
        onSuccess: () => { resetForm(); toast('Workout created', 'success') },
        onError: () => toast('Failed to create workout', 'error'),
      })
    }
  }

  return (
    <div className="max-w-4xl mx-auto space-y-10 pb-12">
      {/* ── Breadcrumb header ─────────────────────────── */}
      <header className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-baseline gap-2">
          <span className="eyebrow">Workouts</span>
          <span className={clsx('text-[11px]', isLight ? 'text-gray-300' : 'text-gray-700')}>·</span>
          <span className="text-[11px] text-gray-500 normal-case tracking-normal">templates for structured sessions</span>
        </div>
        {!showBuilder && (
          <button
            onClick={() => { resetForm(); setShowBuilder(true) }}
            className="btn"
          >
            + New workout
          </button>
        )}
      </header>

      {/* ── Sport filter ───────────────────────────── */}
      <section>
        <div className="section-head mb-4"><span className="eyebrow">Filter</span></div>
        <div className="flex gap-1.5 flex-wrap">
          {SPORT_FILTERS.map(s => {
            const active = sportFilter === s
            const color = s === 'All' ? '#9ca3af' : getSportColor(s)
            return (
              <button
                key={s}
                onClick={() => setSportFilter(s)}
                className="text-[11px] font-medium rounded-full px-3 py-1.5 border transition-all tracking-[0.05em]"
                style={{
                  borderColor: active ? color : `${color}30`,
                  color: active ? '#fff' : color,
                  backgroundColor: active ? `${color}40` : 'transparent',
                }}
              >
                {s}
              </button>
            )
          })}
        </div>
      </section>

      {/* ── Builder form ───────────────────────────── */}
      {showBuilder && (
        <section className={clsx(panelClass, 'p-5 md:p-6 space-y-4 hero-brackets')} style={{ ['--card-accent' as string]: getSportColor(sportType) }}>
          <div className="eyebrow">{editingTemplate ? 'Edit workout' : 'New workout'}</div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label className="eyebrow mb-1.5 block">Name</label>
              <input
                type="text" placeholder="e.g. Tempo 5x1km"
                value={name} onChange={e => setName(e.target.value)}
                className={inputClass}
              />
            </div>
            <div>
              <label className="eyebrow mb-1.5 block">Sport</label>
              <SportTypeCombobox
                value={sportType}
                onChange={setSportType}
                className={inputClass}
                isLight={isLight}
              />
            </div>
          </div>

          <div>
            <label className="eyebrow mb-1.5 block">Description</label>
            <textarea
              placeholder="Optional description…"
              value={description} onChange={e => setDescription(e.target.value)}
              className={inputClass}
              rows={2}
            />
          </div>

          <div>
            <label className="eyebrow mb-1.5 block">Segments</label>
            <SegmentListBuilder
              segments={segments}
              onChange={setSegments}
              paceUnit={getPaceUnit(sportType)}
            />
          </div>

          <div className="flex gap-2 pt-1">
            <button
              onClick={handleSave}
              disabled={!name.trim() || segments.length === 0}
              className={clsx(
                'btn flex-1 !text-sm !py-2',
                isLight
                  ? '!bg-gray-900 !text-white !border-gray-900 hover:!bg-gray-800'
                  : '!bg-white/10 !text-gray-200 !border-white/20 hover:!bg-white/15',
              )}
            >
              {editingTemplate ? 'Save changes' : 'Create template'}
            </button>
            <button onClick={resetForm} className="btn flex-1 !text-sm !py-2">
              Cancel
            </button>
          </div>
        </section>
      )}

      {/* ── Template list ──────────────────────────── */}
      <section>
        <div className="section-head mb-4"><span className="eyebrow">Templates</span></div>
        {isLoading ? (
          <div className="grid gap-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className={clsx(panelClass, 'p-4 animate-pulse')}>
                <div className="flex items-center gap-2 mb-3">
                  <div className={clsx('h-4 w-32 rounded', isLight ? 'bg-gray-200' : 'bg-surface-700')} />
                  <div className={clsx('h-4 w-12 rounded-full', isLight ? 'bg-gray-100' : 'bg-surface-700')} />
                </div>
                <div className={clsx('h-8 rounded', isLight ? 'bg-gray-100' : 'bg-surface-700')} />
              </div>
            ))}
          </div>
        ) : !templates || templates.length === 0 ? (
          <div className={clsx(panelClass, 'p-10 text-center flex flex-col items-center gap-3')}>
            <svg className={clsx('w-9 h-9', isLight ? 'text-gray-300' : 'text-gray-600')} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
            </svg>
            <div className={clsx('text-sm', isLight ? 'text-gray-500' : 'text-gray-500')}>No workout templates yet</div>
            <div className={clsx('text-[11px]', isLight ? 'text-gray-400' : 'text-gray-600')}>Create your first structured workout from the button above</div>
          </div>
        ) : (
          <div className="grid gap-3 stagger-children">
            {(templates as Record<string, unknown>[]).map(t => {
              const sColor = getSportColor(t.sport_type as string)
              const isConfirming = confirmDeleteId === (t.id as number)
              return (
                <div
                  key={t.id as number}
                  className={clsx(panelClass, 'p-4 transition-colors')}
                  style={{ borderLeftWidth: 2, borderLeftColor: sColor }}
                >
                  <div className="flex items-start justify-between mb-3 gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap mb-1">
                        <span className={clsx('font-semibold text-sm tracking-tight', isLight ? 'text-gray-900' : 'text-gray-100')}>{t.name as string}</span>
                        <span
                          className="text-[10px] uppercase tracking-[0.15em] rounded-full px-2 py-0.5 border font-semibold"
                          style={{ color: sColor, borderColor: `${sColor}40`, backgroundColor: `${sColor}15` }}
                        >
                          {t.sport_type as string}
                        </span>
                      </div>
                      {!!t.description && (
                        <div className={clsx('text-xs', isLight ? 'text-gray-500' : 'text-gray-500')}>{String(t.description)}</div>
                      )}
                    </div>
                    <div className="flex gap-2 shrink-0">
                      {isConfirming ? (
                        <>
                          <span className="text-[11px] uppercase tracking-[0.15em] text-red-400">Delete?</span>
                          <button
                            onClick={() => {
                              deleteTemplate.mutate(t.id as number, {
                                onSuccess: () => toast('Workout deleted', 'success'),
                                onError: () => toast('Failed to delete workout', 'error'),
                              })
                              setConfirmDeleteId(null)
                            }}
                            className="text-red-400 hover:text-red-300 text-[11px] uppercase tracking-[0.15em] font-bold"
                          >Yes</button>
                          <button
                            onClick={() => setConfirmDeleteId(null)}
                            className={clsx('text-[11px] uppercase tracking-[0.15em]', isLight ? 'text-gray-400 hover:text-gray-600' : 'text-gray-500 hover:text-gray-200')}
                          >No</button>
                        </>
                      ) : (
                        <>
                          <button onClick={() => startEdit(t)} className={clsx('text-[11px] uppercase tracking-[0.15em]', isLight ? 'text-gray-400 hover:text-gray-600' : 'text-gray-500 hover:text-gray-200')}>Edit</button>
                          <button onClick={() => setConfirmDeleteId(t.id as number)} className="text-red-400/80 hover:text-red-300 text-[11px] uppercase tracking-[0.15em]">Delete</button>
                        </>
                      )}
                    </div>
                  </div>
                  <SegmentSummary segments={(t.segments as Segment[]) || []} />
                </div>
              )
            })}
          </div>
        )}
      </section>
    </div>
  )
}
