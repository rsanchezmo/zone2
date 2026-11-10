---
name: intervals
description: Design an interval, threshold, tempo or race-pace session with its target, guardrail and success criteria, express it as steps z2 can send to the watch, and judge it afterwards. Use when planning a quality session, asked what a session should be, or reviewing one.
---

## The target

- In a goal block, size the session from the goal pace (see race-block for the offsets). `race_predictions`' `training_paces` show where the athlete is now. Show both, and use the goal-derived pace as the target.
- Outside a goal block, size it from `training_paces`, or from predicted times: 5K pace is the predicted 5K time ÷ 5.

| Session | Work | Pace or effort | Recovery |
| --- | --- | --- | --- |
| VO2 reps | 4–6 × 3–5 min, or 5–8 × 800 m–1.2 km | 3K–5K pace, zone 5 | jog 50–90% of the rep time |
| Threshold | 3 × 2 km → 2 × 4 km → an 8–10 km progression | between 10K and half-marathon pace, zone 4 | jog 2–3 min |
| Race pace | 4 × 2 km → 3 × 3 km for a 10K; long blocks for a half or marathon | goal pace | jog 2–2:30 |
| Short reps | 8–12 × 400 m | 1500m–3K pace | jog 1 min |
| Strides | 4–6 × 20 s | building to about 5K pace, relaxed | full recovery |
| Hills | 8–12 × 30–90 s uphill | hard, controlled | jog down |

- Total hard time: about 15–25 minutes of VO2 work, or 20–40 minutes at threshold. Grow the time at threshold through a block, for example 6 km, then 8 km, then a progression into race pace.
- Every quality session gets a warmup of 2–3 km easy plus 4–6 strides, and a cooldown of 1.5–2 km easy.
- Give pace ranges of about ±3–5 s/km around the target, since the watch alerts outside them.

## Every session gets three written lines

1. **Purpose**: what it trains, and how it leads to the race.
2. **Guardrail**: the HR rule that overrides pace. For threshold, "HR above threshold HR before km 3 of a rep: ease 5 s/km". For VO2 reps, peaks near max are normal.
3. **Success**: the pace range, the HR shape, and "easing off under the guardrail still counts".

Put them in the session's `description`, so they travel with it to the calendar.

The last rep of intervals can be pushed. A threshold session can't: racing its last km makes it an all-out effort.

## Write it as steps

A session's `segments` list in order: `warmup`, then `work` with `repetitions` and its recovery (`recovery_duration_mins` or `recovery_distance_km`), then `cooldown`. Paces are decimal minutes per km, where `target_pace_min` is the fast end and `target_pace_max` the slow end. Example: 6 × 1 km at 4:20–4:25/km with 90 s jog:

```json
[
  {"type": "warmup", "distance_km": 2.5},
  {"type": "work", "distance_km": 1.2, "repetitions": 5, "recovery_duration_mins": 2,
   "target_pace_min": 4.33, "target_pace_max": 4.42},
  {"type": "cooldown", "distance_km": 1.5}
]
```

Set `planned_intensity` to "hard" and `planned_distance_km` to the total, warmup and cooldown included. Give a structured session a short title ("6×1 km"), since it becomes a saved workout.

## Judging one afterwards

From `activity_detail`:
- **Reps**, from `laps`: pace and average and max HR per rep, and the fade from the first rep to the last.
- **Within a long rep**, from `splits_km` (per-km pace and HR): whether HR crossed the guardrail, and at which km.
- **Recoveries**: their length against the plan. A lap's `elapsed`, and the `stops` list, show auto-pauses and standing. A traffic-light stop mid-rep splits that rep.
- **`hr_recovery`**: how far HR fell 30 and 60 s after each rep. Compare jogged recoveries only, since walked ones drop far more.
- **Like for like**: the same session type from `workout_history`, on the same HR sensor, with the confounders named.
