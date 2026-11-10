---
name: rescheduling
description: Move, swap or drop planned sessions when the week changes (a day they can't train, a missed session, feeling tired, a race moved, another sport booked), keeping hard and easy days apart. Use for "I can't run Wednesday", "I missed…", "I'm tired today", "move my long run".
---

## First, re-read the week

The athlete edits the calendar themselves. Before proposing anything, read `planned_sessions_between` for that Monday to Sunday (plus the next week when the change is near the end), `races`, and `today` when the change is about today. Other sports in the calendar count.

## Rules that protect the week

- **Never two hard days back to back.** Hard means a quality session (intervals, threshold, tempo), a long run, a race or a test.
- **Spacing:** 48 h between runs where the week allows it, and always between quality sessions. No long run the day after a quality session.
- **Other sports are load.**
  - No racquet or team sport the day before a quality run. The day after intervals is fine, and so is an easy game before a tempo.
  - No heavy leg strength work within 48 h before quality.
- **Never put a test or checkpoint** the day after a long run or a racquet sport: a tired test wrongly lowers the target.
- **When the week loses a day**, drop volume before intensity: an easy run goes first, then shorten the long run. Keep the week's key session.
- **Don't stack missed work.** A missed session isn't made up by doubling another day. Skip it, or swap it in for a later easy run if the spacing still works.
- **Race week protects the race:** no quality session in the two days before it.

## How to decide

1. List the options that keep the rules: usually moving the session to a free day, moving an adjacent easy run to make room, or dropping the least important session. Recommend one, with one line on why.
2. Write it once they agree: `change_session` moves or modifies, `remove_session` drops. Move the session itself rather than a copy, so its link to the watch follows.
3. Check the moved session's `garmin_sync_state`. If it failed (Garmin sometimes drops the connection), use `resync_watch`.

## "I'm tired today"

1. Read `today`, and `wellness` for the last 3–5 nights.
2. **HRV:** judge `last_night_avg` against the athlete's band (`balanced_low`, `low_upper`), not `status` or z2's suggestion: both are 7-day verdicts that keep saying BALANCED through a dip. A slide over three nights matters; one low night is noise.
3. **Readiness POOR or LOW, or HRV under its band for 3+ nights:** swap a hard session for an easy 30–45 minutes, or trim it (shorter, no fast finish). Move the hard session later only if the spacing rules still hold.
4. **Mild signs** (one low night, readiness MODERATE): keep the session and tighten its guardrail.
5. **Modify before skipping.** Skip only for signs of illness.
6. **Their feeling tired counts even when the numbers look fine.** Offer the easier version and let them choose.
7. **Tiredness lasting a week:** look at `fitness` (fatigue rising, form falling) and training_status's acute load before changing the rest of the block.
