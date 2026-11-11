import { useState } from 'react'
import clsx from 'clsx'
import { Link } from 'react-router-dom'
import {
  useCoachNotes, useDeleteCoachNote, useUpdateSuggestion, type CoachLogEntry, type CoachLogKind, type CoachNote,
  type CoachNoteTopic,
} from '../../api/coach'
import { fmtDayDate } from '../garmin/garmin'

const KIND_LABEL: Record<CoachLogKind, string> = {
  review: 'Review',
  change: 'Change',
  decision: 'Decision',
  suggestion: 'Suggestion',
  summary: 'Summary',
}

/** What the coach wrote about the block, latest first. Suggestions change nothing until you ask for them. */
export function CoachLog({ entries }: { entries: CoachLogEntry[] }) {
  const update = useUpdateSuggestion()
  return (
    <section>
      <div className="section-head mb-4"><span className="eyebrow">Coach's log</span></div>
      {entries.length === 0 ? (
        <p className="text-[11px] text-gray-500">Nothing yet. The coach logs its session reviews, the changes you ask for, and its suggestions here.</p>
      ) : (
        <ol className="space-y-2">
          {entries.map(e => {
            const open = e.kind === 'suggestion' && e.status === 'open'
            return (
              <li key={e.id} className={clsx('panel p-4', e.kind === 'suggestion' && e.status !== 'open' && 'opacity-60')}>
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <span className="text-[11px] text-gray-500 sm:w-24 shrink-0">{fmtDayDate(e.date)}</span>
                  <span className={clsx(
                    'text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded border shrink-0',
                    open ? 'border-amber-500/60 text-amber-500' : 'border-surface-500 text-gray-400',
                  )}>
                    {KIND_LABEL[e.kind]}{e.kind === 'suggestion' && e.status !== 'open' && ` · ${e.status}`}
                  </span>
                  <span className="min-w-0 basis-full sm:basis-0 flex-1 text-[13px] font-medium order-last sm:order-none text-fg-strong">{e.title}</span>
                  {e.activity_id != null && (
                    <Link to={`/activities/${e.activity_id}`} className="ml-auto text-[11px] text-gray-500 hover:text-cyan-500 shrink-0">run ›</Link>
                  )}
                </div>
                {e.body && <p className="mt-2 sm:ml-[6.75rem] text-[12px] text-gray-500 leading-relaxed whitespace-pre-line">{e.body}</p>}
                {open && (
                  <div className="mt-2 sm:ml-[6.75rem] flex flex-wrap items-center gap-3 text-[11px]">
                    <span className="text-gray-500">Ask the coach to make this change, or:</span>
                    <button className="text-gray-500 hover:text-cyan-500" onClick={() => update.mutate({ id: e.id, status: 'done' })}>Mark done</button>
                    <button className="text-gray-500 hover:text-red-500" onClick={() => update.mutate({ id: e.id, status: 'dismissed' })}>Dismiss</button>
                  </div>
                )}
              </li>
            )
          })}
        </ol>
      )}
    </section>
  )
}

const TOPICS: { key: CoachNoteTopic; label: string }[] = [
  { key: 'rules', label: 'Your week' },
  { key: 'body', label: 'Body and baselines' },
  { key: 'kit', label: 'Kit and data' },
  { key: 'preferences', label: 'How you like it' },
]

/** Notes with the coach's forget button, which shows on hover. */
function NoteList({ notes }: { notes: CoachNote[] }) {
  const remove = useDeleteCoachNote()
  return (
    <ul className="space-y-2">
      {notes.map(n => (
        <li key={n.id} className="group flex items-start gap-2">
          <span className="min-w-0 flex-1 text-[12px] leading-relaxed [overflow-wrap:anywhere] text-fg-muted">{n.note}</span>
          <button
            aria-label="Forget this note"
            title="Forget this note"
            className="text-gray-500 hover:text-red-500 opacity-0 group-hover:opacity-100 focus:opacity-100 shrink-0 leading-none"
            onClick={() => remove.mutate(n.id)}
          >×</button>
        </li>
      ))}
    </ul>
  )
}

/** What the coach keeps for one plan only: it reads these with the plan, not in every turn. */
export function PlanAgreements({ notes }: { notes: CoachNote[] }) {
  if (!notes.length) return null
  return (
    <section>
      <div className="section-head mb-4"><span className="eyebrow">Agreed for this plan</span></div>
      <div className="panel p-4"><NoteList notes={notes} /></div>
    </section>
  )
}

/** The notes about you the coach reads in every conversation: one line, folded open by topic. */
export function CoachNotes() {
  const { data: notes } = useCoachNotes()
  const [open, setOpen] = useState(false)
  if (!notes) return null
  const known = new Set<string>(TOPICS.map(t => t.key))
  const groups = [
    ...TOPICS.map(t => ({ label: t.label, notes: notes.filter(n => n.topic === t.key) })),
    { label: 'Other', notes: notes.filter(n => !n.topic || !known.has(n.topic)) },
  ].filter(g => g.notes.length)
  return (
    <section>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        aria-expanded={open}
        disabled={!notes.length}
        className={clsx(
          'w-full flex flex-wrap items-baseline gap-x-4 gap-y-2 text-left rounded-xl border px-4 py-3 transition-colors',
          'border-surface-600 hover:border-surface-500',
        )}
      >
        <span className="text-[13px] font-medium text-fg-strong">
          {notes.length ? `The coach keeps ${notes.length} ${notes.length === 1 ? 'note' : 'notes'} about you` : 'The coach hasn\'t noted anything about you yet'}
        </span>
        <span className="flex flex-wrap gap-x-3 gap-y-1 text-[12px] text-gray-500">
          {groups.map(g => <span key={g.label}>{g.label} <span className="font-mono">{g.notes.length}</span></span>)}
        </span>
        {notes.length > 0 && <span className="ml-auto text-[12px] text-gray-500">{open ? 'Hide' : 'Show'}</span>}
      </button>
      {open && (
        <div className="mt-4 space-y-6">
          <p className="text-[11px] text-gray-500">The coach reads these in every conversation. What's agreed for one plan is on that plan's page.</p>
          <div className="grid gap-x-8 gap-y-6 sm:grid-cols-2">
            {groups.map(g => (
              <div key={g.label}>
                <h3 className="text-[12px] font-semibold mb-2 text-fg-strong">{g.label}</h3>
                <NoteList notes={g.notes} />
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}
