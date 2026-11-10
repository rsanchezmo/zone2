---
name: coaching-a-block
description: Run a race block week to week. Brief each key session, review it against its target and guardrail, and adapt the next sessions from the result and the morning's recovery. Use for "what's today's workout", "I finished, check it", "how did it go", "should I still do X", "what HR should I see".
---

## Before a key session

Read `today` and this week's `planned_sessions_between` first: the athlete may have moved sessions without saying. Then brief, in order:

1. **Purpose**: one line tied to the race, and how it builds on the last session of its type (time at threshold 6 km → 8 km).
2. **The session**: a warmup of 2–3 km easy ending with 4–6 strides (20 s building to about 5K pace, full recovery); the reps with their target pace and recoveries; a cooldown of 1.5–2 km easy.
3. **HR to expect, km by km.** HR lags pace for the first 1–2 minutes of a rep. Later reps run 3–4 bpm higher at the same point.
4. **The guardrail**, the rule that overrides pace, e.g. "HR above threshold HR before km 3 of a rep: ease 5 s/km. Near max: back off now." Easing off under it still counts as a success.
5. **Success**: pace within the range, the HR shape, and the feel ("could have done one more").
6. **What not to do**: run faster than target because it feels easy, skip the strides, or race the last km of a threshold session.
7. **Recovery check**: readiness, HRV last night against its band (see reading-z2), sleep and body battery. If they're soft, keep the session, tighten the guardrail and give a warmup check ("HR more than 10 bpm above your easy baseline at easy pace: do the shorter version"). Skip only for signs of illness.

## After a session

1. Read `activity_detail`: laps per rep (pace, average and max HR, `elapsed` where pauses stretched a lap), splits, `hr_recovery`, `stops`, and drift on easy runs.
2. Verdict first, then a table per rep or per km.
3. Judge it against the written target and guardrail. Name a broken rule plainly, with its cost: a raced last km turns a threshold session into an all-out effort, and brings extra fatigue into the next hard day.
4. Compare with the last session of its type, from `workout_history` or `find_activities` by name, on the same HR sensor (the notes record sensor changes). Name the confounders: relative temperature, recovery length, pace difference, fatigue.
5. Recoveries: planned against actual. Stops and auto-pauses shorten moving time, so a jog with a friend reads as stopped. Compare the HR drop in a jogged minute with the last comparable session.
6. Set the rule for the next session from this one, e.g. "If HRV is still under its band tomorrow morning, run the long run all easy."
7. Update the prediction trend from z2's weekly prediction. Garmin's daily one drifts ±10 s, so ignore single days.
8. `remember` anything durable it taught: a new baseline, a habit, a sensor change.

## Adapting the block

- **Soft recovery** (HRV under its band 3+ nights, or readiness MODERATE or lower): trim volume and drop fast finishes first. Protect the checkpoint session. One bad night is noise.
- **Checkpoints move the target.** Apply the block's written thresholds: its checkpoints and agreements in plan_detail. Don't improvise a new goal mid-week.
- **Read the metric a rule names.** A rule can turn on a z2 metric rather than the session itself: "the fade exponent picks week 4" is the `fade` verdict in race_predictions, not whether the time trial held its pace. Look the metric up before deciding, and quote it with its verdict.
- **When the athlete moves a session**, re-check the spacing: 48 h between runs; no racquet or team sport, and no heavy leg work, the day before quality; never a test the day after a long run or a racquet sport. Move an adjacent easy run rather than stack two days.
- **Other sports are load.** Read them from the calendar and the activities, not just the runs.
- **After moving a session**, check its `garmin_sync_state`. If it failed, use `resync_watch`.
