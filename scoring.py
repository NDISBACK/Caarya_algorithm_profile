"""The fit algorithm.

Pure functions, no Flask import, so the company-matching dashboard can reuse this
module as-is and so the whole thing is testable without a server.

The question it answers: a student told us what they want to get paid for and
rated themselves on the skills behind it. Does their skill profile actually
support that ambition, and if not, what would suit them better?

A self-rating is weak evidence, and most of the machinery here exists to stop us
treating it as strong. In order:

  1. calibrate   - read each rating against the rest of that student's answers
  2. score       - 60/40 technical/transferable, with a real gap dragging it down
  3. confidence  - how much we should trust each number
  4. estimate    - fill in areas we never asked about, clearly marked
  5. adjust      - rank on the cautious end of the range, never the raw score
  6. effort      - how far from ready, and exactly what closes the gap
  7. place       - what they want against what they're ready for
"""

from __future__ import annotations

from dataclasses import dataclass, field

from taxonomy_loader import Taxonomy, vc_skill_ids

# Technical is weighted higher than transferable because it is the harder
# constraint on a placement: a company will coach someone through communication
# far sooner than through "has never written SQL".
TECHNICAL_WEIGHT = 0.60
TRANSFERABLE_WEIGHT = 0.40

# A value construct needs at least this share of its skills rated before we are
# willing to put a measured number on it. Below that we either estimate (clearly
# marked) or say "not enough evidence" - never score it 0, which would fabricate
# a weakness the student never claimed.
MIN_COVERAGE = 0.5

BANDS = [
    (75, "strong", "Strong fit"),
    (60, "emerging", "Emerging fit"),
    (45, "stretch", "Stretch"),
    (0, "gap", "Gap"),
]
READY_THRESHOLD = 60.0

# What each band is called when we're talking to a student rather than about a
# model. Same four bands, no extra logic - a score should never appear without
# one of these next to it, because "58" on its own tells nobody anything.
PLAIN_BANDS = {
    "strong": "Well ahead",
    "emerging": "Ready to start",
    "stretch": "Almost",
    "gap": "Not yet",
}

# How much better an unselected business service must score before we tell a
# student to go there instead. Anything less is noise in a self-rating.
REDIRECT_MARGIN = 8.0

# How hard the weakest must-have skill pulls a score down. At 0.35 an even
# profile barely moves and a genuine hole bites hard - see _readiness.
BOTTLENECK_PULL = 0.35

# Calibration: how much of the final score comes from where a rating sits in the
# student's own range rather than its face value, and how many points one
# standard deviation is worth.
CALIBRATION_WEIGHT = 0.30
CALIBRATION_SAMPLE = 12
POINTS_PER_SIGMA = 12.5
FLAT_SPREAD = 0.35          # below this the student barely used the scale

# Confidence: the worst response quality we will assign, and how many points of
# score a completely unconfident number gives up when ranked.
MIN_RESPONSE_QUALITY = 0.5
UNCERTAINTY_SPAN = 20.0

# If this share of ratings sit at 4-5, the self-assessment stops discriminating
# between skills and we say so rather than pretending the ranking is meaningful.
OVER_RATING_SHARE = 0.8

# Inference: similarity mass needed before an estimate is worth anything, and
# how much confidence an estimated area keeps.
MIN_INFERENCE_WEIGHT = 0.4
ESTIMATE_CONFIDENCE = 0.5

# Evidence: what a claim is worth before we have seen any history (unknown),
# and the range once we have. Unknown deliberately sits between the two, so
# filling in the profile can move confidence in either direction honestly.
NO_EVIDENCE_FACTOR = 0.9
EVIDENCE_FLOOR = 0.8


def normalize(rating: float) -> float:
    """1-5 -> 0-100, at face value."""
    return (float(rating) - 1.0) / 4.0 * 100.0


def band_for(score: float) -> tuple[str, str]:
    for threshold, key, label in BANDS:
        if score >= threshold:
            return key, label
    return "gap", "Gap"


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


# ---------------------------------------------------------------- calibration


@dataclass
class Calibration:
    """Reads each rating against the rest of that student's answers.

    Two students who are equally good rate themselves differently: one marks
    everything 4-5, another is hard on themselves throughout. Face value alone
    rewards the first and punishes the second. So part of each score comes from
    where that rating sits in the student's own range.

    When someone used barely any of the scale, the relative half collapses to the
    middle - which is the honest reading: a flat sheet of answers tells us
    nothing about which of their skills is stronger.
    """

    average: float
    spread: float
    weight: float
    count: int
    scores: dict[str, float] = field(default_factory=dict)

    def transform(self, rating: float) -> float:
        absolute = normalize(rating)
        if self.spread < FLAT_SPREAD:
            relative = 50.0
        else:
            relative = _clamp(50.0 + POINTS_PER_SIGMA * (rating - self.average) / self.spread)
        return (1.0 - self.weight) * absolute + self.weight * relative

    def score(self, skill_id: str) -> float | None:
        return self.scores.get(skill_id)


def calibrate_ratings(ratings: dict[str, int]) -> Calibration:
    values = [float(v) for v in ratings.values()]
    count = len(values)
    if not count:
        return Calibration(average=3.0, spread=0.0, weight=0.0, count=0)

    average = sum(values) / count
    spread = (sum((v - average) ** 2 for v in values) / count) ** 0.5
    # With only a handful of answers the student's own mean and spread are noisy,
    # so lean on face value until there is enough to read a pattern from.
    weight = CALIBRATION_WEIGHT * min(1.0, count / CALIBRATION_SAMPLE)

    calibration = Calibration(average=average, spread=spread, weight=weight, count=count)
    calibration.scores = {skill: calibration.transform(rating) for skill, rating in ratings.items()}
    return calibration


# ------------------------------------------------------------ response quality


def response_quality(ratings: dict[str, int]) -> dict:
    """How much the shape of someone's answers should be trusted.

    Not a judgement of the person - a measure of how much signal the answers
    carry. Every 4 down the page, or only ever using two points of a five-point
    scale, genuinely tells us less than a considered spread, and the ranking
    should be held more loosely as a result.
    """
    values = list(ratings.values())
    count = len(values)
    if not count:
        return {"score": MIN_RESPONSE_QUALITY, "distinct": 0, "longest_run": 0,
                "high_share": 0.0, "over_rating": False, "notes": []}

    distinct = len(set(values))
    longest_run = current = 1
    for previous, value in zip(values, values[1:]):
        current = current + 1 if value == previous else 1
        longest_run = max(longest_run, current)

    high_share = sum(1 for v in values if v >= 4) / count
    over_rating = high_share >= OVER_RATING_SHARE

    notes: list[str] = []
    penalty = 0.0

    variety = (1.0 - (distinct - 1) / 4.0) * 0.25
    if variety > 0.05:
        penalty += variety
        if distinct <= 2:
            notes.append(f"only {distinct} of the 5 points on the scale were used")

    run = max(0.0, longest_run / count - 0.4) * 0.5
    if run > 0.05:
        penalty += run
        notes.append(f"{longest_run} identical answers in a row")

    if over_rating:
        penalty += max(0.0, high_share - OVER_RATING_SHARE) * 0.75 + 0.05
        notes.append(f"{high_share * 100:.0f}% of answers were 4 or 5")

    return {
        "score": round(max(MIN_RESPONSE_QUALITY, 1.0 - penalty), 3),
        "distinct": distinct,
        "longest_run": longest_run,
        "high_share": round(high_share, 2),
        "over_rating": over_rating,
        "notes": notes,
    }


# ------------------------------------------------------------------- estimates


class SkillEstimator:
    """Predicts a score for a skill we never asked about.

    Skills overlap: `sql` and `data-modelling` live in the same value construct,
    so an answer about one is real - if weak - evidence about the other. We take
    a similarity-weighted average of what the student did rate, and only trust it
    when enough related skills were actually answered. Everything it produces is
    marked as an estimate wherever it surfaces.
    """

    def __init__(self, tax: Taxonomy, calibration: Calibration, ratings: dict[str, int]):
        self.tax = tax
        self.calibration = calibration
        self.ratings = ratings
        self._cache: dict[str, tuple[float, float] | None] = {}
        self._type_means = {
            kind: _mean([calibration.scores[s] for s in ratings if tax.skill_type(s) == kind])
            for kind in ("technical", "transferable")
        }

    def estimate(self, skill_id: str) -> tuple[float, float] | None:
        """(score, strength 0-1), or None when there is nothing to go on."""
        if skill_id in self._cache:
            return self._cache[skill_id]

        weighted = 0.0
        total = 0.0
        for neighbour, similarity in self.tax.neighbours(skill_id).items():
            score = self.calibration.score(neighbour)
            if score is None:
                continue
            weighted += similarity * score
            total += similarity

        if total >= MIN_INFERENCE_WEIGHT:
            result = (weighted / total, min(1.0, total))
        else:
            fallback = self._type_means.get(self.tax.skill_type(skill_id))
            # A student's average for this kind of skill is a weak guess, but it
            # beats silence - and it is handed back with a low strength so the
            # confidence maths discounts it properly.
            result = (fallback, 0.2) if fallback is not None else None

        self._cache[skill_id] = result
        return result

    def rating_estimate(self, skill_id: str) -> int:
        """The estimate expressed back on the 1-5 scale, for effort advice."""
        estimate = self.estimate(skill_id)
        score = estimate[0] if estimate else 0.0
        return int(max(1, min(5, round(score / 25.0) + 1)))


# --------------------------------------------------------------------- scoring


def _readiness(technical: list[float], transferable: list[float]) -> float | None:
    """Weighted score, then dragged towards the weakest must-have skill.

    Straight averaging says a 5 and a 1 are "medium", which is wrong about real
    work: you cannot ship an API you cannot build, however well you document it.
    So the score is pulled part of the way towards the lowest technical skill.
    A near-even profile barely moves; a genuine hole bites.
    """
    tech_mean = _mean(technical)
    trans_mean = _mean(transferable)
    if tech_mean is None and trans_mean is None:
        return None

    if tech_mean is None:
        base = trans_mean
    elif trans_mean is None:
        base = tech_mean
    else:
        base = TECHNICAL_WEIGHT * tech_mean + TRANSFERABLE_WEIGHT * trans_mean

    limiter = min(technical) if technical else min(transferable)
    return base - BOTTLENECK_PULL * max(0.0, base - limiter)


@dataclass
class VCScore:
    id: str
    name: str
    service_id: str
    selected: bool
    readiness: float | None = None
    adjusted: float | None = None
    confidence: float = 0.0
    technical: float | None = None
    transferable: float | None = None
    coverage: float = 0.0
    rated: int = 0
    total: int = 0
    evidenced: bool = False
    estimated: bool = False
    band: str = ""
    band_label: str = ""
    weak_skills: list[dict] = field(default_factory=list)
    effort: dict | None = None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "service_id": self.service_id,
            "selected": self.selected,
            "readiness": round(self.readiness, 1) if self.readiness is not None else None,
            "adjusted": round(self.adjusted, 1) if self.adjusted is not None else None,
            "confidence": round(self.confidence, 2),
            "technical": round(self.technical, 1) if self.technical is not None else None,
            "transferable": round(self.transferable, 1) if self.transferable is not None else None,
            "coverage": round(self.coverage, 2),
            "rated": self.rated,
            "total": self.total,
            "evidenced": self.evidenced,
            "estimated": self.estimated,
            "band": self.band,
            "band_label": self.band_label,
            "band_plain": PLAIN_BANDS.get(self.band, ""),
            "weak_skills": self.weak_skills,
            "effort": self.effort,
        }


def score_value_construct(
    tax: Taxonomy,
    vc_id: str,
    calibration: Calibration,
    selected: bool,
    estimator: SkillEstimator | None = None,
    quality: float = 1.0,
    evidence_factor: float = 1.0,
) -> VCScore:
    vc = tax.vcs[vc_id]
    skill_ids = vc_skill_ids(vc)
    score = VCScore(
        id=vc_id,
        name=vc.get("name", vc_id),
        service_id=tax.service_of_vc.get(vc_id, ""),
        selected=selected,
        total=len(skill_ids),
    )

    technical: list[float] = []
    transferable: list[float] = []
    estimate_strength: list[float] = []

    for skill_id in skill_ids:
        value = calibration.score(skill_id)
        if value is not None:
            score.rated += 1
            strength = 1.0
        elif estimator is not None:
            estimate = estimator.estimate(skill_id)
            if estimate is None:
                continue
            value, strength = estimate
            estimate_strength.append(strength)
        else:
            continue

        if tax.skill_type(skill_id) == "technical":
            technical.append(value)
        else:
            transferable.append(value)

    score.coverage = score.rated / score.total if score.total else 0.0
    score.technical = _mean(technical)
    score.transferable = _mean(transferable)
    score.estimated = bool(estimate_strength)

    measured_enough = score.coverage >= MIN_COVERAGE
    # An area held up mostly by estimates is still worth showing - it is how we
    # spot a hidden strength in work the student never picked - but it has to be
    # labelled, and it has to cost confidence.
    inferred_enough = bool(estimate_strength) and _mean(estimate_strength) >= 0.3

    if not (measured_enough or inferred_enough) or (not technical and not transferable):
        return score

    score.evidenced = True
    score.readiness = _readiness(technical, transferable)
    if score.readiness is not None:
        score.band, score.band_label = band_for(score.readiness)

    score.confidence = _clamp(score.coverage * quality * evidence_factor, 0.0, 1.0)
    if score.estimated:
        score.confidence *= ESTIMATE_CONFIDENCE * (_mean(estimate_strength) or 0.0) + ESTIMATE_CONFIDENCE
    score.confidence = round(_clamp(score.confidence, 0.0, 1.0), 4)

    if score.readiness is not None:
        score.adjusted = score.readiness - (1.0 - score.confidence) * UNCERTAINTY_SPAN

    rated_skills = [(s, calibration.scores[s]) for s in skill_ids if s in calibration.scores]
    score.weak_skills = [
        {"id": s, "name": tax.skill_name(s), "score": round(v, 1), "type": tax.skill_type(s)}
        for s, v in sorted(rated_skills, key=lambda pair: pair[1])
        if v < READY_THRESHOLD
    ][:3]
    return score


@dataclass
class ServiceScore:
    id: str
    name: str
    selected: bool
    fit: float | None = None
    adjusted: float | None = None
    confidence: float = 0.0
    coverage: float = 0.0
    evidenced_vcs: int = 0
    total_vcs: int = 0
    estimated: bool = False
    band: str = ""
    band_label: str = ""

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "selected": self.selected,
            "fit": round(self.fit, 1) if self.fit is not None else None,
            "adjusted": round(self.adjusted, 1) if self.adjusted is not None else None,
            "confidence": round(self.confidence, 2),
            "coverage": round(self.coverage, 2),
            "evidenced_vcs": self.evidenced_vcs,
            "total_vcs": self.total_vcs,
            "estimated": self.estimated,
            "band": self.band,
            "band_label": self.band_label,
            "band_plain": PLAIN_BANDS.get(self.band, ""),
        }


def score_service(tax: Taxonomy, service_id: str, vc_scores: dict[str, VCScore],
                  ratings: dict[str, int], selected: bool) -> ServiceScore:
    service = tax.services[service_id]
    # Active only: a retired value construct should not drag down, or prop up,
    # a score being computed today. Reports scored before it was retired are
    # stored whole and are unaffected.
    vcs = tax.active_vcs_of_service(service_id)
    scored = [vc_scores[vc["id"]] for vc in vcs if vc_scores[vc["id"]].evidenced]

    skill_ids = tax.skills_of_vcs([vc["id"] for vc in vcs])
    rated = sum(1 for s in skill_ids if s in ratings)

    score = ServiceScore(
        id=service_id,
        name=service.get("name", service_id),
        selected=selected,
        coverage=rated / len(skill_ids) if skill_ids else 0.0,
        evidenced_vcs=len(scored),
        total_vcs=len(vcs),
        # Estimated only when guessing actually drives the number. Flagging an
        # area as guessed because one of its five jobs was inferred would put
        # "we guessed this" on the area the student rated most thoroughly.
        estimated=sum(vc.estimated for vc in scored) > sum(not vc.estimated for vc in scored),
    )

    score.fit = _mean([vc.readiness for vc in scored if vc.readiness is not None])
    if score.fit is not None:
        score.band, score.band_label = band_for(score.fit)
        score.confidence = _mean([vc.confidence for vc in scored]) or 0.0
        score.adjusted = score.fit - (1.0 - score.confidence) * UNCERTAINTY_SPAN
    return score


# ---------------------------------------------------------------------- effort


def effort_to_ready(tax: Taxonomy, vc_id: str, ratings: dict[str, int],
                    calibration: Calibration, estimator: SkillEstimator | None = None) -> dict:
    """What it would actually take to get this piece of work to 'ready'.

    A score tells a student where they stand; this tells them what to do. We
    raise the skill that buys the most improvement, one rating point at a time,
    until the value construct clears the ready line - using the same bottleneck
    rule as the real score, so the advice points at the thing that is actually
    holding them back rather than at whatever is merely lowest.
    """
    vc = tax.vcs[vc_id]
    skill_ids = vc_skill_ids(vc)
    technical_ids = [s for s in skill_ids if tax.skill_type(s) == "technical"]
    transferable_ids = [s for s in skill_ids if tax.skill_type(s) != "technical"]

    start: dict[str, int] = {}
    for skill_id in skill_ids:
        if skill_id in ratings:
            start[skill_id] = int(ratings[skill_id])
        elif estimator is not None:
            start[skill_id] = estimator.rating_estimate(skill_id)
        else:
            return {"ready": False, "known": False, "points": None, "skills": [],
                    "summary": "Not enough answers to say"}

    def readiness_of(state: dict[str, int]) -> float:
        return _readiness(
            [calibration.transform(state[s]) for s in technical_ids],
            [calibration.transform(state[s]) for s in transferable_ids],
        ) or 0.0

    current = dict(start)
    points = 0
    while readiness_of(current) < READY_THRESHOLD and points < len(skill_ids) * 4:
        best_skill = None
        best_gain = 0.0
        baseline = readiness_of(current)
        for skill_id in skill_ids:
            if current[skill_id] >= 5:
                continue
            trial = dict(current)
            trial[skill_id] += 1
            gain = readiness_of(trial) - baseline
            if gain > best_gain:
                best_skill, best_gain = skill_id, gain
        if best_skill is None:
            break
        current[best_skill] += 1
        points += 1

    moved = [
        {"id": s, "name": tax.skill_name(s), "from": start[s], "to": current[s],
         "type": tax.skill_type(s)}
        for s in skill_ids if current[s] != start[s]
    ]

    if not moved:
        summary = "Already there"
    else:
        skills_word = "skill" if len(moved) == 1 else "skills"
        points_word = "point" if points == 1 else "points"
        summary = f"{len(moved)} {skills_word}, {points} {points_word}"

    # Every skill, not just the ones that need raising: this is what the skills
    # map draws, and a skill already at the level it needs is as much a part of
    # the picture as one that isn't.
    detail = [
        {
            "id": skill_id,
            "name": tax.skill_name(skill_id),
            "type": tax.skill_type(skill_id),
            "from": start[skill_id],
            "to": current[skill_id],
            "estimated": skill_id not in ratings,
            "met": current[skill_id] <= start[skill_id],
        }
        for skill_id in skill_ids
    ]

    return {
        "ready": readiness_of(current) >= READY_THRESHOLD,
        "known": True,
        "points": points,
        "skills": moved,
        "skills_detail": detail,
        "summary": summary,
    }


# ------------------------------------------------------------------ the grid


GRID_BOXES = {
    "sweet_spot": ("Sweet spot", "You picked it and you're ready for it."),
    "stretch": ("Stretch", "You picked it, but you're not there yet."),
    "hidden_strength": ("Hidden strength", "You didn't pick it, but you're good at it."),
    "park_it": ("Park it", "Not picked, and not a strength right now."),
}


def build_grid(items: list) -> dict:
    """Place each area on what-you-want against what-you're-ready-for.

    Interest is what they chose; ability is the cautious score, so a confidently
    rated but thinly evidenced area doesn't get to call itself a strength.
    """
    boxes: dict[str, list[dict]] = {key: [] for key in GRID_BOXES}
    for item in items:
        if item.adjusted is None:
            continue
        score = getattr(item, "readiness", None)
        if score is None:
            score = getattr(item, "fit", None)
        ready = (score or 0) >= READY_THRESHOLD
        if item.selected:
            key = "sweet_spot" if ready else "stretch"
        else:
            key = "hidden_strength" if ready else "park_it"
        boxes[key].append({
            "id": item.id,
            "name": item.name,
            "score": round(score or 0, 1),
            "adjusted": round(item.adjusted, 1),
            "band": item.band,
            "estimated": item.estimated,
        })

    for entries in boxes.values():
        entries.sort(key=lambda entry: -entry["adjusted"])

    return {
        "boxes": boxes,
        "labels": {key: {"title": title, "blurb": blurb} for key, (title, blurb) in GRID_BOXES.items()},
    }


# ------------------------------------------------------- adaptive questioning


BATCH_SIZE = 4
MAX_EXTRA_ROUNDS = 3


def next_question_batch(tax: Taxonomy, selections: dict, ratings: dict[str, int],
                        batch_size: int = BATCH_SIZE, max_rounds: int = MAX_EXTRA_ROUNDS) -> dict:
    """The next few skills worth asking about, chosen from the answers so far.

    A fixed list of extra questions wastes a student's patience on areas that
    were settled three answers ago. Instead we work out which business services
    could still overtake what they picked, and ask only about those - stopping
    as soon as no contender can close the gap.
    """
    role_id = selections.get("role_id")
    selected_services = set(selections.get("service_ids", []))
    selected_vcs = set(selections.get("vc_ids", []))
    ratings = {k: int(v) for k, v in ratings.items() if k in tax.skills and v}

    path_skills = set(tax.skills_of_vcs(list(selected_vcs)))
    extra_rated = [s for s in ratings if s not in path_skills]
    current_round = len(extra_rated) // batch_size

    missing_path = [s for s in path_skills if s not in ratings]
    if missing_path:
        return {"skills": [tax.skill_payload(s) for s in missing_path], "round": 0,
                "max_rounds": max_rounds, "done": False,
                "reason": "the skills behind the work you chose"}

    if current_round >= max_rounds:
        return _done(max_rounds, "asked as much as we usefully can")

    calibration = calibrate_ratings(ratings)

    def bounds(service: dict) -> tuple[float, float, int]:
        """Pessimistic and optimistic fit for a service: what it would score if
        every unanswered skill came back 1, and if every one came back 5."""
        low_vcs: list[float] = []
        high_vcs: list[float] = []
        unrated = 0
        for vc in tax.active_vcs_of_service(service["id"]):
            low_t, low_f, high_t, high_f = [], [], [], []
            for skill_id in vc_skill_ids(vc):
                known = calibration.score(skill_id)
                low = known if known is not None else calibration.transform(1)
                high = known if known is not None else calibration.transform(5)
                if known is None:
                    unrated += 1
                if tax.skill_type(skill_id) == "technical":
                    low_t.append(low)
                    high_t.append(high)
                else:
                    low_f.append(low)
                    high_f.append(high)
            low_value = _readiness(low_t, low_f)
            high_value = _readiness(high_t, high_f)
            if low_value is not None:
                low_vcs.append(low_value)
            if high_value is not None:
                high_vcs.append(high_value)
        return (_mean(low_vcs) or 0.0), (_mean(high_vcs) or 0.0), unrated

    services = tax.active_services_of_role(role_id)
    selected_fits = []
    for service in services:
        if service["id"] not in selected_services:
            continue
        low, high, _ = bounds(service)
        selected_fits.append((low + high) / 2)
    target = (_mean(selected_fits) or 0.0) + REDIRECT_MARGIN

    # A service is still worth asking about only while the answer is genuinely
    # open: it could beat the student's own choice, but isn't already certain to.
    contenders = []
    for service in services:
        if service["id"] in selected_services:
            continue
        low, high, unrated = bounds(service)
        if unrated and low < target < high:
            contenders.append((service, high - low, unrated))

    if not contenders:
        return _done(max_rounds, "your answers already separate these clearly")

    value: dict[str, float] = {}
    for service, width, unrated in contenders:
        for vc in tax.active_vcs_of_service(service["id"]):
            for skill_id in vc_skill_ids(vc):
                if skill_id in ratings:
                    continue
                # Wider uncertainty and fewer remaining questions both make a
                # single answer worth more; technical skills carry more of the
                # score, so they resolve the question faster.
                weight = 1.2 if tax.skill_type(skill_id) == "technical" else 1.0
                value[skill_id] = value.get(skill_id, 0.0) + (width / unrated) * weight

    if not value:
        return _done(max_rounds, "nothing left worth asking")

    chosen = sorted(value, key=lambda skill: (-value[skill], skill))[:batch_size]
    return {
        "skills": [tax.skill_payload(s) for s in chosen],
        "round": current_round + 1,
        "max_rounds": max_rounds,
        "done": False,
        "reason": "narrowing down " + ", ".join(service["name"] for service, _, _ in contenders[:2]),
    }


def _done(max_rounds: int, reason: str) -> dict:
    return {"skills": [], "round": max_rounds, "max_rounds": max_rounds, "done": True, "reason": reason}


# -------------------------------------------------------------------- evidence


def _evidence_corpus(profile: dict) -> str:
    """Everything the student told us they have actually done, as one lowercase
    blob we can search for skill names."""
    parts: list[str] = []
    for group in (profile.get("tool_stack") or {}).values():
        parts.extend(group if isinstance(group, list) else [])
    for key in ("work_experience", "projects", "competitions", "leadership"):
        for entry in profile.get(key) or []:
            if not isinstance(entry, dict):
                continue
            parts.extend(str(entry.get(f, "")) for f in
                         ("title", "description", "your_role", "organisation", "outcome", "name"))
            tech = entry.get("tech")
            if isinstance(tech, list):
                parts.extend(str(t) for t in tech)
    for key in ("why_this_role", "what_to_learn", "proudest_work"):
        parts.append(str((profile.get("motivation") or {}).get(key, "")))
    for cert in profile.get("certifications") or []:
        if isinstance(cert, dict):
            parts.append(str(cert.get("name", "")))
    return " ".join(parts).lower()


# Skill names don't always match what a student types. These are the handful of
# aliases worth spelling out; anything else falls back to the skill name itself.
SKILL_ALIASES = {
    "backend-languages": ["node", "python", "java", "javascript", "typescript", "go", "php", "ruby", "c#"],
    "backend-frameworks": ["express", "django", "flask", "fastapi", "spring", "nestjs", "laravel", "rails", ".net"],
    "sql": ["sql", "postgres", "mysql", "sqlite"],
    "orm-frameworks": ["orm", "prisma", "sqlalchemy", "sequelize", "hibernate", "mongoose"],
    "redis": ["redis"],
    "jwt": ["jwt", "json web token"],
    "oauth": ["oauth", "google login", "social login"],
    "payment-apis": ["stripe", "razorpay", "payment", "paypal"],
    "webhooks": ["webhook"],
    "message-queues": ["rabbitmq", "kafka", "sqs", "celery", "bullmq", "queue"],
    "swagger-openapi": ["swagger", "openapi"],
    "postman": ["postman"],
    "load-balancing": ["load balanc", "nginx"],
    "horizontal-scaling": ["scaling", "kubernetes", "docker"],
    "logging-apm-tools": ["grafana", "datadog", "new relic", "logging", "prometheus"],
    "error-tracking": ["sentry", "error tracking"],
    "indexing": ["index"],
    "email-apis": ["sendgrid", "ses", "resend", "nodemailer", "smtp"],
    "smtp-messaging-apis": ["twilio", "smtp", "sms"],
    "data-modelling": ["schema", "data model", "erd"],
    "cron-jobs-queues": ["cron", "scheduler", "queue"],
    "profiling": ["profiling", "profiler"],
    "monitoring-log-analysis": ["monitoring", "logs"],
    "api-integration": ["api integration", "third-party api", "rest api"],
    "rest-architecture": ["rest", "restful"],
    "json-data-parsing": ["json"],
    "password-hashing": ["bcrypt", "argon2", "hashing"],
    "auth-frameworks": ["auth0", "firebase auth", "passport", "authentication", "devise"],
    "sessions-cookies": ["session", "cookie"],
    "rbac": ["rbac", "role-based", "permissions"],
    "automated-api-testing": ["jest", "pytest", "supertest", "api test"],
    "caching": ["cache", "caching"],
}


def unevidenced_claims(tax: Taxonomy, ratings: dict[str, int], profile: dict) -> list[dict]:
    """Technical skills claimed at 4-5 with nothing in the student's history that
    mentions them.

    Only technical skills are checked. There is no honest way to look for
    evidence of 'problem solving' in a list of repo links, and flagging it would
    be a guess dressed up as a finding. This is a neutral note for a company
    reading the profile - a prompt for a question, not an accusation.
    """
    corpus = _evidence_corpus(profile)
    if not corpus.strip():
        return []

    flagged: list[dict] = []
    for skill_id, rating in ratings.items():
        if rating < 4 or tax.skill_type(skill_id) != "technical":
            continue
        name = tax.skill_name(skill_id).lower()
        needles = SKILL_ALIASES.get(skill_id, []) + [name]
        needles += [w for w in name.replace("/", " ").replace("&", " ").split() if len(w) > 4]
        if not any(needle in corpus for needle in needles):
            flagged.append({"id": skill_id, "name": tax.skill_name(skill_id), "rating": rating})
    return sorted(flagged, key=lambda item: item["name"])


def evidence_factor(tax: Taxonomy, ratings: dict[str, int], profile: dict) -> tuple[float, list[dict]]:
    """How much the student's own history backs up what they claimed.

    Before they fill in the follow-up section this sits at "unknown", below a
    corroborated claim and above a contradicted one - absence of a profile is not
    absence of evidence, so it must not be punished like one, but it cannot count
    for as much as a project that plainly demonstrates the skill either.
    """
    claims = [s for s, r in ratings.items() if r >= 4 and tax.skill_type(s) == "technical"]
    if not claims or not _evidence_corpus(profile).strip():
        return NO_EVIDENCE_FACTOR, []


    flagged = unevidenced_claims(tax, ratings, profile)
    share_backed = 1.0 - len(flagged) / len(claims)
    # Bounded: a thin profile should soften the numbers, never gut them, and a
    # well-backed one should be worth more than no profile at all.
    return round(EVIDENCE_FLOOR + (1.0 - EVIDENCE_FLOOR) * share_backed, 4), flagged


# --------------------------------------------------------------------- verdict


def _verdict(selected_scores: list[ServiceScore], alternatives: list[ServiceScore],
             quality: dict, overall_confidence: float) -> dict:
    """Judge the student's stated ambition against their own ratings.

    Deliberately conservative, and it compares cautious scores rather than raw
    ones, so telling someone to change direction takes real evidence and not
    just a confident hand on the 5 button.
    """
    evidenced = [s for s in selected_scores if s.adjusted is not None]
    if not evidenced:
        return {
            "code": "insufficient",
            "headline": "Not enough to go on yet",
            "reasoning": [
                "You didn't rate enough of the skills behind what you picked for us to say anything "
                "honest about fit. Come back and finish the ratings and this section fills in."
            ],
            "alternatives": [], "keep": [], "watch": [],
        }

    # Whether someone is ready is about what they scored; confidence decides which
    # area beats which, not whether we call them ready at all. Judging readiness
    # on the cautious figure would demote a genuinely strong student purely for
    # having answered fewer questions.
    good = [s for s in evidenced if s.fit >= READY_THRESHOLD]
    weak = [s for s in evidenced if s.fit < READY_THRESHOLD]
    average = sum(s.fit for s in evidenced) / len(evidenced)
    cautious = sum(s.adjusted for s in evidenced) / len(evidenced)
    reasoning: list[str] = []

    if not weak:
        code = "aligned"
        headline = "What you want and what you're good at line up"
        reasoning.append(
            f"Across the areas you chose you're averaging {average:.0f} out of 100, "
            f"which puts you in {'strong' if average >= 75 else 'workable'} territory to start contributing."
        )
        strongest = max(evidenced, key=lambda s: s.adjusted)
        reasoning.append(f"Your strongest area is {strongest.name}, at {strongest.fit:.0f}.")
    elif good:
        code = "partial"
        headline = "Part of what you picked fits — the rest is a stretch"
        reasoning.append(
            f"{', '.join(s.name for s in good)} sits where it needs to be "
            f"({', '.join(f'{s.fit:.0f}' for s in good)} out of 100)."
        )
        reasoning.append(
            f"{', '.join(s.name for s in weak)} is further off "
            f"({', '.join(f'{s.fit:.0f}' for s in weak)}). That's a gap you can close, "
            "but not one to hide from a company."
        )
    elif alternatives:
        code = "redirect"
        headline = "Your ratings point somewhere different from your pick"
        reasoning.append(
            f"Everything you selected is averaging {average:.0f} out of 100 on your own ratings — "
            "below where a company would expect you to start."
        )
    else:
        # Low everywhere with nothing better to point at is not a wrong choice,
        # and saying "you picked wrong" here would be both unkind and untrue.
        code = "early"
        headline = "It's early days — but you've picked a reasonable place to start"
        reasoning.append(
            f"You're averaging {average:.0f} out of 100 across what you chose, which is below where "
            "a company would expect you to start — but nothing else in this role scores higher for "
            "you either, so this is about experience rather than the wrong choice."
        )

    if alternatives:
        best = alternatives[0]
        line = (
            f"{best.name} scores {best.fit:.0f} on the same ratings, "
            f"{best.adjusted - cautious:.0f} points clear of what you picked once we account for "
            "how sure we are of each."
        )
        if best.estimated:
            line += " That one is partly an estimate — we didn't ask you about all of it."
        reasoning.append(
            line + (" It's worth a serious look as a starting point." if code == "redirect"
                    else " Worth knowing about.")
        )
    elif code == "early":
        reasoning.append(
            "The gap is closeable and the work below is where to start closing it."
        )

    caveats: list[str] = []
    if quality["over_rating"]:
        caveats.append(
            "you rated almost everything 4 or 5, so these numbers separate your skills less sharply "
            "than they look"
        )
    elif quality["notes"]:
        caveats.append(quality["notes"][0])
    if overall_confidence < 0.55:
        caveats.append("we only asked about part of this role, so the ranking is soft")

    return {
        "code": code,
        "headline": headline,
        "reasoning": reasoning,
        "caveat": ("One thing to hold in mind: " + "; and ".join(caveats) + ".") if caveats else None,
        "alternatives": [s.as_dict() for s in alternatives],
        "keep": [s.as_dict() for s in good],
        "watch": [s.as_dict() for s in weak],
    }


def _recommended_vcs(code: str, vc_scores: dict[str, VCScore]) -> list[VCScore]:
    """The three pieces of work to start on.

    Ready areas first, then whatever is closest to ready - because the useful
    answer to "where do I start" is the reachable thing, not the highest number.
    When a student's own picks hold up we recommend from their picks; telling
    someone who is already well matched to go elsewhere is just noise.
    """
    evidenced = [vc for vc in vc_scores.values() if vc.adjusted is not None]
    pool = [vc for vc in evidenced if vc.selected] if code in ("aligned", "early") else evidenced
    if len(pool) < 3:
        pool = pool + sorted((vc for vc in evidenced if vc not in pool),
                             key=lambda vc: -vc.adjusted)

    def rank(vc: VCScore) -> tuple:
        ready = (vc.readiness or 0) >= READY_THRESHOLD
        effort = (vc.effort or {}).get("points")
        return (
            0 if ready else 1,                       # reachable now beats promising later
            -vc.adjusted if ready else (effort if effort is not None else 99),
            -vc.adjusted,
            vc.name,
        )

    return sorted(pool, key=rank)[:3]


# ------------------------------------------------------------- the skills map


def build_skill_map(tax: Taxonomy, vc_scores: dict, selected_vcs: list[str],
                    recommended: list[VCScore]) -> dict:
    """Where each skill sits against where the work needs it.

    Covers the work the student chose plus whatever we are pointing them at -
    not the whole role, which would be a hundred rows nobody reads. The target
    for a skill is the level that would make its value construct ready, which is
    the same number the effort advice is built from, so the map and the advice
    can never disagree.
    """
    wanted: list[str] = list(selected_vcs)
    for vc in recommended:
        if vc.id not in wanted:
            wanted.append(vc.id)

    groups: list[dict] = []
    for service in tax.active_services_of_role(tax.role_of_vc(wanted[0]) if wanted else None) or []:
        entries = []
        for vc in tax.active_vcs_of_service(service["id"]):
            if vc["id"] not in wanted:
                continue
            score = vc_scores.get(vc["id"])
            if not score or not score.effort or not score.effort.get("skills_detail"):
                continue
            entries.append({
                "id": vc["id"],
                "name": vc.get("name", vc["id"]),
                "selected": vc["id"] in selected_vcs,
                "readiness": round(score.readiness, 1) if score.readiness is not None else None,
                "band": score.band,
                "band_plain": PLAIN_BANDS.get(score.band, ""),
                "ready": (score.effort or {}).get("points") == 0,
                "summary": (score.effort or {}).get("summary", ""),
                "skills": score.effort["skills_detail"],
            })
        if entries:
            groups.append({
                "service_id": service["id"],
                "service_name": service.get("name", service["id"]),
                "selected": any(entry["selected"] for entry in entries),
                "value_constructs": entries,
            })

    return {"groups": groups, "scale": 5}


# ---------------------------------------------------------------- the report


def build_report(tax: Taxonomy, selections: dict, ratings: dict[str, int],
                 profile: dict | None = None) -> dict:
    """Everything the report page and the company dashboard need, computed once."""
    profile = profile or {}
    role_id = selections.get("role_id")
    selected_services = set(selections.get("service_ids", []))
    selected_vcs = list(selections.get("vc_ids", []))
    role = tax.roles.get(role_id, {})

    ratings = {k: int(v) for k, v in ratings.items() if k in tax.skills and v}

    calibration = calibrate_ratings(ratings)
    quality = response_quality(ratings)
    factor, flagged = evidence_factor(tax, ratings, profile)
    estimator = SkillEstimator(tax, calibration, ratings)

    # Score every value construct in the role, not only the chosen ones - the
    # unchosen ones are where a hidden strength or a better starting point comes
    # from, and we can only see them by scoring them.
    vc_scores: dict[str, VCScore] = {}
    for service in tax.active_services_of_role(role_id):
        for vc in tax.active_vcs_of_service(service["id"]):
            score = score_value_construct(
                tax, vc["id"], calibration,
                selected=vc["id"] in selected_vcs,
                estimator=estimator,
                quality=quality["score"],
                evidence_factor=factor,
            )
            if score.evidenced:
                score.effort = effort_to_ready(tax, vc["id"], ratings, calibration, estimator)
            vc_scores[vc["id"]] = score

    service_scores = [
        score_service(tax, service["id"], vc_scores, ratings, service["id"] in selected_services)
        for service in tax.active_services_of_role(role_id)
    ]

    selected_score_objs = [s for s in service_scores if s.selected]
    evidenced_selected = [s for s in selected_score_objs if s.adjusted is not None]
    selected_average = _mean([s.fit for s in evidenced_selected])
    selected_cautious = _mean([s.adjusted for s in evidenced_selected])

    # The comparison that decides a redirect runs on cautious scores at both
    # ends, so an area we are unsure about cannot bluff its way past a pick we
    # measured properly.
    alternatives: list[ServiceScore] = []
    if selected_cautious is not None:
        alternatives = sorted(
            (s for s in service_scores
             if not s.selected and s.adjusted is not None
             and s.adjusted >= selected_cautious + REDIRECT_MARGIN),
            key=lambda s: s.adjusted,
            reverse=True,
        )[:2]

    # Role fit answers "how ready are they for the work they actually want", so
    # it is weighted over the services they chose. Averaging across all five
    # would drag the headline down with areas they deliberately skipped.
    scored = [s for s in (evidenced_selected or service_scores) if s.fit is not None and s.coverage > 0]
    role_fit = (sum(s.fit * s.coverage for s in scored) / sum(s.coverage for s in scored)
                if scored else None)
    overall_confidence = _mean([s.confidence for s in evidenced_selected]) or 0.0

    verdict = _verdict(selected_score_objs, alternatives, quality, overall_confidence)
    top_vcs = _recommended_vcs(verdict["code"], vc_scores)
    if top_vcs:
        first = top_vcs[0]
        effort = first.effort or {}
        # effort["ready"] means "reachable once these upgrades land", not "ready
        # now" - only a zero-point effort means they are already there.
        hedge = " (estimated — we didn't ask you about it directly)" if first.estimated else ""
        if effort.get("points") == 0:
            verdict["reasoning"].append(
                f"The most concrete place to begin is {first.name}{hedge} — you're already at "
                f"{first.readiness:.0f} on it, and it's a smaller commitment than a whole area."
            )
        elif effort.get("skills"):
            names = ", ".join(skill["name"] for skill in effort["skills"][:2])
            verdict["reasoning"].append(
                f"The closest thing to within reach is {first.name}{hedge}: {effort['summary'].lower()} "
                f"between you and ready, mostly {names}."
            )
    if verdict.get("caveat"):
        verdict["reasoning"].append(verdict["caveat"])

    path_skills = tax.skills_of_vcs(selected_vcs)
    rated_path = [(s, ratings[s], calibration.scores[s]) for s in path_skills if s in ratings]
    strengths = [
        {"id": s, "name": tax.skill_name(s), "rating": r, "score": round(v, 1), "type": tax.skill_type(s)}
        for s, r, v in sorted(rated_path, key=lambda row: (-row[2], tax.skill_name(row[0])))
    ][:5]
    gaps = [
        {"id": s, "name": tax.skill_name(s), "rating": r, "score": round(v, 1), "type": tax.skill_type(s)}
        for s, r, v in sorted(rated_path, key=lambda row: (row[2], tax.skill_name(row[0])))
        if v < READY_THRESHOLD
    ][:5]

    technical_values = [v for s, v in calibration.scores.items() if tax.skill_type(s) == "technical"]
    transferable_values = [v for s, v in calibration.scores.items() if tax.skill_type(s) != "technical"]

    # What to build next: the lowest skills that actually block either the work
    # the student chose or the work we are pointing them at, so the advice is
    # specific rather than a generic list of weaknesses.
    focus = {vc.id for vc in top_vcs} | set(selected_vcs)
    blocking: dict[str, dict] = {}
    for vc in vc_scores.values():
        if vc.id not in focus or not vc.effort or not vc.effort.get("skills"):
            continue
        for skill in vc.effort["skills"]:
            entry = blocking.setdefault(skill["id"], {**skill, "blocks": []})
            if vc.name not in entry["blocks"]:
                entry["blocks"].append(vc.name)
    skills_to_build = sorted(
        blocking.values(),
        key=lambda s: (s["from"], -len(s["blocks"]), s["name"]),
    )[:5]

    chosen_vc_scores = [vc_scores[vc_id] for vc_id in selected_vcs if vc_id in vc_scores]
    steps = next_steps(top_vcs, skills_to_build)
    plain = plain_summary(verdict["code"], selected_score_objs, alternatives,
                          top_vcs, chosen_vc_scores, steps)

    return {
        "plain": plain,
        "next_steps": steps,
        "skill_map": build_skill_map(tax, vc_scores, selected_vcs, top_vcs),
        "taxonomy_version": tax.version,
        "role": {"id": role_id, "name": role.get("name", role_id), "tagline": role.get("tagline", "")},
        "selected": {
            "services": [{"id": s.id, "name": s.name} for s in selected_score_objs],
            "value_constructs": [
                {"id": vc_id, "name": tax.vcs.get(vc_id, {}).get("name", vc_id),
                 "service_id": tax.service_of_vc.get(vc_id, "")}
                for vc_id in selected_vcs
            ],
        },
        "role_fit": {
            "score": round(role_fit, 1) if role_fit is not None else None,
            "band": band_for(role_fit)[0] if role_fit is not None else None,
            "band_label": band_for(role_fit)[1] if role_fit is not None else None,
            "band_plain": PLAIN_BANDS.get(band_for(role_fit)[0], "") if role_fit is not None else None,
            "confidence": round(overall_confidence, 2),
        },
        "selected_average": round(selected_average, 1) if selected_average is not None else None,
        "selected_cautious": round(selected_cautious, 1) if selected_cautious is not None else None,
        "services": [s.as_dict() for s in sorted(service_scores,
                                                 key=lambda s: (s.fit is None, -(s.fit or 0)))],
        "value_constructs": [vc.as_dict() for vc in vc_scores.values()],
        "grid": build_grid(service_scores),
        "grid_value_constructs": build_grid(list(vc_scores.values())),
        "verdict": verdict,
        "recommended_value_constructs": [vc.as_dict() for vc in top_vcs],
        "strengths": strengths,
        "gaps": gaps,
        "skills_to_build": skills_to_build,
        "balance": {
            "technical": round(_mean(technical_values), 1) if technical_values else None,
            "transferable": round(_mean(transferable_values), 1) if transferable_values else None,
            "technical_count": len(technical_values),
            "transferable_count": len(transferable_values),
        },
        "calibration": {
            "average_rating": round(calibration.average, 2),
            "spread": round(calibration.spread, 2),
            "weight": round(calibration.weight, 2),
            "flat": calibration.spread < FLAT_SPREAD,
        },
        "flags": {
            "over_rating_suspected": quality["over_rating"],
            "response_quality": quality["score"],
            "response_notes": quality["notes"],
            "ratings_count": len(ratings),
            "evidence_factor": factor,
            "evidence_seen": factor != 1.0 or bool(_evidence_corpus(profile).strip()),
            "unevidenced_skills": flagged,
        },
        "rating_scale": tax.rating_scale,
        "ready_threshold": READY_THRESHOLD,
    }


# ------------------------------------------------------------ plain language


def _join(names: list[str]) -> str:
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def next_steps(recommended: list[VCScore], skills_to_build: list[dict]) -> list[dict]:
    """At most three concrete things to do, in the order to do them.

    One piece of work to ask for, then the skills standing in the way of it.
    Only skills rated 3 or below become a "learn" step - telling someone who
    rated themselves 4 to go and learn it is advice nobody needs, and it would
    push the genuinely blocking skill off a three-item list.
    """
    steps: list[dict] = []

    if recommended:
        first = recommended[0]
        effort = first.effort or {}
        if effort.get("points") == 0:
            why = "You're already there. This is the smallest real piece of work you could ask for."
        elif effort.get("summary"):
            why = f"{effort['summary']} between you and ready — smaller than taking on a whole area."
        else:
            why = "The closest piece of real work to what you can already do."
        steps.append({
            "kind": "start",
            "title": first.name,
            "why": why,
            "estimated": first.estimated,
        })

    for skill in [s for s in skills_to_build if s.get("from", 5) <= 3][:2]:
        blocks = skill.get("blocks") or []
        why = f"You rated yourself {skill['from']} out of 5."
        if blocks:
            why += f" It's what's holding back {blocks[0]}."
        steps.append({
            "kind": "learn",
            "title": skill["name"],
            "why": why,
            "from": skill["from"],
            "to": skill["to"],
        })

    return steps[:3]


def plain_summary(code: str, selected_scores: list[ServiceScore], alternatives: list[ServiceScore],
                  recommended: list[VCScore], selected_vcs: list[VCScore],
                  steps: list[dict]) -> dict:
    """The whole report in two sentences, in the second person.

    This is the only thing some students will read, so it carries no numbers in
    the headline and no vocabulary from the model. The supporting line names the
    single most actionable fact we have - usually the skills in the way.
    """
    blocking = [step["title"] for step in steps if step["kind"] == "learn"]
    if blocking:
        verb = "is" if len(blocking) == 1 else "are"
        noun = "skill" if len(blocking) == 1 else "skills"
        blocking_line = f"{len(blocking)} {noun} {verb} holding you back: {_join(blocking)}."
    else:
        blocking_line = ""

    scored = [s for s in selected_scores if s.fit is not None]
    good = [s for s in scored if s.fit >= READY_THRESHOLD]
    weak = [s for s in scored if s.fit < READY_THRESHOLD]

    if code == "insufficient" or not scored:
        return {
            "headline": "We need a few more answers before we can tell you anything.",
            "detail": "Go back and finish rating the skills behind the work you picked, and this fills in.",
        }

    if code == "aligned":
        best = max(good or scored, key=lambda s: s.fit)
        headline = (f"You're well ahead on {best.name}." if best.fit >= 75
                    else f"You're ready to start on {best.name}.")
        ready_jobs = [vc for vc in selected_vcs if (vc.readiness or 0) >= READY_THRESHOLD]
        if blocking_line:
            detail = blocking_line
        elif ready_jobs:
            count = (f"All {len(selected_vcs)}" if len(ready_jobs) == len(selected_vcs)
                     else f"{len(ready_jobs)} of the {len(selected_vcs)}")
            detail = (f"{count} job{'' if len(selected_vcs) == 1 else 's'} you picked "
                      f"{'is' if len(ready_jobs) == 1 else 'are'} already within reach.")
        else:
            detail = "The area holds up overall — the jobs below are where to start."
        return {"headline": headline, "detail": detail}

    if code == "partial":
        headline = f"{good[0].name} fits you. {weak[0].name} doesn't yet."
        detail = blocking_line or "The difference is a handful of skills, listed below."
        return {"headline": headline, "detail": detail}

    if code == "redirect":
        chosen = max(scored, key=lambda s: s.fit)
        headline = f"You picked {chosen.name}, but you're stronger at {alternatives[0].name}."
        detail = "That's not a no. It's a better place to start — you can come back to what you picked."
        return {"headline": headline, "detail": detail}

    # early
    headline = "You're at the start of this, and that's normal."
    if recommended and (recommended[0].effort or {}).get("summary"):
        closest = recommended[0]
        detail = (f"Nothing here is out of reach: the closest job, {closest.name}, is "
                  f"{closest.effort['summary'].lower()} away.")
    else:
        detail = blocking_line or "Nothing here is out of reach — the work below is where to start."
    return {"headline": headline, "detail": detail}
