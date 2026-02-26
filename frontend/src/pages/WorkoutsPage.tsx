import { useState, useMemo } from 'react'
import {
  useWorkoutTemplates, useCreateWorkoutTemplate,
  useUpdateWorkoutTemplate, useDeleteWorkoutTemplate,
} from '../api/hooks'
import { SPORT_COLORS_HEX, getSportColor } from '../constants/sportColors'
import SegmentListBuilder, { SegmentSummary, type Segment } from '../components/shared/SegmentListBuilder'
import clsx from 'clsx'
import { useTheme } from '../hooks/useTheme'

const SPORT_FILTERS = ['All', 'Run', 'Ride', 'Swim', 'Walk', 'Hike'] as const

function getPaceUnit(sportType: string): string {
  const st = sportType.toLowerCase().replace(/\s/g, '')
  const cycling = new Set(['ride', 'virtualride', 'ebikeride', 'gravelride', 'mountainbikeride'])
  if (cycling.has(st)) return 'km/h'
  return 'min/km'
}

export default function WorkoutsPage() {
  const { theme } = useTheme()
  const isLight = theme === 'light'
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

  const cardClass = clsx(
    'rounded-xl border',
    isLight ? 'bg-white border-gray-200' : 'bg-surface-800 border-surface-600',
  )

  const inputClass = clsx(
    'w-full border rounded-lg px-3 py-2.5 text-sm',
    isLight ? 'bg-white border-gray-200 text-gray-700' : 'bg-surface-700 border-surface-600 text-gray-200',
  )

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
      segments: segments as Record<string, unknown>[],
    }
    if (editingTemplate) {
      updateTemplate.mutate({ id: editingTemplate.id as number, ...payload }, { onSuccess: resetForm })
    } else {
      createTemplate.mutate(payload, { onSuccess: resetForm })
    }
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h1 className={clsx('text-2xl font-bold', isLight ? 'text-gray-900' : 'text-white')}>Workout Templates</h1>
        {!showBuilder && (
          <button
            onClick={() => { resetForm(); setShowBuilder(true) }}
            className={clsx(
              'border rounded-lg px-4 py-2 text-sm transition-colors',
              isLight
                ? 'bg-gray-900 text-white border-gray-900 hover:bg-gray-800'
                : 'bg-white/10 text-gray-300 border-white/20 hover:bg-white/15',
            )}
          >
            + New Workout
          </button>
        )}
      </div>

      {/* Sport filter chips */}
      <div className="flex gap-2 flex-wrap">
        {SPORT_FILTERS.map(s => {
          const active = sportFilter === s
          const color = s === 'All' ? '#9ca3af' : getSportColor(s)
          return (
            <button
              key={s}
              onClick={() => setSportFilter(s)}
              className="text-xs rounded-full px-3 py-1.5 border transition-all"
              style={{
                borderColor: active ? color : `${color}30`,
                color: active ? (isLight ? '#fff' : '#fff') : color,
                backgroundColor: active ? `${color}30` : 'transparent',
              }}
            >
              {s}
            </button>
          )
        })}
      </div>

      {/* Builder form */}
      {showBuilder && (
        <div className={clsx(cardClass, 'p-5 space-y-4')}>
          <div className={clsx('text-sm font-medium', isLight ? 'text-gray-700' : 'text-gray-300')}>
            {editingTemplate ? 'Edit Workout' : 'New Workout'}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Name</label>
              <input
                type="text" placeholder="e.g. Tempo 5x1km"
                value={name} onChange={e => setName(e.target.value)}
                className={inputClass}
              />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Sport Type</label>
              <select
                value={sportType} onChange={e => setSportType(e.target.value)}
                className={inputClass}
                style={{ color: getSportColor(sportType) }}
              >
                {Object.keys(SPORT_COLORS_HEX).map(s => (
                  <option key={s} value={s}>{s}</option>
                ))}
                <option value="Other">Other</option>
              </select>
            </div>
          </div>

          <div>
            <label className="text-xs text-gray-500 mb-1 block">Description</label>
            <textarea
              placeholder="Optional description..."
              value={description} onChange={e => setDescription(e.target.value)}
              className={inputClass}
              rows={2}
            />
          </div>

          <div>
            <label className="text-xs text-gray-500 mb-1 block">Segments</label>
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
                'flex-1 border rounded py-2 text-sm transition-colors disabled:opacity-40 disabled:cursor-not-allowed',
                isLight
                  ? 'bg-gray-900 text-white border-gray-900 hover:bg-gray-800'
                  : 'bg-white/10 text-gray-300 border-white/20 hover:bg-white/15',
              )}
            >
              {editingTemplate ? 'Save Changes' : 'Create Template'}
            </button>
            <button
              onClick={resetForm}
              className={clsx(
                'flex-1 rounded py-2 text-sm transition-colors',
                isLight ? 'bg-gray-100 text-gray-500 hover:text-gray-700' : 'bg-surface-700 text-gray-400 hover:text-gray-200',
              )}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Template list */}
      {isLoading ? (
        <div className="grid gap-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className={clsx(cardClass, 'p-4 animate-pulse')}>
              <div className="flex items-center gap-2 mb-3">
                <div className={clsx('h-4 w-32 rounded', isLight ? 'bg-gray-200' : 'bg-surface-700')} />
                <div className={clsx('h-4 w-12 rounded-full', isLight ? 'bg-gray-100' : 'bg-surface-700')} />
              </div>
              <div className={clsx('h-8 rounded', isLight ? 'bg-gray-100' : 'bg-surface-700')} />
            </div>
          ))}
        </div>
      ) : !templates || templates.length === 0 ? (
        <div className={clsx(cardClass, 'p-8 text-center')}>
          <svg className={clsx('w-10 h-10 mx-auto mb-3', isLight ? 'text-gray-300' : 'text-gray-600')} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
          </svg>
          <div className={clsx('text-sm mb-1', isLight ? 'text-gray-500' : 'text-gray-500')}>No workout templates yet</div>
          <div className={clsx('text-xs', isLight ? 'text-gray-400' : 'text-gray-600')}>Create your first structured workout above</div>
        </div>
      ) : (
        <div className="grid gap-3">
          {(templates as Record<string, unknown>[]).map(t => {
            const sColor = getSportColor(t.sport_type as string)
            const isConfirming = confirmDeleteId === (t.id as number)
            return (
              <div
                key={t.id as number}
                className={clsx(cardClass, 'p-4 transition-colors', isLight ? 'hover:border-gray-300' : 'hover:border-surface-500')}
              >
                <div className="flex items-start justify-between mb-2">
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <span className={clsx('font-medium text-sm', isLight ? 'text-gray-900' : 'text-gray-100')}>{t.name as string}</span>
                      <span
                        className="text-[10px] rounded-full px-2 py-0.5 border"
                        style={{ color: sColor, borderColor: `${sColor}40`, backgroundColor: `${sColor}10` }}
                      >
                        {t.sport_type as string}
                      </span>
                    </div>
                    {t.description && (
                      <div className="text-xs text-gray-500 mb-2">{t.description as string}</div>
                    )}
                  </div>
                  <div className="flex gap-2 shrink-0 ml-3">
                    {isConfirming ? (
                      <>
                        <span className="text-xs text-red-400">Delete?</span>
                        <button
                          onClick={() => { deleteTemplate.mutate(t.id as number); setConfirmDeleteId(null) }}
                          className="text-red-400 hover:text-red-300 text-xs font-bold"
                        >Yes</button>
                        <button
                          onClick={() => setConfirmDeleteId(null)}
                          className={clsx('text-xs', isLight ? 'text-gray-400 hover:text-gray-600' : 'text-gray-400 hover:text-gray-200')}
                        >No</button>
                      </>
                    ) : (
                      <>
                        <button onClick={() => startEdit(t)} className={clsx('text-xs', isLight ? 'text-gray-400 hover:text-gray-600' : 'text-gray-400 hover:text-gray-200')}>Edit</button>
                        <button onClick={() => setConfirmDeleteId(t.id as number)} className="text-red-400 hover:text-red-300 text-xs">Delete</button>
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
    </div>
  )
}
