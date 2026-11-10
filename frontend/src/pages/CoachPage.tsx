import { useCoachPlans } from '../api/hooks'
import PageHeader from '../components/shared/PageHeader'
import PlanCard from '../components/coach/PlanCard'
import { CoachNotes } from '../components/coach/CoachLog'

/** Every plan as a card, like the activity list; each opens its plan. */
export default function CoachPage() {
  const { data: plans, isLoading } = useCoachPlans()
  const active = (plans ?? []).filter(p => p.status === 'active')
  const past = (plans ?? []).filter(p => p.status !== 'active')

  return (
    <div className="max-w-5xl mx-auto space-y-8 pb-12">
      <PageHeader title="Coach" description="your plans · the coach's log" />

      {isLoading && (
        <div className="space-y-2">
          {[0, 1].map(i => <div key={i} className="panel h-[118px] animate-pulse" />)}
        </div>
      )}

      {!isLoading && plans?.length === 0 && (
        <div className="panel p-8 text-center space-y-1">
          <p className="text-sm">No plans yet.</p>
          <p className="text-[12px] text-gray-500">Ask the coach to build one toward a race. It shows up here with its progress.</p>
        </div>
      )}

      {[{ label: 'Active', plans: active }, { label: 'Finished', plans: past }].filter(g => g.plans.length).map(g => (
        <section key={g.label} className="space-y-2.5">
          <div className="flex items-center gap-3 py-2">
            <span className="eyebrow shrink-0">{g.label}</span>
            <div className="hidden sm:block flex-1 h-px" style={{ background: 'linear-gradient(to right, var(--color-surface-600) 0%, transparent 75%)' }} />
            <span className="shrink-0 text-[11px] text-gray-500 font-mono tabular-nums">{g.plans.length} {g.plans.length === 1 ? 'plan' : 'plans'}</span>
          </div>
          <div className="space-y-2 stagger-children">
            {g.plans.map(p => <PlanCard key={p.id} plan={p} />)}
          </div>
        </section>
      ))}

      <CoachNotes />
    </div>
  )
}
