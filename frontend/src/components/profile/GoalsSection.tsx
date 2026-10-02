import { useMemo, useState } from 'react'
import clsx from 'clsx'
import {
  useCreateGoal, useUpdateGoal, useDeleteGoal, type Goal, type GoalProgress,
} from '../../api/hooks'
import RowActions from '../shared/RowActions'
import GoalProgressBar from '../shared/GoalProgressBar'
import ChartPanel from '../shared/ChartPanel'
import { goalAmount, GOAL_DONE_COLOR } from '../../utils/goals'
import { getSportColor } from '../../constants/sportColors'
import { getSportCategory } from '../../utils/formatSpeed'
import { useTheme } from '../../hooks/useTheme'
import { useToast } from '../../hooks/useToast'

function getMetricOptions(sportType: string) {
  const isSwimming = getSportCategory(sportType) === 'swimming'
  return [
    { value: 'distance_km', label: isSwimming ? 'Distance (m)' : 'Distance (km)' },
    { value: 'time_hours', label: 'Time (hours)' },
    { value: 'activities', label: 'Activities' },
    { value: 'elevation_m', label: 'Elevation (m)' },
  ]
}

const PERIOD_OPTIONS = [
  { value: 'weekly', label: 'Weekly' },
  { value: 'monthly', label: 'Monthly' },
  { value: 'yearly', label: 'Yearly' },
]

function metricLabel(metric: string, sportType?: string): string {
  return getMetricOptions(sportType ?? 'Run').find(m => m.value === metric)?.label ?? metric
}

function periodLabel(period: string): string {
  return PERIOD_OPTIONS.find(p => p.value === period)?.label ?? period
}

export default function GoalsSection({ goals, progress: goalProgressData, sportTypes }: {
  goals: Goal[] | undefined
  progress: { goals: GoalProgress[] } | undefined
  sportTypes: string[] | undefined
}) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const { toast } = useToast()
  const createGoal = useCreateGoal()
  const updateGoal = useUpdateGoal()
  const deleteGoal = useDeleteGoal()

  const [showGoalForm, setShowGoalForm] = useState(false)
  const [editingGoalId, setEditingGoalId] = useState<number | null>(null)
  const [confirmDeleteGoalId, setConfirmDeleteGoalId] = useState<number | null>(null)
  const currentYear = new Date().getFullYear()
  const [goalForm, setGoalForm] = useState({ year: String(currentYear), sport_type: 'Run', metric: 'distance_km', period: 'weekly', target_value: '' })

  const inputClass = 'input'
  const selectClass = 'select'

  // Build a lookup: goal id → progress data
  const progressMap = useMemo(() => {
    const map = new Map<number, { current_value: number; percentage: number; period_start: string; period_end: string }>()
    if (goalProgressData?.goals) {
      for (const g of goalProgressData.goals) {
        map.set(g.id, g)
      }
    }
    return map
  }, [goalProgressData])

  const handleGoalSubmit = () => {
    let target = parseFloat(goalForm.target_value)
    const yearNum = parseInt(goalForm.year)
    if (!target || target <= 0 || !yearNum) return
    // Convert meters to km for swimming distance goals (backend stores km)
    if (goalForm.metric === 'distance_km' && getSportCategory(goalForm.sport_type) === 'swimming') {
      target = target / 1000
    }
    const payload = { year: yearNum, sport_type: goalForm.sport_type, metric: goalForm.metric, period: goalForm.period, target_value: target }
    if (editingGoalId != null) {
      updateGoal.mutate({ id: editingGoalId, ...payload }, {
        onSuccess: () => { setEditingGoalId(null); setShowGoalForm(false); toast('Goal updated', 'success') },
      })
    } else {
      createGoal.mutate(payload, {
        onSuccess: () => { setShowGoalForm(false); setGoalForm({ year: String(currentYear), sport_type: 'Run', metric: 'distance_km', period: 'weekly', target_value: '' }); toast('Goal created', 'success') },
      })
    }
  }

  const startEdit = (goal: Goal) => {
    setEditingGoalId(goal.id)
    // Convert km back to meters for swimming distance goals
    let displayValue = goal.target_value
    if (goal.metric === 'distance_km' && getSportCategory(goal.sport_type) === 'swimming') {
      displayValue = displayValue * 1000
    }
    setGoalForm({
      year: String(goal.year),
      sport_type: goal.sport_type,
      metric: goal.metric,
      period: goal.period,
      target_value: String(displayValue),
    })
    setShowGoalForm(true)
  }

  const cancelForm = () => {
    setShowGoalForm(false)
    setEditingGoalId(null)
    setGoalForm({ year: String(currentYear), sport_type: 'Run', metric: 'distance_km', period: 'weekly', target_value: '' })
  }

  return (
    <ChartPanel
      title="Goals"
      glow={false}
      toolbar={
        !showGoalForm ? (
          <button
            onClick={() => { setEditingGoalId(null); setGoalForm({ year: String(currentYear), sport_type: 'Run', metric: 'distance_km', period: 'weekly', target_value: '' }); setShowGoalForm(true) }}
            className="btn"
          >
            + Add goal
          </button>
        ) : undefined
      }
    >

      {/* Goal form */}
      {showGoalForm && (
        <div className={clsx('mb-4 p-3 rounded-lg space-y-3', isLight ? 'bg-gray-50' : 'bg-surface-700')}>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
            <input
              type="number" min="2020" max="2040" placeholder="Year"
              value={goalForm.year}
              onChange={e => setGoalForm(f => ({ ...f, year: e.target.value }))}
              className={inputClass}
            />
            <select
              value={goalForm.sport_type}
              onChange={e => setGoalForm(f => ({ ...f, sport_type: e.target.value }))}
              className={selectClass}
            >
              <option value="__all__">All Sports</option>
              {(sportTypes ?? []).map((s: string) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <select
              value={goalForm.metric}
              onChange={e => setGoalForm(f => ({ ...f, metric: e.target.value }))}
              className={selectClass}
            >
              {getMetricOptions(goalForm.sport_type).map(m => (
                <option key={m.value} value={m.value}>{m.label}</option>
              ))}
            </select>
            <select
              value={goalForm.period}
              onChange={e => setGoalForm(f => ({ ...f, period: e.target.value }))}
              className={selectClass}
            >
              {PERIOD_OPTIONS.map(p => (
                <option key={p.value} value={p.value}>{p.label}</option>
              ))}
            </select>
            <input
              type="number" step="any" min="0" placeholder="Target value"
              value={goalForm.target_value}
              onChange={e => setGoalForm(f => ({ ...f, target_value: e.target.value }))}
              className={inputClass}
            />
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleGoalSubmit}
              disabled={!goalForm.target_value || parseFloat(goalForm.target_value) <= 0}
              className="btn"
            >
              {editingGoalId != null ? 'Update' : 'Create'}
            </button>
            <button
              onClick={cancelForm}
              className="btn"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Goals list with progress */}
      {goals && goals.length > 0 ? (
        <div className="space-y-3">
          {goals.map(goal => {
            const sport = goal.sport_type
            const color = getSportColor(sport)
            const metric = goal.metric
            const { value: targetDisplay, unit: targetUnit } = goalAmount(goal, goal.target_value)

            const progress = progressMap.get(goal.id)
            const currentDisplay = progress ? goalAmount(goal, progress.current_value).value : null
            const pct = progress?.percentage ?? null
            const barColor = pct !== null && pct >= 100 ? GOAL_DONE_COLOR : color

            return (
              <div
                key={goal.id as number}
                className={clsx(
                  'rounded-xl border p-3 group transition-all duration-200',
                  isLight ? 'bg-white border-gray-200 hover:border-gray-300' : 'bg-surface-800 border-surface-600 hover:border-surface-500',
                )}
                style={{ borderLeftWidth: 3, borderLeftColor: barColor }}
              >
                {/* Top row: sport, metric, period, actions */}
                <div className="flex items-center gap-2 mb-2">
                  <span className={clsx('text-sm font-medium', isLight ? 'text-gray-800' : 'text-gray-200')}>
                    {sport === '__all__' ? 'All Sports' : sport}
                  </span>
                  <span className={clsx('text-[11px] px-1.5 py-0.5 rounded-md', isLight ? 'bg-gray-100 text-gray-500' : 'bg-surface-700 text-gray-400')}>
                    {metricLabel(metric, sport)}
                  </span>
                  <span className={clsx('text-[11px] px-1.5 py-0.5 rounded-md', isLight ? 'bg-gray-100 text-gray-500' : 'bg-surface-700 text-gray-400')}>
                    {periodLabel(goal.period).toLowerCase()}
                  </span>
                  <span className="text-[11px] text-gray-500 font-mono">{goal.year}</span>
                  {/* Hover-reveal would strand these on touch, where no hover
                      event ever fires — pin them visible there instead. */}
                  <div className={clsx(
                    'ml-auto transition-opacity',
                    confirmDeleteGoalId !== goal.id && 'opacity-0 group-hover:opacity-100 [@media(hover:none)]:opacity-100',
                  )}>
                    <RowActions
                      isConfirming={confirmDeleteGoalId === goal.id}
                      onEdit={() => startEdit(goal)}
                      onConfirmDelete={() => {
                        deleteGoal.mutate(goal.id, { onSuccess: () => toast('Goal deleted', 'success') })
                        setConfirmDeleteGoalId(null)
                      }}
                      onAskDelete={() => setConfirmDeleteGoalId(goal.id)}
                      onCancelDelete={() => setConfirmDeleteGoalId(null)}
                    />
                  </div>
                </div>

                {/* Progress bar */}
                <div className="flex items-center gap-3">
                  <GoalProgressBar percentage={pct ?? 0} color={color} className="flex-1 h-2" />
                  <div className="text-right shrink-0 min-w-[100px]">
                    {currentDisplay !== null ? (
                      <span className="text-sm font-mono font-medium" style={{ color: barColor }}>
                        {currentDisplay}
                        <span className="text-gray-500 mx-0.5">/</span>
                        {targetDisplay}
                        {targetUnit && <span className="text-[11px] text-gray-500 ml-0.5">{targetUnit}</span>}
                      </span>
                    ) : (
                      <span className="text-sm font-mono text-gray-500">
                        — / {targetDisplay}{targetUnit && <span className="text-[11px] ml-0.5">{targetUnit}</span>}
                      </span>
                    )}
                  </div>
                </div>

                {/* Percentage badge */}
                {pct !== null && (
                  <div className="flex items-center gap-2 mt-1.5">
                    <span className={clsx(
                      'text-[11px] font-semibold px-1.5 py-0.5 rounded-md',
                      pct >= 100
                        ? (isLight ? 'bg-green-100 text-green-700' : 'bg-green-500/15 text-green-400')
                        : pct >= 70
                          ? (isLight ? 'bg-blue-100 text-blue-700' : 'bg-blue-500/15 text-blue-400')
                          : (isLight ? 'bg-gray-100 text-gray-600' : 'bg-surface-700 text-gray-400'),
                    )}>
                      {pct >= 100 ? 'Done!' : `${Math.round(pct)}%`}
                    </span>
                    {progress?.period_start && progress?.period_end && (
                      <span className="text-[10px] text-gray-500">
                        {new Date(progress.period_start).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                        {' — '}
                        {new Date(progress.period_end).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                      </span>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      ) : !showGoalForm ? (
        <div className={clsx('text-sm', isLight ? 'text-gray-400' : 'text-gray-600')}>No goals set. Add a goal to track your progress.</div>
      ) : null}
    </ChartPanel>
  )
}
