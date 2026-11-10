# z2 agent

One agent for all of z2: it knows your whole history, can see the page you're on, and can act on your data. You type or talk to it, whichever you prefer, in the same conversation.

Built so far: the agent, with read tools over all of z2 and approved writes; the coaching guides; the Coach page; the chat panel on every page, typed or spoken; a terminal chat; and its cost on the Profile page. Not yet built: live coaching on the run.

## Try it

Add `OPENAI_API_KEY=…` to `.env`, then, from the repo root:

```bash
poetry run python -m backend.agent chat                     # a conversation; approve writes as they come
poetry run python -m backend.agent ask "…" [-c ID]          # one turn; -c continues a conversation
poetry run python -m backend.agent approve -c ID [--deny …] # answer the writes a turn asked approval for
poetry run python -m backend.agent call TOOL '{"arg": 1}'   # run one tool through the agent, no model
poetry run python -m backend.agent tools                    # what the model sees
poetry run python -m backend.agent notes [add TEXT | rm ID]  # what it keeps about the athlete
```

- **Model.** It's `STRAVA_WEB_AGENT_MODEL`, default `openai:gpt-6-luna`. `--model` overrides it for one run, for example `openai:gpt-6.1-terra`, or a local model with `ollama:<model>` and `OLLAMA_BASE_URL`.
- **Garmin.** Calendar writes from the terminal don't push to Garmin unless you pass `--push-garmin`. This machine's calendar isn't the one the watch follows.
- **Cost.** Each turn's cost is recorded and shown under Agent on the Profile page.

## What it does

| Pillar | You say | The agent |
| --- | --- | --- |
| **Ask** | "What's my 10K PR this year?" "Is my HR recovery improving?" "Am I fitter than two years ago?" | Answers from your history: records, predictions, fitness and form, HR drift and recovery, Garmin wellness |
| **Plan** | "Get me ready for a 10K in ten weeks." "I run Mon/Wed/Sun, but this Wednesday I can't." | Builds and reshapes the plan around your days and rest, writes sessions to the calendar, and sends workouts to the watch |
| **Go** | "A 10K loop from home, mostly new streets." | Plans a route and sends it to the watch as a course |
| **Play** | "How do I finish this neighbourhood?" "Write my initials on the map." | Plans runs over the streets you're missing, and GPS art |
| **Run** (later) | "Let's do the intervals." | Coaches the session live from the plan. This builds on the live session and runner sim in the `z2-agent` repo |

Nothing else combines the whole loop: plan by conversation, write to the calendar and watch, coach live from that plan, reroute mid-run, and play the city. Chat plan coaches (Type to Run, 26weeks.ai, Runcaster) and Garmin Coach each cover one part.

## How it works

- **The agent sees your page.**
  - Each page tells the agent what it shows, such as run 1234, the calendar week of 10 Nov, or a neighbourhood's coverage. That context goes with every message, so "this run" or "move this one" resolve on their own.
  - The agent's tools still reach all of your data, not just the page.
  - After a write, the agent tells the frontend which data changed and the page refreshes. It can also open a page ("show me that run").
- **One conversation, typed or spoken.**
  - A message sent when Strava or Garmin last synced over 15 minutes ago first runs a quick sync, shown as a step, so the coach sees the run you just finished. The reply waits up to 20 seconds for it; a slower sync finishes in the background.
  - The app keeps a single conversation. The model sees only its current session: a message after a 30-minute pause starts fresh, with the last few exchanges carried over, plus the notes and the coach's log.
  - Voice is a mode, not a second agent: hold the mic and your words are transcribed into the same chat. The reply is read aloud sentence by sentence as it streams, and voice replies are kept short.
  - A realtime speech model is only worth it for live coaching on the run, and it would use the same tools.
- **The plan changes only when you ask.**
  - The agent changes the plan or the calendar only for a change you asked for in conversation, such as "I can't run Friday, move it". You approve each write.
  - When it thinks something should change, it says so. When you're not in the conversation, it logs a suggestion instead.
  - Every change is logged on the Coach page with the reason and the before and after.
- **The Coach page** (`/coach`) shows each plan in one view:
  - the race, the goal against the prediction, and the phases;
  - sessions done and the average execution score (z2's own, which the agent can't edit);
  - km per week against the plan;
  - checkpoints with the rules agreed before them;
  - sessions week by week;
  - the coach's log: reviews, changes, decisions and suggestions;
  - what the coach knows about you.
- **Writes need a yes.** A write tool returns a draft, the panel shows it as a confirm card, and only the confirm applies it.
- **Tools call services, never routers.** Tools are typed Python functions (Pydantic in and out) over `backend/services/`. Where logic sits in a router today, it moves into a service when a tool needs it, so the router and the tool share it.
- **What it knows about you lives in notes.** These are facts z2's data doesn't hold: preferences, constraints, baselines, sensor changes, and the plan's agreed thresholds. Every turn sees them. The agent adds and drops notes as it learns (`remember`, `forget`), and you can edit them with the `notes` command.
- **Coaching know-how lives in guides.**
  - Guides are playbooks the agent loads only when a question needs them:
    - building a race block with checkpoints;
    - coaching it week to week (briefing and reviewing key sessions);
    - moving sessions without stacking hard days;
    - designing intervals;
    - reading z2's metrics and their caveats.
  - The coaching method comes from coaching a real 10K block.
  - Each guide is a folder with a `SKILL.md`. The instructions list the guides, and the agent reads one in full when the conversation calls for it.
- **MCP comes later, as a thin adapter.** The agent calls its tools in-process. An MCP server over the same functions is only needed to use z2 from other AI apps, such as Claude or ChatGPT.

## Layout

```
backend/agent/
  agent.py          the agent: instructions, tools, guides; run_turn stores and accounts each turn
  instructions.md   the coaching prompt
  tools.py          read tools over z2's services, and the calendar writes (each needs approval)
  guides/           coaching playbooks, one SKILL.md folder each, loaded on demand (pydantic-ai-harness Skills)
  notes.py          what it keeps about the athlete (preferences, baselines, sensor changes, plan thresholds), in every turn
  conversations.py  message history per conversation, in calendar.db
  usage.py          tokens and cost per turn, in calendar.db; imports nothing from Pydantic AI
  __main__.py       the terminal chat
backend/routers/agent.py   GET /api/agent/usage (later: text chat, voice, confirm)
backend/routers/coach.py   the Coach page's API: plans with progress, the coach's log, notes
backend/services/plans.py, coach_log.py, session_scores.py   plans and their progress, the log, and session scoring (shared with the calendar)
frontend/src/pages/CoachPage.tsx, components/coach/        the Coach page
frontend/src/components/profile/AgentUsage.tsx   the agent's cost on the Profile page
```

Later: `frontend/src/agent/` for the button, the transcript panel, mic and playback, and the page-context hook.

The agent button sits bottom-right on every page. It's a flat dark disc with a waveform icon, red while offline, with no glow and no toasts. Clicking it opens a transcript card upward from the button: your words as a live caption, the agent's reply streaming in, tool calls as chips, confirm cards for writes, and a text box to type instead.

## Build order

1. **Tools and the agent, with a terminal chat** (done): reads over all of z2, and calendar writes that need approval.
2. **The Coach page** (done): plans, checkpoints and the coach's log, which the agent writes through its tools.
3. **The text panel with page context**, starting on the Coach page.
4. **More writes**: saved workouts, races and courses, with confirm cards in the panel.
5. **Voice** (done, push-to-talk).
6. **Live coaching**, using the live session and sim from `z2-agent`.
7. **Play**: conquer an area, then GPS art (z2 has no shape-to-streets planner yet).

## Open questions

- Which model and provider, for text and for voice.
- Whether notes are enough memory, or the agent should also learn from how you answered its suggestions.
- A readiness signal combined from Garmin's sleep, HRV and body battery, for "tired today" swaps.
