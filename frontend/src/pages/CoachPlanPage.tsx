import { Link, useParams } from 'react-router-dom'
import { useCoachPlan } from '../api/coach'
import PageHeader from '../components/shared/PageHeader'
import PlanOverview from '../components/coach/PlanOverview'
import { Checkpoints, PlanWeeks } from '../components/coach/PlanWeeks'
import { CoachLog, PlanAgreements } from '../components/coach/CoachLog'

/** One plan: its hero, the weekly trends, checkpoints and agreements, sessions and the coach's log. */
export default function CoachPlanPage() {
  const planId = Number(useParams().planId) || undefined
  const { data: plan, isError } = useCoachPlan(planId)

  return (
    <div className="max-w-5xl mx-auto space-y-10 pb-12">
      <PageHeader
        title={plan?.name ?? 'Plan'}
        description={plan?.race ? plan.race.name : 'coach · plan'}
        actions={
          <Link
            to="/coach"
            className="inline-flex items-center gap-1.5 text-xs font-semibold transition-colors text-fg-muted hover:text-fg-strong"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
            All plans
          </Link>
        }
      />

      {isError && (
        <div className="panel p-8 text-center">
          <p className="text-sm">There's no plan here.</p>
          <Link to="/coach" className="text-[12px] text-gray-500 hover:text-red-400">See all plans</Link>
        </div>
      )}

      {plan && (
        <>
          <PlanOverview plan={plan} />
          <Checkpoints plan={plan} />
          <PlanAgreements notes={plan.agreements} />
          <PlanWeeks plan={plan} />
          <CoachLog entries={plan.log} />
        </>
      )}
    </div>
  )
}
