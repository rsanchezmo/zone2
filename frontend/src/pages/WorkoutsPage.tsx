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
        <h1 className="text-2xl font-bold">Workout Templates</h1>
        {!showBuilder && (
          <button
            onClick={() => { resetForm(); setShowBuilder(true) }}
            className="bg-neon-cyan/20 text-neon-cyan border border-neon-cyan/30 rounded-lg px-4 py-2 text-sm hover:bg-neon-cyan/30 transition-colors"
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
                color: active ? '#fff' : color,
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
        <div className="bg-surface-800 border border-surface-600 rounded-xl p-5 space-y-4">
          <div className="text-sm font-medium text-gray-300">
            {editingTemplate ? 'Edit Workout' : 'New Workout'}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Name</label>
              <input
                type="text" placeholder="e.g. Tempo 5x1km"
                value={name} onChange={e => setName(e.target.value)}
                className="w-full bg-surface-700 border border-surface-600 rounded-lg px-3 py-2.5 text-sm"
              />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Sport Type</label>
              <select
                value={sportType} onChange={e => setSportType(e.target.value)}
                className="w-full bg-surface-700 border border-surface-600 rounded-lg px-3 py-2.5 text-sm"
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
              className="w-full bg-surface-700 border border-surface-600 rounded-lg px-3 py-2 text-sm"
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
              className="flex-1 bg-neon-cyan/20 text-neon-cyan border border-neon-cyan/30 rounded py-2 text-sm hover:bg-neon-cyan/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {editingTemplate ? 'Save Changes' : 'Create Template'}
            </button>
            <button
              onClick={resetForm}
              className={clsx('flex-1 bg-surface-700 rounded py-2 text-sm text-gray-400', isLight ? 'hover:text-gray-700' : 'hover:text-gray-200')}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Template list */}
      {isLoading ? (
        <div className="text-sm text-gray-500">Loading...</div>
      ) : !templates || templates.length === 0 ? (
        <div className="bg-surface-800 border border-surface-600 rounded-xl p-8 text-center text-gray-500">
          <div className="text-lg mb-1">No workout templates yet</div>
          <div className="text-sm">Create your first structured workout above</div>
        </div>
      ) : (
        <div className="grid gap-3">
          {(templates as Record<string, unknown>[]).map(t => {
            const sColor = getSportColor(t.sport_type as string)
            const isConfirming = confirmDeleteId === (t.id as number)
            return (
              <div
                key={t.id as number}
                className="bg-surface-800 border border-surface-600 rounded-xl p-4 transition-colors hover:border-surface-500"
              >
                <div className="flex items-start justify-between mb-2">
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-medium text-sm">{t.name as string}</span>
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
                          className="text-gray-400 hover:text-gray-200 text-xs"
                        >No</button>
                      </>
                    ) : (
                      <>
                        <button onClick={() => startEdit(t)} className="text-gray-400 hover:text-gray-200 text-xs">Edit</button>
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
