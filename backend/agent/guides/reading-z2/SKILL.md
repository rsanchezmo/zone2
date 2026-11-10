---
name: reading-z2
description: What z2's numbers mean and where they mislead — fitness/form, race predictions, personal records, HR drift and recovery, pauses, HR sensors, Garmin HRV and readiness. Use before interpreting any metric or judging progress.
---

## Fitness, fatigue and form

- **Fitness** is the 42-day average of daily training load (TRIMP from heart rate). **Fatigue** is the 7-day average. **Form** is fitness minus fatigue, as a share of fitness (`form_pct`).
- **Form zones:**
  - below −30%: overreaching, back off;
  - −30% to +5%: productive training;
  - +5% to +20%: fresh, good for a race;
  - above +20%: stale, rested long enough that fitness fades.
- Days marked `projected` come from the planned sessions, not from real data.

## Race predictions and records

- **z2's race predictor** fits the athlete's recent best efforts and averages about 3% off on real races. Give its range, not just the point.
- **Two predictions:**
  - z2's is weekly and steady; use it for trends.
  - Garmin's daily prediction (`race_predictions` in wellness) drifts ±5–10 s with easy days and HRV. Don't read single days.
- **The fade exponent** (how much pace drops as distance grows) is fragile. Report it with its SE.
- **Records:**
  - `current_best` in the predictions is the best in the recent window.
  - All-time records come from `personal_records`. Check them before calling anything a PR.
  - Strava's PR count includes segment PRs.
- **Races** are the race calendar's events (and Strava's race flag).

## Heart rate

- **HR sensor changes break comparisons.** HR from the wrist and from a strap or armband differ. Never compare HR across a sensor change; the notes record when it happened.
- **HR drift (decoupling)** is how much HR rose at a steady grade-adjusted pace. Under about 5% on a long easy run means good aerobic fitness. It's unreliable on runs with stops, hills or a varying pace, and the tool says when it can't judge.
- **HR recovery** is how far HR fell 30 and 60 s after each rep. Compare it only between sessions with jogged recoveries. Walked recoveries drop far more, by a wide margin.
- **`average_temp`** comes from the watch on the wrist, warmed by the body. Only relative comparisons hold.
- **Cadence:** Garmin's summary cadence counts both feet, while per-stream cadence counts one.

## Pauses and stops

- Auto-pause stops the clock on a slow jog or while standing, so a recovery's moving time looks shorter than it was. A lap's `elapsed` and the activity's `stops` show the real length.
- A stop mid-rep, such as a traffic light, splits the rep. Judge the two halves together.

## Garmin HRV, readiness and wellness

- **HRV:** `status` (BALANCED, UNBALANCED, LOW, POOR) is a 7-day verdict and lags. Judge last night's `last_night_avg` against the athlete's band (`balanced_low`, `balanced_upper`, `low_upper`), plus the trend over several nights. z2's own suggestion in `today` uses the status, so it lags too.
- **Training readiness** runs POOR, LOW, MODERATE, HIGH, PRIME. Judge the day on the morning value (`at_wakeup`). `recovery_time_min` is Garmin's own estimate of the hours still needed.
- **Telling load from life stress:** training_status's acute load against chronic load. Low HRV with a normal load points to sleep, stress or illness, not training.
- **Resting HR** a few bpm above the athlete's usual, together with poor sleep, is a reason to keep the day easy.
- **Missing wellness:** days the watch wasn't worn or hasn't synced have no data. Say so instead of reading the gap as a change.
