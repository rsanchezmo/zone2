---
name: coaching-a-block
description: Run a race block week to week. Brief each key session before it, review it afterwards against its target and guardrail, and adapt the next sessions from the result and the morning's recovery. Use for "what's today's workout", "I finished, check it", "how did it go", "should I still do X", "what HR should I see".
---

## Before a key session

Read `today` and this week's `planned_sessions_between` first. The athlete may have moved sessions without saying. Then brief in this order:

1. **Purpose.** One line tied to the race. Example: "Threshold: raises the pace you can hold for 10 km, so goal pace becomes sustainable." Say how it builds on the last session of its type (time at threshold 6 km → 8 km).
2. **The session.**
   - The warmup, 2–3 km easy, ends with 4–6 strides. A stride is 20 s building to about 5K pace, with full recovery.
   - The reps with their target pace, and the recoveries.
   - The cooldown, 1.5–2 km easy.
3. **HR to expect, km by km.** HR lags pace for the first 1–2 minutes of a rep. Later reps run 3–4 bpm higher at the same point.
4. **The guardrail**, the rule that overrides pace. Example: "HR above threshold HR before km 3 of a rep: ease 5 s/km. Near max: back off now." Easing off under the guardrail still counts as a success.
5. **What success looks like**: pace within the range, the HR shape, and the feel ("could have done one more").
6. **What not to do**: run faster than target because it feels easy, skip the strides, or race the last km of a threshold session.
7. **Recovery check.**
   - Read readiness, HRV last night against its band (see reading-z2), sleep and body battery.
   - If they're soft, keep the session and tighten the guardrail.
   - Give a warmup check, for example "HR more than 10 bpm above your easy baseline at easy pace: do the shorter version".
   - Skip only for signs of illness.

## After a session

1. Read `activity_detail`: laps per rep (pace, average and max HR, `elapsed` where pauses stretched a lap), splits, `hr_recovery`, `stops`, and drift on easy runs.
2. Lead with the verdict, then a table per rep or per km.
3. Judge the run against the written target and guardrail. Name a broken rule plainly, with its cost. A raced last km in a threshold session turns it into an all-out effort, and brings extra fatigue into the next hard day.
4. Compare with the last session of the same type, from `workout_history` or `find_activities` by name. It must be on the same HR sensor; check the notes for sensor changes. Name the confounders: relative temperature, recovery length, pace difference, fatigue.
5. For recoveries, compare planned with actual. Stops and auto-pauses shorten moving time, so a jog with a friend reads as stopped. Compare the HR drop in a jogged minute with the last comparable session.
6. Set the rule for the next session from this one. Example: "If HRV is still under its band tomorrow morning, run the long run all easy."
7. Update the prediction trend from z2's weekly prediction. Garmin's daily one drifts ±10 s, so ignore single days.
8. `remember` anything durable the session taught: a new baseline, a habit, a sensor change.

## Adapting the block

- **Soft recovery** (HRV under its band 3+ nights, or readiness MODERATE or lower): trim volume and drop fast finishes first. Protect the checkpoint session. One bad night is noise.
- **Checkpoints move the target.** Apply the block's written thresholds, which are in the notes or on the plan. Don't improvise a new goal mid-week.
- **When the athlete moves a session**, re-check the spacing:
  - 48 h between runs.
  - No racquet or team sport, and no heavy leg work, the day before quality.
  - Never a test the day after a long run or a racquet sport.
  - Move an adjacent easy run rather than stack two days.
- **Other sports are load.** Read them from the calendar and the activities, not just the runs.
- **After moving a session**, check its `garmin_sync_state`. If it says failed, use `resync_watch`.
