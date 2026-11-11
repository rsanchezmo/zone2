"""Race predictions from recent best efforts: Riegel projections at the typical
and the athlete's own fade exponent and, for running, Daniels' VDOT, blended
with weights for how close, recent and hard each effort was, then calibrated
by how past races landed against their prediction."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, NamedTuple, NotRequired, TypedDict

import numpy as np
import pandas as pd

from zone2.best_efforts import BestEffort, RankedBests, recent_best_efforts, sport_distances
from zone2.utils import (
    RIEGEL_TYPICAL_EXPONENT, FadeVerdict, SportCategory, fit_riegel_exponent, predicted_time_from_vdot,
    riegel_predict, training_paces_from_vdot, vdot_from_time_distance,
)

# Hard outer cutoff of the recent bests; the recency decay inside
# compute_predictions does the real freshness weighting.
PREDICTIONS_WINDOW_DAYS = 365

# Race-day calibration: predictions read systematically ~2–3% slower than
# race results at every distance and knob setting, as training best efforts
# understate a tapered, competitive race. The correction is learned per
# athlete: median(actual / predicted as of the day before) over past races,
# clamped, once enough races exist.
RACE_CALIBRATION_MIN_RACES = 3
RACE_CALIBRATION_CLAMP = 0.05   # factor stays within [0.95, 1.05]
# GPS over-reads a nominal course; up to this much over, a race still counts
# as its standard distance (a 10-mile race's 16.3 km reads as the 15K).
RACE_GPS_OVERREAD_MAX = 1.10

# Shortest effort the fade is fit on: Riegel's power law is calibrated for
# aerobic race durations, and anaerobic 400m/1K points skew the exponent
# that is then applied to every distance.
FADE_MIN_TIME_S = 180
# Longest over shortest fitted distance: closer distances say little about
# how pace holds as races get longer.
FADE_MIN_SPAN = 2.0

# The marathon prediction is usually an extrapolation, and the shortest
# efforts measure speed more than aerobic fitness.
TRAINING_PACE_DISTANCES = (5000, 10000, 21097)

# History steps with fewer distinct distances among their recent bests are
# dropped: the personal fade can't be fit, and one anchor can't speak for
# the whole distance range.
HISTORY_MIN_INPUTS = 3


@dataclass(frozen=True)
class PredictionTuning:
    """Knobs backtested against race-flagged activities (each predicted as of
    the day before, scripts/backtest_race_predictions.py, 5K–HM). The values
    are the moderate ones the grid marginals support, as the single best
    combination sat at the grid's extremes with a small sample: half-life
    90 and decay 1.0 each shaved ~0.1–0.2pp of MAE off 180 and 1.5; the
    VDOT weight was the strongest lever (0.5 → 3.96%, 0.7 → 3.70% MAE),
    capped at 0.7 so the Riegel family still anchors the band and the
    backtest-untested marathon. Replace StravaAnalytics.prediction_tuning
    to experiment."""
    recency_half_life_days: float = 90.0   # anchor age decay half-life
    dist_decay_k: float = 1.0              # distance-proximity decay exponent
    vdot_family_weight: float = 0.7        # central-estimate share for VDOT (running)
    race_boost: float = 1.5                # weight multiplier for race anchors
    intensity_floor: float = 0.4           # min quality weight for low-avg-HR anchors


PredictionSource = Literal["predicted", "personal_record"]
Confidence = Literal["high", "medium", "low"]
# (race date, actual / predicted as of the day before)
RaceResidual = tuple[pd.Timestamp, float]


class PredictionModels(TypedDict, total=False):
    riegel: float
    personalized_riegel: float
    vdot: float


class Prediction(TypedDict):
    distance_m: int
    label: str
    pr_time_s: float | None
    pr_date: str | None
    source: PredictionSource
    predicted_time_s: float | None
    predicted_time_low_s: float | None
    predicted_time_high_s: float | None
    models: PredictionModels
    garmin_time_s: NotRequired[float]


class FadeAnchor(TypedDict):
    distance_m: int
    time_s: float
    date: str
    activity_id: int
    activity_name: str
    is_race: bool
    weight_share: float


class FadeFit(TypedDict):
    exponent: float
    stderr: float | None
    typical: float
    # None without a standard error to judge the exponent by
    verdict: FadeVerdict | None
    anchors: list[FadeAnchor]


class PredictionCore(TypedDict):
    predictions: list[Prediction]
    athlete_vdot: float | None
    fitted_exponent: float | None
    fade: FadeFit | None


class Calibration(TypedDict):
    factor: float
    # The empirical band, None below RACE_CALIBRATION_MIN_RACES
    band_low_mult: float | None
    band_high_mult: float | None
    n_races: int


class RaceDayCalibration(TypedDict):
    factor: float
    n_races: int
    band_low_mult: float | None
    band_high_mult: float | None


class TrainingPaceRange(TypedDict):
    zone: str
    speed_min_mps: float
    speed_max_mps: float


class TrainingPaces(TypedDict):
    vdot: float
    paces: list[TrainingPaceRange]


class GarminRacePredictions(TypedDict):
    """Garmin's race predictor, in seconds."""
    date: str | None
    time5K: float | None
    time10K: float | None
    timeHalfMarathon: float | None
    timeMarathon: float | None


class DataQuality(TypedDict):
    total_activities: int
    prs_available: int
    recent_prs: int
    sufficient: bool
    warnings: list[str]
    window_days: int


class RacePredictions(TypedDict):
    predictions: list[Prediction]
    athlete_vdot: float | None
    fitted_exponent: float | None
    fade: FadeFit | None
    training_paces: TrainingPaces | None
    confidence: Confidence
    sport_category: SportCategory
    garmin_predictions: GarminRacePredictions | None
    race_day_calibration: RaceDayCalibration
    data_quality: DataQuality


class HistoryPrediction(TypedDict):
    distance_m: int
    label: str
    predicted_time_s: float | None
    predicted_time_low_s: float | None
    predicted_time_high_s: float | None


class PredictionHistoryPoint(TypedDict):
    end_date: str
    athlete_vdot: float | None
    fitted_exponent: float | None
    n_inputs: int
    predictions: list[HistoryPrediction]


class RaceResult(NamedTuple):
    """A race's own best effort at the standard distance it ran."""
    date: pd.Timestamp
    distance_m: int
    time_s: float


def weighted_quantile(values: list[float], weights: list[float], q: float) -> float:
    """Linear-interpolated weighted quantile, numpy.percentile's 'hazen'
    method when weights are uniform. The prediction band uses it so the IQR
    respects the same closer-anchor weighting as the central estimate.
    """
    if not values:
        return 0.0
    pairs = sorted(zip(values, weights), key=lambda p: p[0])
    vals = np.array([v for v, _ in pairs], dtype=np.float64)
    wts = np.array([w for _, w in pairs], dtype=np.float64)
    total = wts.sum()
    if total <= 0:
        return float(np.percentile(vals, q * 100))
    # Centered staircase: each sample contributes weight at the midpoint of
    # its cumulative weight interval.
    cum = (np.cumsum(wts) - 0.5 * wts) / total
    return float(np.interp(q, cum, vals))


def compute_predictions(
    recent_bests: list[BestEffort],
    sport_category: SportCategory,
    reference_date: datetime | pd.Timestamp,
    hr_max: float,
    tuning: PredictionTuning = PredictionTuning(),
) -> PredictionCore:
    """Predictions at each of the sport's standard distances from its recent
    best efforts, as of `reference_date` (naive is UTC), uncalibrated.

    Each effort weighs into every target with
        w = distance_proximity × recency_decay × quality
    where:
        distance_proximity = exp(-k·|log2(d_input / d_target)|)
        recency_decay      = exp(-ln(2) × age_days / recency_half_life_days)
        quality            = race_boost for a race, otherwise an intensity
                             factor from the activity's avg HR vs `hr_max`:
                             a long-run "best" is weaker evidence of race
                             ability than a race or a hard workout.

    - Central estimate per target: the Riegel family (typical 1.06 and the
      personal fade exponent when it can be fit), blended for running with
      a VDOT prediction that takes vdot_family_weight of it.
    - Band: weighted p25–p75 of the same projection pool. The weighted mean
      can fall outside it when the pool is skewed; apply_calibration leaves
      the central inside the band.

    For cycling and swimming, Riegel's 1.06 is a running figure and the
    fitted exponent matters more; `fitted_exponent` lets the caller judge.
    """
    ref_ts = pd.Timestamp(reference_date)
    if ref_ts.tz is None:
        ref_ts = ref_ts.tz_localize("UTC")
    target_distances = sport_distances(sport_category)

    # exp(-ln(2) × age / half-life): with a 90-day half-life, today → ~1.0;
    # 3 months → 0.5; 6 months → 0.25; 1 year → 0.06.
    half_life = tuning.recency_half_life_days

    def _recency_w(date_str: str) -> float:
        try:
            pr_date = datetime.fromisoformat(date_str)
            if pr_date.tzinfo is None:
                pr_date = pr_date.replace(tzinfo=timezone.utc)
            age_days = max(0.0, (ref_ts - pr_date).total_seconds() / 86400.0)
        except Exception:
            return 0.1
        return math.exp(-0.693 * age_days / half_life)

    # Races are true maximal demonstrations and get a boost; efforts at
    # clearly sub-maximal heart rate are down-weighted. Whole-activity
    # average HR is a coarse proxy for segment intensity, so the floor stays
    # generous and missing HR is neutral rather than penalized.
    race_boost = tuning.race_boost
    intensity_floor = tuning.intensity_floor

    def _quality_w(b: BestEffort) -> float:
        if b["is_race"]:
            return race_boost
        avg_hr = b["avg_hr"]
        if avg_hr and hr_max > 0:
            ratio = avg_hr / hr_max
            # ~85%+ of max HR → full weight, linear down to the floor.
            return float(min(1.0, max(intensity_floor, (ratio - 0.55) / 0.30)))
        return 1.0

    anchor_weights = [_recency_w(b["date"]) * _quality_w(b) for b in recent_bests]

    # VDOT only applies to running. Each top-1 anchor yields a VDOT, kept
    # with its distance and weight to be re-weighted by distance proximity
    # per target. `athlete_vdot` (weighted by recency × quality only) is for
    # display; the predictions use the per-target VDOT.
    vdot_anchors: list[tuple[float, int, float]] = []
    athlete_vdot: float | None = None
    if sport_category == SportCategory.RUNNING:
        for b, rw in zip(recent_bests, anchor_weights):
            if not b["is_top1"]:
                continue
            v = vdot_from_time_distance(b["time_s"], b["distance_m"])
            if v is not None and rw > 0:
                vdot_anchors.append((v, int(b["distance_m"]), rw))
        if vdot_anchors:
            tot = sum(rw for _, _, rw in vdot_anchors)
            athlete_vdot = (
                round(sum(v * rw for v, _, rw in vdot_anchors) / tot, 2)
                if tot > 0 else None
            )

    fade = fit_fade(recent_bests, anchor_weights)
    fitted_exp = fade["exponent"] if fade else None

    # k=1 is the classical exp(-|log2|); a larger k dampens far anchors'
    # contributions (a 5K projecting to 20K) without zeroing them.
    dist_decay_k = tuning.dist_decay_k

    def _dist_weight(d_in: float, d_tgt: float) -> float:
        return math.exp(-dist_decay_k * abs(math.log2(d_in / d_tgt)))

    predictions: list[Prediction] = []
    for dist_m, label in target_distances:
        entry: Prediction = {
            "distance_m": dist_m,
            "label": label,
            "pr_time_s": None,
            "pr_date": None,
            "source": "predicted",
            "predicted_time_s": None,
            "predicted_time_low_s": None,
            "predicted_time_high_s": None,
            "models": {},
        }

        # For display: the fastest recent effort at this distance.
        existing = next(
            (b for b in recent_bests if b["distance_m"] == dist_m and b["is_top1"]),
            None,
        )
        if existing:
            entry["pr_time_s"] = existing["time_s"]
            entry["pr_date"] = existing["date"]
            entry["source"] = "personal_record"

        if not recent_bests:
            predictions.append(entry)
            continue

        # Every raw model value that contributes to the central, with its
        # effective weight: the pool's weighted mean is the central, its
        # weighted p25/p75 the band.
        samples: list[tuple[float, float]] = []  # (value, weight)

        # Per-input Riegel (typical 1.06) projections weighted by distance
        # proximity and the recency × quality of the underlying best.
        riegel_inputs = [
            (riegel_predict(b["time_s"], b["distance_m"], dist_m),
             _dist_weight(b["distance_m"], dist_m) * rw)
            for b, rw in zip(recent_bests, anchor_weights)
        ]
        riegel_sum_w = sum(w for _, w in riegel_inputs)

        # Per-input personal Riegel projections, if the exponent was fit.
        pers_inputs: list[tuple[float, float]] = []
        if fitted_exp is not None:
            pers_inputs = [
                (riegel_predict(b["time_s"], b["distance_m"], dist_m, fitted_exp),
                 _dist_weight(b["distance_m"], dist_m) * rw)
                for b, rw in zip(recent_bests, anchor_weights)
            ]
        pers_sum_w = sum(w for _, w in pers_inputs)

        # Per-target VDOT: each anchor's VDOT re-weighted by its distance
        # proximity to this target. A 5K anchor still informs the marathon,
        # but much less than a 20K or half marathon one.
        vdot_pred: float | None = None
        if vdot_anchors and sport_category == SportCategory.RUNNING:
            vdot_pairs = [
                (v, rw * _dist_weight(d_anchor, dist_m))
                for v, d_anchor, rw in vdot_anchors
            ]
            tot_vw = sum(w for _, w in vdot_pairs)
            if tot_vw > 0:
                target_vdot = sum(v * w for v, w in vdot_pairs) / tot_vw
                vdot_pred = predicted_time_from_vdot(target_vdot, dist_m)

        # Family weights: VDOT takes vdot_family_weight when present; the
        # Riegel family splits the rest evenly between typical and personal.
        has_r = riegel_sum_w > 0
        has_p = pers_sum_w > 0
        vdot_w = tuning.vdot_family_weight if vdot_pred is not None else 0.0
        family_w = 1.0 - vdot_w
        n_families = (1 if has_r else 0) + (1 if has_p else 0)
        r_share = family_w / n_families if has_r and n_families else 0.0
        p_share = family_w / n_families if has_p and n_families else 0.0

        # Each family's share spread over its inputs by their weights.
        if has_r:
            for v, w in riegel_inputs:
                samples.append((v, r_share * w / riegel_sum_w))
        if has_p:
            for v, w in pers_inputs:
                samples.append((v, p_share * w / pers_sum_w))
        if vdot_pred is not None:
            samples.append((vdot_pred, vdot_w))

        if has_r:
            entry["models"]["riegel"] = round(
                sum(v * w for v, w in riegel_inputs) / riegel_sum_w, 1
            )
        if has_p:
            entry["models"]["personalized_riegel"] = round(
                sum(v * w for v, w in pers_inputs) / pers_sum_w, 1
            )
        if vdot_pred is not None:
            entry["models"]["vdot"] = vdot_pred

        total_w = sum(w for _, w in samples)
        if total_w > 0:
            central = sum(v * w for v, w in samples) / total_w
            entry["predicted_time_s"] = round(central, 1)

        if len(samples) >= 2:
            vals = [v for v, _ in samples]
            wts = [w for _, w in samples]
            entry["predicted_time_low_s"] = round(weighted_quantile(vals, wts, 0.25), 1)
            entry["predicted_time_high_s"] = round(weighted_quantile(vals, wts, 0.75), 1)
        elif len(samples) == 1 and entry["predicted_time_s"] is not None:
            entry["predicted_time_low_s"] = entry["predicted_time_s"]
            entry["predicted_time_high_s"] = entry["predicted_time_s"]

        predictions.append(entry)

    return {
        "predictions": predictions,
        "athlete_vdot": athlete_vdot,
        "fitted_exponent": fitted_exp,
        "fade": fade,
    }


def fit_fade(recent_bests: list[BestEffort], anchor_weights: list[float]) -> FadeFit | None:
    """How much the athlete slows as distance grows: the Riegel exponent fit
    over the recent best efforts, weighted by the same recency × quality as
    the predictions, so an old short PR can't outweigh this month's long race.
    Each distance counts once: its efforts share the weight of its strongest
    one, so a distance with more efforts doesn't pull the fit.

    The verdict compares the exponent ± its standard error to Riegel's
    typical 1.06; while that range includes 1.06 the efforts can't tell
    speed from endurance."""
    by_distance: dict[int, list[tuple[BestEffort, float]]] = {}
    for b, w in zip(recent_bests, anchor_weights):
        if b["time_s"] >= FADE_MIN_TIME_S and w > 0:
            by_distance.setdefault(b["distance_m"], []).append((b, w))
    if len(by_distance) < 3 or max(by_distance) / min(by_distance) < FADE_MIN_SPAN:
        return None

    anchors: list[tuple[BestEffort, float]] = []
    for efforts in by_distance.values():
        total, strongest = sum(w for _, w in efforts), max(w for _, w in efforts)
        anchors += [(b, strongest * w / total) for b, w in efforts]
    fit = fit_riegel_exponent([b for b, _ in anchors], [w for _, w in anchors])
    if fit is None:
        return None

    exponent, stderr = fit
    verdict: FadeVerdict | None = None
    if stderr is not None:
        if exponent - stderr > RIEGEL_TYPICAL_EXPONENT:
            verdict = FadeVerdict.FADES
        elif exponent + stderr < RIEGEL_TYPICAL_EXPONENT:
            verdict = FadeVerdict.HOLDS_PACE
        else:
            verdict = FadeVerdict.TYPICAL
    total_w = sum(w for _, w in anchors)
    return {
        "exponent": exponent,
        "stderr": stderr,
        "typical": RIEGEL_TYPICAL_EXPONENT,
        "verdict": verdict,
        "anchors": [
            {
                "distance_m": b["distance_m"],
                "time_s": b["time_s"],
                "date": b["date"],
                "activity_id": b["activity_id"],
                "activity_name": b["activity_name"],
                "is_race": b["is_race"],
                "weight_share": round(w / total_w, 3),
            }
            for b, w in sorted(anchors, key=lambda a: -a[1])
        ],
    }


def race_distance(gps_distance_m: float, sport_category: SportCategory) -> int | None:
    """The standard distance a race ran: the longest one its GPS distance
    reaches without over-reading it by more than RACE_GPS_OVERREAD_MAX."""
    targets = sorted((d for d, _ in sport_distances(sport_category)), reverse=True)
    return next((t for t in targets if t <= gps_distance_m <= t * RACE_GPS_OVERREAD_MAX), None)


def race_results(races: pd.DataFrame, bests: pd.DataFrame, sport_category: SportCategory) -> list[RaceResult]:
    """Each of `races` (activities of the sport) that ran a standard distance,
    with its own best effort at that distance from `bests`."""
    results: list[RaceResult] = []
    for _, row in races.iterrows():
        distance_m = race_distance(float(row.get("distance") or 0), sport_category)
        if distance_m is None:
            continue
        effort = bests[(bests["activity_id"] == row["id"]) & (bests["distance_m"] == distance_m)]
        if effort.empty:
            continue
        results.append(RaceResult(row["start_date_local"], distance_m, float(effort["time_s"].iloc[0])))
    return results


def race_residuals(
    races: list[RaceResult],
    ranked: RankedBests,
    sport_category: SportCategory,
    hr_max: float,
    tuning: PredictionTuning = PredictionTuning(),
) -> list[RaceResidual]:
    """(race date, actual / predicted) for each race, predicted as of the day
    before it: a race never calibrates itself, and the residuals come
    ordered by date so a caller can take the races before a date leak-free."""
    residuals: list[RaceResidual] = []
    for race in races:
        asof = race.date - pd.Timedelta(days=1)
        recent = recent_best_efforts(ranked, asof, PREDICTIONS_WINDOW_DAYS)
        if not recent:
            continue
        core = compute_predictions(recent, sport_category, asof, hr_max, tuning)
        entry = next((p for p in core["predictions"] if p["distance_m"] == race.distance_m), None)
        if not entry or not entry["predicted_time_s"]:
            continue
        residuals.append((race.date, race.time_s / float(entry["predicted_time_s"])))

    residuals.sort(key=lambda r: r[0])
    return residuals


def race_calibration(residuals: list[RaceResidual], reference_date: datetime | pd.Timestamp) -> Calibration:
    """Race-day calibration from the races strictly before `reference_date`
    (naive is UTC):
        factor          — clamped median(actual/predicted): central correction
        band_low_mult / band_high_mult — p25/p75 of the residuals, or None
                          below the minimum race count. An empirical band:
                          across past races, the middle 50% of results
                          landed in this range around the raw prediction. It
                          captures day form, course and model error together,
                          which the model-spread IQR (quantiles of a pool
                          dominated by one VDOT sample) understates.
        n_races         — residuals used
    """
    ref = pd.Timestamp(reference_date)
    if ref.tz is None:
        ref = ref.tz_localize("UTC")
    ratios = [r for d, r in residuals if d < ref]
    n = len(ratios)
    if n < RACE_CALIBRATION_MIN_RACES:
        return {"factor": 1.0, "band_low_mult": None, "band_high_mult": None, "n_races": n}
    clamp = RACE_CALIBRATION_CLAMP
    factor = float(min(1.0 + clamp, max(1.0 - clamp, np.median(ratios))))
    # Keep the band consistent with the (possibly clamped) central factor.
    low = min(float(np.percentile(ratios, 25)), factor)
    high = max(float(np.percentile(ratios, 75)), factor)
    return {"factor": factor, "band_low_mult": low, "band_high_mult": high, "n_races": n}


def apply_calibration(predictions: list[Prediction], cal: Calibration) -> None:
    """Apply race-day calibration in place: scale the central by `factor`;
    replace the band with the empirical residual band when available,
    otherwise scale the model band and widen it to contain the central."""
    factor = cal["factor"]
    low_mult, high_mult = cal["band_low_mult"], cal["band_high_mult"]
    for p in predictions:
        raw = p["predicted_time_s"]
        if raw is None:
            continue
        central = raw * factor
        if low_mult is not None and high_mult is not None:
            p["predicted_time_low_s"] = round(raw * low_mult, 1)
            p["predicted_time_high_s"] = round(raw * high_mult, 1)
        else:
            low, high = p["predicted_time_low_s"], p["predicted_time_high_s"]
            if low is not None:
                p["predicted_time_low_s"] = round(min(low * factor, central), 1)
            if high is not None:
                p["predicted_time_high_s"] = round(max(high * factor, central), 1)
        p["predicted_time_s"] = round(central, 1)


def training_paces(predictions: list[Prediction]) -> TrainingPaces | None:
    """Daniels' training paces at the VDOT the calibrated predictions imply,
    so they follow what the athlete would race now (`athlete_vdot` comes
    from raw training efforts, which read slow of race day)."""
    vdots = [
        vdot_from_time_distance(p["predicted_time_s"], p["distance_m"])
        for p in predictions
        if p["distance_m"] in TRAINING_PACE_DISTANCES and p["predicted_time_s"]
    ]
    known = [v for v in vdots if v is not None]
    if not known:
        return None
    vdot = sum(known) / len(known)
    speeds = training_paces_from_vdot(vdot)
    if speeds is None:
        return None
    return {
        "vdot": round(vdot, 1),
        "paces": [
            {"zone": zone.value, "speed_min_mps": round(slow, 4), "speed_max_mps": round(fast, 4)}
            for zone, (slow, fast) in speeds.items()
        ],
    }


def _distinct_distances(recent: list[BestEffort]) -> int:
    return len({b["distance_m"] for b in recent if b["is_top1"]})


def predict_races(
    ranked: RankedBests,
    residuals: list[RaceResidual],
    sport_category: SportCategory,
    now: datetime,
    hr_max: float,
    garmin: GarminRacePredictions | None,
    total_activities: int,
    tuning: PredictionTuning = PredictionTuning(),
) -> RacePredictions:
    """Predictions as of `now` from the recent bests of the last
    PREDICTIONS_WINDOW_DAYS, calibrated by the races before `now`, with
    training paces and the fade (running), Garmin's own predictor alongside
    when given (running), and how far the inputs can be trusted."""
    recent = recent_best_efforts(ranked, now, PREDICTIONS_WINDOW_DAYS)
    core = compute_predictions(recent, sport_category, now, hr_max, tuning)
    cal = race_calibration(residuals, now)
    apply_calibration(core["predictions"], cal)

    n_recent = _distinct_distances(recent)
    confidence: Confidence = "high" if n_recent >= 5 else "medium" if n_recent >= 3 else "low"

    warnings: list[str] = []
    if n_recent == 0:
        warnings.append(
            f"No {sport_category} efforts in the last 52 weeks — predictions unavailable"
        )
    elif n_recent < 3:
        warnings.append(
            f"Only {n_recent} distinct recent best effort(s) in the last 52 weeks — "
            "personalized Riegel not fit; predictions extrapolated from limited inputs"
        )
    if sport_category == SportCategory.CYCLING:
        warnings.append(
            "Cycling predictions use a time/distance Riegel model — for power-based "
            "athletes a critical-power curve would be more accurate"
        )

    # Targets far beyond the longest recent effort are extrapolations the
    # backtest can't vouch for (e.g. Marathon predicted from ≤HM anchors).
    max_anchor = max((b["distance_m"] for b in recent), default=0)
    extrapolated = [
        label for dist_m, label in sport_distances(sport_category)
        if max_anchor and dist_m > 1.6 * max_anchor
    ]
    if extrapolated:
        warnings.append(
            f"{', '.join(extrapolated)} prediction extrapolates well beyond the "
            f"longest recent effort ({max_anchor / 1000:.1f} km) — treat with caution"
        )

    if garmin:
        garmin_by_distance = {
            5000: garmin["time5K"],
            10000: garmin["time10K"],
            21097: garmin["timeHalfMarathon"],
            42195: garmin["timeMarathon"],
        }
        for p in core["predictions"]:
            g = garmin_by_distance.get(p["distance_m"])
            if g:
                p["garmin_time_s"] = float(g)

    is_running = sport_category == SportCategory.RUNNING
    return {
        "predictions": core["predictions"],
        "athlete_vdot": core["athlete_vdot"],
        "fitted_exponent": core["fitted_exponent"],
        # Riegel's typical exponent is a running figure.
        "fade": core["fade"] if is_running else None,
        "training_paces": training_paces(core["predictions"]) if is_running else None,
        "confidence": confidence,
        "sport_category": sport_category,
        "garmin_predictions": garmin,
        "race_day_calibration": {
            "factor": round(cal["factor"], 4),
            "n_races": cal["n_races"],
            "band_low_mult": round(cal["band_low_mult"], 4) if cal["band_low_mult"] else None,
            "band_high_mult": round(cal["band_high_mult"], 4) if cal["band_high_mult"] else None,
        },
        "data_quality": {
            "total_activities": total_activities,
            "prs_available": n_recent,
            "recent_prs": n_recent,
            "sufficient": n_recent >= 2,
            "warnings": warnings,
            "window_days": PREDICTIONS_WINDOW_DAYS,
        },
    }


def prediction_history(
    ranked: RankedBests,
    residuals: list[RaceResidual],
    sport_category: SportCategory,
    now: datetime,
    hr_max: float,
    weeks: int,
    step_days: int,
    window_days: int,
    tuning: PredictionTuning = PredictionTuning(),
) -> list[PredictionHistoryPoint]:
    """Calibrated predictions every `step_days` over the last `weeks` steps up
    to `now`, each from the recent bests of the `window_days` before it,
    oldest first. Steps under HISTORY_MIN_INPUTS distinct distances are left
    out until the first one that has them; after it they stay in with null
    predictions, so a chart breaks its line there instead of bridging it."""
    target_distances = sport_distances(sport_category)
    if not target_distances:
        return []

    empty_predictions: list[HistoryPrediction] = [
        {
            "distance_m": dist_m,
            "label": label,
            "predicted_time_s": None,
            "predicted_time_low_s": None,
            "predicted_time_high_s": None,
        }
        for dist_m, label in target_distances
    ]

    history: list[PredictionHistoryPoint] = []
    first_valid_seen = False
    for i in range(weeks - 1, -1, -1):
        step_end = now - timedelta(days=i * step_days)
        recent = recent_best_efforts(ranked, step_end, window_days)

        if _distinct_distances(recent) < HISTORY_MIN_INPUTS:
            if not first_valid_seen:
                continue
            history.append({
                "end_date": step_end.date().isoformat(),
                "athlete_vdot": None,
                "fitted_exponent": None,
                "n_inputs": len(recent),
                "predictions": empty_predictions,
            })
            continue

        first_valid_seen = True
        core = compute_predictions(recent, sport_category, step_end, hr_max, tuning)
        apply_calibration(core["predictions"], race_calibration(residuals, step_end))
        history.append({
            "end_date": step_end.date().isoformat(),
            "athlete_vdot": core["athlete_vdot"],
            "fitted_exponent": core["fitted_exponent"],
            "n_inputs": len(recent),
            "predictions": [
                {
                    "distance_m": p["distance_m"],
                    "label": p["label"],
                    "predicted_time_s": p["predicted_time_s"],
                    "predicted_time_low_s": p["predicted_time_low_s"],
                    "predicted_time_high_s": p["predicted_time_high_s"],
                }
                for p in core["predictions"]
            ],
        })
    return history
