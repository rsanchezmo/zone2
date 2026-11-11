import { memo, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  refreshAfterAgentTurn, streamAgentTurn, useAgentConversation, useAgentStatus, useMarkCoachSeen, useOpenCoach,
  type AgentPendingWrite, type AgentStreamEvent, type AgentTranscriptItem, type AgentTurn,
} from '../api/agent'
import { refreshPages } from '../api/invalidation'
import { useTheme } from '../hooks/useTheme'
import { useNow } from '../hooks/useNow'
import { COACH } from '../components/coach/colors'
import { RobotIcon } from '../components/icons'
import { pageContext } from './pageContext'
import { Listener } from './listener'

// The app's one conversation with the coach (backend/agent/conversations.py MAIN)
const CONVERSATION = 'coach'
const REMARK_PLUGINS = [remarkGfm]
// The catch-up before a turn (routers/agent.py) and the coach's own sync_now
const SYNC_STEPS = new Set(['sync', 'sync_now'])

/** Questions to start from, on an empty chat. */
const STARTERS = [
  'How is my plan going?',
  'Review my last run',
  'How recovered am I today?',
  'What should I run this week?',
]

const WRITE_LABEL: Record<string, string> = {
  add_session: 'Add a session',
  change_session: 'Change a session',
  remove_session: 'Remove a session',
  create_plan: 'Create a plan',
  change_plan: 'Change the plan',
  link_sessions: 'Put sessions in the plan',
  add_checkpoint: 'Add a checkpoint',
  record_checkpoint: 'Record a checkpoint',
  resync_watch: 'Send sessions to the watch again',
  add_race: 'Add a race',
  change_race: 'Change a race',
  set_goal: 'Set a goal',
  change_goal: 'Change a goal',
  remove_goal: 'Remove a goal',
  save_workout: 'Save a workout',
  change_workout: 'Change a saved workout',
  remove_workout: 'Delete a saved workout',
}

/** What each tool is doing, in words, while it runs. */
const STEP_LABEL: Record<string, string> = {
  sync: 'Syncing your latest activities',
  today: 'Checking today',
  athlete: 'Reading your zones',
  find_activities: 'Searching your activities',
  activity_detail: 'Opening the activity',
  similar_activities: 'Finding runs like it',
  personal_records: 'Checking your records',
  race_predictions: 'Checking race predictions',
  fitness: 'Checking fitness and form',
  weekly_volume: 'Adding up weekly km',
  planned_sessions_between: 'Reading the calendar',
  races: 'Reading the race calendar',
  wellness: 'Reading Garmin wellness',
  saved_workouts: 'Reading saved workouts',
  workout_history: 'Finding past sessions like it',
  plans_overview: 'Reading your plans',
  plan_detail: 'Reading the plan',
  goals: 'Reading your goals',
  remember: 'Noting that',
  forget: 'Forgetting a note',
  log_entry: "Writing to the coach's log",
  close_suggestion: 'Closing a suggestion',
  sync_now: 'Syncing Strava and Garmin',
  open_page: 'Opening the page',
  gear: 'Reading your gear',
  gear_detail: 'Looking at the pair',
  year_stats: 'Adding up the year',
  totals: 'Adding up all time',
  streaks: 'Counting streaks',
  night: 'Reading the night',
}

/** The capabilities the coach loads with their tools; any other id is a guide. */
const CAPABILITY_LABEL: Record<string, string> = {
  gear: 'Looking at your gear',
  history: 'Looking back at your years',
  workouts: 'Opening the workout library',
}

function stepLabel(tool: string, args?: Record<string, unknown>): string {
  if (tool === 'load_capability') {
    const id = String(args?.id ?? '').replace(/^capability:/, '')
    return CAPABILITY_LABEL[id] ?? `Reading the ${id.replace(/-/g, ' ')} guide`
  }
  return STEP_LABEL[tool] ?? WRITE_LABEL[tool] ?? tool
}

/** A transcript line while a turn runs: tool steps know whether they've finished, and when they ran. */
type LiveItem = AgentTranscriptItem
  | { role: 'step'; tool: string; args?: Record<string, unknown>; running: boolean; startedAt: number; endedAt?: number }
type Step = Extract<LiveItem, { role: 'step' | 'tool' }>

const NO_ITEMS: LiveItem[] = []

const SESSION_AT = new Intl.DateTimeFormat(undefined, { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

type Group = { kind: 'user'; text: string } | { kind: 'agent'; text: string } | { kind: 'session'; at: string }
  | { kind: 'event'; text: string; at: string } | { kind: 'steps'; steps: Step[] }

/** Consecutive tool steps grouped, so a finished turn's tools fold into one line. */
function groups(items: LiveItem[]): Group[] {
  const out: Group[] = []
  for (const item of items) {
    const last = out[out.length - 1]
    if (item.role === 'session') out.push({ kind: 'session', at: item.at })
    else if (item.role === 'event') out.push({ kind: 'event', text: item.text, at: item.at })
    else if (item.role === 'user') out.push({ kind: 'user', text: item.text })
    else if (item.role === 'agent') out.push({ kind: 'agent', text: item.text })
    else if (last?.kind === 'steps') last.steps.push(item)
    else out.push({ kind: 'steps', steps: [item] })
  }
  return out
}

/** How long something took, as "Ys" or "Xm Ys". */
function took(ms: number): string {
  const s = Math.floor(Math.max(0, ms) / 1000)
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`
}

const TIME_CLASS = 'font-mono tabular-nums opacity-60'

/** Time since `since`, ticking; its own component so the clock re-renders only itself. */
function Elapsed({ since }: { since: number }) {
  const now = useNow(250)
  return <span className={TIME_CLASS}>{took(now - since)}</span>
}

/** A step's time: live while the turn runs, final once done; past turns loaded from the server have none. */
function StepTime({ step, live }: { step: Step; live: boolean }) {
  if (step.role !== 'step') return null
  if (step.endedAt != null) return <span className={TIME_CLASS}>{took(step.endedAt - step.startedAt)}</span>
  return live ? <Elapsed since={step.startedAt} /> : null
}

/** A reply, memoised so a streamed token or a keystroke re-parses only the reply being written. */
const AgentReply = memo(function AgentReply({ text, coach }: { text: string; coach: string }) {
  return (
    <div className="flex gap-2.5">
      <span className="w-6 h-6 mt-0.5 rounded-full flex items-center justify-center shrink-0" style={{ backgroundColor: `${coach}22`, color: coach }} aria-hidden="true">
        <RobotIcon size={13} />
      </span>
      <div className="agent-markdown min-w-0 flex-1">
        <Markdown remarkPlugins={REMARK_PLUGINS}>{text}</Markdown>
      </div>
    </div>
  )
})

/** A one-line reading of a write, from its arguments. */
function describe(write: AgentPendingWrite): string {
  const a = write.args as Record<string, Record<string, unknown> | unknown>
  const session = (a.session ?? a.changes) as Record<string, unknown> | undefined
  const parts = [
    session?.title, session?.date, a.session_id != null && `session ${a.session_id}`,
    (a.plan as Record<string, unknown> | undefined)?.name, (a.race as Record<string, unknown> | undefined)?.name,
    (a.race as Record<string, unknown> | undefined)?.date, a.title, a.day,
  ].filter(Boolean)
  if (a.changes && typeof a.changes === 'object') parts.push(Object.keys(a.changes).join(', '))
  return parts.map(String).join(' · ')
}

// The waveform's bars: where each sits, how tall it is at rest, and how much it follows the voice
const BARS = [{ x: 4, rest: 3, gain: 0.55 }, { x: 8, rest: 9, gain: 0.8 }, { x: 12, rest: 15, gain: 1 }, { x: 16, rest: 9, gain: 0.8 }, { x: 20, rest: 3, gain: 0.55 }]

/** The mic's icon; while it listens, the bars follow how loud you are (the `--level` CSS variable). */
function Waveform({ live }: { live: boolean }) {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      {BARS.map(({ x, rest, gain }) => (
        <line
          key={x}
          x1={x} x2={x} y1={live ? 4.5 : 12 - rest / 2} y2={live ? 19.5 : 12 + rest / 2}
          style={live ? { transformBox: 'fill-box', transformOrigin: 'center', transition: 'transform 60ms linear', transform: `scaleY(calc(0.12 + ${gain * 0.88} * var(--level, 0)))` } : undefined}
        />
      ))}
    </svg>
  )
}

/** Dictated words after what was already typed. */
function joined(typed: string, said: string): string {
  return [typed, said].filter(Boolean).join(' ')
}

/** The message box and the mic. Mounted only while the chat is open, so closing it, from
 *  anywhere, drops what the mic was hearing. */
function Composer({ draft, onDraft, onSend, busy, offline, onError }: {
  draft: string
  onDraft: (draft: string) => void
  onSend: () => void
  busy: boolean
  offline: boolean
  onError: (message: string | null) => void
}) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const [listening, setListening] = useState(false)
  // Let go, until the words are settled
  const [settling, setSettling] = useState(false)
  const listener = useRef<Listener | null>(null)
  const typed = useRef('')
  const pressedAt = useRef(0)
  const mic = useRef<HTMLButtonElement>(null)
  const input = useRef<HTMLTextAreaElement>(null)

  useEffect(() => () => listener.current?.cancel(), [])

  // The box grows with what's in it, typed or dictated
  useEffect(() => {
    const box = input.current
    if (!box) return
    box.style.height = ''
    if (draft) box.style.height = `${box.scrollHeight}px`
  }, [draft])

  function submit() {
    if (listening || settling) return
    onSend()
  }

  /** Hold the mic to talk, or tap to start and tap again to stop. The words appear in the box
   *  as you say them and stay there, to fix and send. */
  function startListening() {
    if (listening || settling) return
    onError(null)
    typed.current = draft.trim()
    const heard = new Listener({
      level: value => mic.current?.style.setProperty('--level', value.toFixed(2)),
      caption: text => onDraft(joined(typed.current, text)),
      final: text => {
        listener.current = null
        onDraft(joined(typed.current, text))
        setListening(false)
        setSettling(false)
        // Ready to send with Enter; on a touch screen the keyboard would cover the panel
        if (window.matchMedia('(pointer: fine)').matches) requestAnimationFrame(() => {
          const box = input.current
          box?.focus()
          box?.setSelectionRange(box.value.length, box.value.length)
        })
      },
      error: message => {
        listener.current = null
        onError(message)
        setListening(false)
        setSettling(false)
      },
    })
    listener.current = heard
    setListening(true)
    void heard.start()
  }

  function stopListening() {
    listener.current?.stop()
    setListening(false)
    setSettling(true)
  }

  return (
    <form
      className="border-t border-surface-600 p-3 flex items-end gap-2"
      onSubmit={e => { e.preventDefault(); submit() }}
    >
      <textarea
        ref={input}
        value={draft}
        onChange={e => onDraft(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }}
        rows={1}
        placeholder={offline ? 'Not connected' : listening ? 'Listening…' : settling ? 'Writing down what you said…' : 'Message or hold the mic to talk'}
        readOnly={listening || settling}
        disabled={offline}
        className={clsx(
          'flex-1 resize-none rounded-lg px-3 py-2 text-[13px] outline-none max-h-40 disabled:opacity-50',
          'bg-surface-700 placeholder:text-gray-500',
        )}
      />
      {draft.trim() && !listening && (
        <button type="submit" disabled={busy || offline || settling} className="text-[12px] font-medium text-[var(--coach)] disabled:text-gray-500 px-1 py-2">Send</button>
      )}
      {/* Last in the row, so Send coming and going never moves it from under a held press */}
      <button
        ref={mic}
        type="button"
        disabled={offline || settling}
        aria-label={listening ? 'Stop listening' : 'Hold to talk'}
        title={listening ? 'Release, or tap, to stop' : 'Hold to talk, or tap to start'}
        aria-pressed={listening}
        onPointerDown={e => {
          e.preventDefault()
          if (listening) return stopListening()
          // The release counts even if the pointer slides off the button
          e.currentTarget.setPointerCapture(e.pointerId)
          pressedAt.current = Date.now()
          startListening()
        }}
        onPointerUp={() => { if (listening && Date.now() - pressedAt.current > 350) stopListening() }}
        className={clsx(
          'w-9 h-9 shrink-0 rounded-full flex items-center justify-center transition-colors disabled:opacity-40 touch-none select-none',
          listening ? 'bg-red-500 text-white' : isLight ? 'text-gray-600 hover:bg-surface-700' : 'text-gray-300 hover:bg-surface-700',
          settling && 'animate-pulse',
        )}
      >
        <Waveform live={listening} />
      </button>
    </form>
  )
}

/** The conversation inside the dock's panel. Loaded on first open and kept mounted after, so a
 *  turn still running when the panel closes goes on filling the transcript. */
export default function AgentChat({ open, expanded, busy, onBusyChange, onOpenPage }: {
  open: boolean
  expanded: boolean
  /** A turn is running; the dock owns it, since its button pulses while the panel is closed. */
  busy: boolean
  onBusyChange: (busy: boolean) => void
  onOpenPage: (path: string) => void
}) {
  const { theme } = useTheme()
  const isLight = theme === 'light'
  const qc = useQueryClient()
  const location = useLocation()
  const page = pageContext(location.pathname, location.search)
  const { data: status } = useAgentStatus()
  const { data: history } = useAgentConversation(open ? CONVERSATION : null)
  const { mutate: markSeen } = useMarkCoachSeen()
  const unread = status?.unread ?? 0
  // Opening the chat, or a review arriving while it's open, reads what the coach wrote
  useEffect(() => {
    if (!open || unread === 0) return
    markSeen()
    qc.invalidateQueries({ queryKey: ['agent-conversation', CONVERSATION] })
  }, [open, unread, markSeen, qc])
  const { mutate: prepare } = useOpenCoach()
  // Stale data syncs while the athlete types, so their first message doesn't wait for it
  useEffect(() => {
    if (open) prepare()
  }, [open, prepare])
  const [items, setItems] = useState<LiveItem[] | null>(null)
  const [pending, setPending] = useState<AgentPendingWrite[] | null>(null)
  const [turnStartedAt, setTurnStartedAt] = useState(0)
  const [thinking, setThinking] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const scroller = useRef<HTMLDivElement>(null)

  // The conversation lives on the server and another device may have continued it: coming back
  // to the chat (reopening it, or returning to the tab) shows the server's copy again
  const busyNow = useRef(busy)
  useEffect(() => {
    busyNow.current = busy
  }, [busy])
  const openedBefore = useRef(false)
  useEffect(() => {
    if (!open) return
    async function resync() {
      if (busyNow.current) return
      await qc.refetchQueries({ queryKey: ['agent-conversation', CONVERSATION] })
      if (busyNow.current) return
      setItems(null)
      setPending(null)
    }
    // The first open loads the conversation through its query
    if (openedBefore.current) void resync()
    openedBefore.current = true
    const onVisible = () => {
      if (document.visibilityState === 'visible') void resync()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [open, qc])

  const transcript: LiveItem[] = items ?? history?.messages ?? NO_ITEMS
  const grouped = useMemo(() => groups(transcript), [transcript])
  const waiting = pending ?? history?.pending ?? []
  const offline = status != null && !status.available

  // Follow the conversation as it grows, including a reply still being written
  const last = transcript[transcript.length - 1]
  const growth = `${transcript.length}:${last && 'text' in last ? last.text.length : 0}`
  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight })
  }, [growth, waiting.length, busy, open, expanded])

  /** Fold one streamed event into the live transcript. */
  function apply(event: AgentStreamEvent) {
    if (event.type === 'thinking') return setThinking(true)
    if (event.type === 'open') return onOpenPage(event.path)
    setThinking(false)
    // Outside the state update, which React may run twice
    if (event.type === 'tool_done' && SYNC_STEPS.has(event.tool)) refreshPages(qc)
    const at = Date.now()
    setItems(prev => {
      const next = [...(prev ?? [])]
      const last = next[next.length - 1]
      if (event.type === 'tool') next.push({ role: 'step', tool: event.tool, args: event.args, running: true, startedAt: at })
      else if (event.type === 'tool_done') {
        const i = next.findIndex(it => it.role === 'step' && it.tool === event.tool && it.running)
        if (i >= 0) next[i] = { ...(next[i] as Extract<LiveItem, { role: 'step' }>), running: false, endedAt: at }
      } else if (event.type === 'text') {
        if (last?.role === 'agent') next[next.length - 1] = { role: 'agent', text: last.text + event.delta }
        else next.push({ role: 'agent', text: event.delta })
      }
      return next
    })
  }

  async function run(path: 'chat' | 'approve', body: Parameters<typeof streamAgentTurn>[1], before: LiveItem[]) {
    setItems(before)
    setPending([])
    setError(null)
    setTurnStartedAt(Date.now())
    onBusyChange(true)
    setThinking(true)
    try {
      const turn: AgentTurn = await streamAgentTurn(path, body, apply)
      setPending(turn.pending)
      refreshAfterAgentTurn(qc, turn)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      // What ran before a failure is saved on the server: ask it what still waits, rather than
      // offering the same yes again
      if (path === 'approve') {
        setPending(null)
        qc.invalidateQueries({ queryKey: ['agent-conversation', CONVERSATION] })
      }
    } finally {
      onBusyChange(false)
      setThinking(false)
    }
  }

  function send() {
    const message = draft.trim()
    if (!message || busy) return
    setDraft('')
    run('chat', { message, conversation_id: CONVERSATION, page }, [...transcript, { role: 'user', text: message }])
  }

  function answer(approvals: Record<string, boolean>) {
    if (busy) return
    run('approve', { conversation_id: CONVERSATION, approvals, page }, transcript)
  }

  if (!open) return null

  const coach = isLight ? COACH.light : COACH.dark
  const running = transcript.some(it => it.role === 'step' && it.running)
  const writing = busy && transcript[transcript.length - 1]?.role === 'agent'

  return (
    <>
      <div ref={scroller} className={clsx('flex-1 overflow-y-auto px-4 py-3 space-y-3 leading-relaxed', expanded ? 'text-[14px]' : 'text-[13px]')}>
        {transcript.length === 0 && !busy && (
          offline ? (
            <p className="text-[12px] text-gray-500">The coach isn't connected: there's no key for {status?.model}.</p>
          ) : (
            <div className="space-y-3">
              <p className="text-[12px] text-gray-500">Ask about your training, or tell it what to change: "I can't run Friday, move it".</p>
              <div className="flex flex-wrap gap-2">
                {STARTERS.map(q => (
                  <button
                    key={q}
                    type="button"
                    onClick={() => run('chat', { message: q, conversation_id: CONVERSATION, page }, [{ role: 'user', text: q }])}
                    className="rounded-full border px-3 py-1 text-[12px] transition-colors hover:bg-[color-mix(in_srgb,var(--coach)_12%,transparent)]"
                    style={{ borderColor: `${coach}55`, color: coach }}
                  >{q}</button>
                ))}
              </div>
            </div>
          )
        )}
        {grouped.map((group, g) => {
          if (group.kind === 'user') return (
            <div key={g} className="flex justify-end">
              <div
                className={clsx('max-w-[85%] rounded-2xl rounded-br-md px-3 py-2 whitespace-pre-wrap', isLight ? 'text-gray-900' : 'text-gray-50')}
                style={{ backgroundColor: `${coach}${isLight ? '1f' : '29'}` }}
              >{group.text}</div>
            </div>
          )
          if (group.kind === 'event') return (
            <div key={g} className="flex items-center gap-3 text-[10px] pt-2" style={{ color: coach }}>
              <span className="flex-1 h-px bg-current opacity-30" aria-hidden="true" />
              {group.text} · {SESSION_AT.format(new Date(group.at))}
              <span className="flex-1 h-px bg-current opacity-30" aria-hidden="true" />
            </div>
          )
          if (group.kind === 'session') return (
            <div key={g} className="flex items-center gap-3 text-[10px] text-gray-500 pt-2" title="After a pause the coach starts fresh, from your notes and its log">
              <span className="flex-1 h-px bg-current opacity-20" aria-hidden="true" />
              New session · {SESSION_AT.format(new Date(group.at))}
              <span className="flex-1 h-px bg-current opacity-20" aria-hidden="true" />
            </div>
          )
          if (group.kind === 'agent') return <AgentReply key={g} text={group.text} coach={coach} />
          const live = busy && g === grouped.length - 1
          const lines = group.steps.map((step, i) => {
            const running = step.role === 'step' && step.running
            return (
              <div key={i} className={clsx('flex items-center gap-2 text-[11px]', running ? 'text-fg' : 'text-gray-500')}>
                <span className={clsx('w-1.5 h-1.5 rounded-full shrink-0', running ? 'bg-[var(--coach)] animate-pulse' : 'bg-surface-500')} aria-hidden="true" />
                {stepLabel(step.tool, step.role === 'step' ? step.args : undefined)}
                <StepTime step={step} live={live} />
              </div>
            )
          })
          const first = group.steps[0], lastStep = group.steps[group.steps.length - 1]
          const groupTime = first.role === 'step' && lastStep.role === 'step' && lastStep.endedAt
            ? took(lastStep.endedAt - first.startedAt) : null
          // Steps show one by one while they run, then fold into a line you can open
          return live ? <div key={g} className="space-y-1">{lines}</div> : (
            <details key={g} className="group text-[11px] text-gray-500">
              <summary className="cursor-pointer list-none flex items-center gap-2 hover:text-gray-300">
                <span className="w-1.5 h-1.5 rounded-full shrink-0 bg-surface-500" aria-hidden="true" />
                {group.steps.length === 1 ? stepLabel(group.steps[0].tool, group.steps[0].role === 'step' ? group.steps[0].args : undefined) : `Looked at ${group.steps.length} things`}
                {groupTime && <span className={TIME_CLASS}>{groupTime}</span>}
                {group.steps.length > 1 && <span className="opacity-60 group-open:rotate-90 transition-transform">›</span>}
              </summary>
              {group.steps.length > 1 && <div className="mt-1 ml-3.5 space-y-1">{lines}</div>}
            </details>
          )
        })}
        {busy && !running && !writing && (
          <div className="flex items-center gap-2 text-[11px] text-gray-500" aria-live="polite">
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--coach)] animate-pulse" aria-hidden="true" />
            {thinking ? 'Thinking' : 'Working'}
            <Elapsed since={turnStartedAt} />
          </div>
        )}
        {waiting.length > 0 && !busy && (
          <div className={clsx('rounded-xl border p-3 space-y-2', isLight ? 'border-amber-500/50' : 'border-amber-500/40')}>
            <div className="eyebrow text-amber-500">Needs your yes</div>
            {waiting.map(w => (
              <div key={w.id} className="space-y-1">
                <div className="text-[12px]">
                  <span className="font-medium">{WRITE_LABEL[w.tool] ?? w.tool}</span>
                  {describe(w) && <span className="text-gray-500"> · {describe(w)}</span>}
                </div>
                {typeof w.args.reason === 'string' && <div className="text-[11px] text-gray-500">{w.args.reason}</div>}
                {waiting.length > 1 && (
                  <button
                    className="text-[11px] text-gray-500 hover:text-[var(--coach)]"
                    onClick={() => answer(Object.fromEntries(waiting.map(o => [o.id, o.id === w.id])))}
                  >Yes to only this one</button>
                )}
              </div>
            ))}
            <div className="flex gap-4 pt-1 text-[12px]">
              <button className="font-medium text-[var(--coach)] hover:opacity-80" onClick={() => answer(Object.fromEntries(waiting.map(w => [w.id, true])))}>
                {waiting.length > 1 ? `Yes to all ${waiting.length}` : 'Yes'}
              </button>
              <button className="text-gray-500 hover:text-gray-300" onClick={() => answer(Object.fromEntries(waiting.map(w => [w.id, false])))}>No</button>
            </div>
          </div>
        )}
        {error && <div className="text-[12px] text-red-500">{error}</div>}
      </div>

      <Composer draft={draft} onDraft={setDraft} onSend={send} busy={busy} offline={offline} onError={setError} />
    </>
  )
}
