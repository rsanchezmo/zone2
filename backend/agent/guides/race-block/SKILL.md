---
name: race-block
description: Build a training block toward a race (5K to marathon), from the athlete's current fitness to race day, with checkpoints that decide the target, and write it to the calendar. Use for "get me ready for…", "plan my next N weeks", or a goal time.
---

## Start from the athlete, not a template

1. Read before proposing:
   - `races`: the goal race and any others in the window.
   - `race_predictions`: where they are now, and their training paces.
   - `fitness`: current load and form.
   - `weekly_volume` for the last 12 weeks of running.
   - `planned_sessions_between` for what's already planned, other sports included.
   - The notes, for preferences, constraints and baselines.
2. Ask only what the data can't tell you, and only if the answer changes the plan: training days, the long-run day, days they can't train, and whether the goal is a time or to finish well.
3. Check the goal against the prediction.
   - Within about 2% of the predicted time is realistic for the block.
   - 2–5% is ambitious: it needs a full block and a checkpoint that can lower the target.
   - Beyond 5%, say so and offer a stepping-stone target.

## Shape of the block

- **Weeks available** set the phases. Count back from race day.
  - **Taper:** 7–10 days for 10K and shorter; 10–14 days for a half marathon; 2–3 weeks for a marathon. Cut volume to about 75%, and keep a short sharp session at race pace.
  - **Peak:** race-specific work at goal pace, in the 2–3 weeks before the taper.
  - **Build:** threshold and VO2 work grows, in the middle.
  - **Base:** easy volume, strides and hills, if there's time at the start. Under 6 weeks, skip base.
- **Volume** starts from what they actually ran in the last 3 months, not their best ever.
  - Peak at about their recent high.
  - Grow by at most about 10% a week.
  - A lighter week (about 75%) every third or fourth week. It's a good place for the test.
- **Quality sessions** depend on training history, not on days a week. An experienced runner (years of training, past race times well under the goal) needs two quality sessions plus the long run even on three running days; one would undertrain them. Someone new or coming back gets one.
- **Easy share.** About 80% easy by time holds with 4+ runs a week. With 3 runs it can't: the long run is the only easy run. Count other sports as aerobic volume, and keep the long run and every easy run truly easy, by HR rather than pace.
- **The long run** grows to about 25–30% of the week's km. For 10K and shorter, cap it at about 15 km or 90 minutes; past that it costs more than it gives. It never goes on the day after a quality session.
- **Other sports belong in the design.**
  - No racquet or team sport the day before a quality run.
  - No heavy leg strength work within 48 h before quality.
  - Drop sports with sharp lateral moves (racquet sports, futsal) in the last 3 weeks, since a sprained ankle ends the block.

## Paces: anchored to the goal, guarded by HR

In a goal block, session paces come from the goal pace, not from today's training paces. Show both, so the athlete sees the gap the block has to close.

For a 10K goal pace G:
- threshold: G + 10 s/km, tightening to G + 5 s/km;
- long intervals: G − 7 to −10 s/km;
- short reps: G − 20 to −25 s/km;
- steady long-run finishes: G + 25 to +30 s/km;
- easy runs by HR cap (zone 2), not by pace.

Every quality session gets an **HR guardrail**: the point at which they give up the pace. Example for threshold: "HR above threshold HR before km 3 of a rep → ease 5 s/km". The checkpoints decide whether the goal pace stays, not the predictor.

**Watch pace on race day.** If the athlete's GPS reads long, which the notes say, or you can measure it on a certified course they raced (watch km against official km), the watch pace for the goal is faster than the course pace. At 2% long, 5:00/km on the course shows about 4:54.

## Checkpoints

Write the decision rules before the test, so the result decides rather than mood.

1. **A test near halfway**, such as a 5K time trial in the lighter week. Set two thresholds:
   - at or under X: keep the goal;
   - about Y: a slower target, with its race-start pace.
2. **Read the fade exponent after the test.** Report it with its SE. It chooses the next block of sessions:
   - Fades (endurance is the limiter): lengthen the threshold work into a progression to race pace.
   - Holds pace (speed is the limiter): shorter, faster reps, such as 8 × 800 m at G − 15 s/km.
   - Typical: no change.
3. **A race-specific session in the peak**, such as 3 × 3 km at goal pace. Pace held at HR under a stated ceiling: go for the goal. Fading, or HR past the ceiling: start the race 5 s/km slower and finish hard.

`remember` the thresholds once they're agreed, so later conversations apply them.

## Race-day plan

- An even pace: run the first km at goal pace, not faster, and hold it to about 70% of the distance before pushing.
- Don't race by HR; expect it near the top of zone 5.
- Give the watch pace with the GPS correction.

## Write it

1. Propose the block week by week:
   - total km;
   - each week's key sessions, with paces and guardrails;
   - the checkpoints and their thresholds;
   - a sentence of logic per week.

   Wait for the athlete's changes.
2. Once they agree, write the sessions. Structured sessions get `segments` so they go to the watch, a short title, `planned_intensity`, and the purpose plus guardrail in `description`. Easy runs stay plain sessions, without steps.
3. Don't duplicate sessions already planned; change them instead.
