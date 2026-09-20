"""Tests for the fit algorithm.

These cover the behaviours that would be embarrassing to get wrong: fabricating
a weakness out of a missing answer, letting a confident guess outrank a measured
one, telling someone to change direction on noise, or handing back advice that
would not actually get them where we said it would.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scoring
from scoring import Calibration, SkillEstimator, calibrate_ratings, response_quality
from taxonomy_loader import load_taxonomy, vc_skill_ids

ROLE = "backend-development"
API = "api-development"
DB = "database-management"
AUTH = "authentication-user-management"


@pytest.fixture(scope="module")
def tax():
    return load_taxonomy(force=True)


def vcs_of(tax, service_id, count=None):
    ids = [vc["id"] for vc in tax.vcs_of_service(service_id)]
    return ids[:count] if count else ids


def rate(tax, vc_ids, value):
    return {skill: value for skill in tax.skills_of_vcs(vc_ids)}


def face_value(ratings):
    """A calibration that leaves ratings at face value, for isolating the parts
    of the maths that aren't about calibration."""
    calibration = Calibration(average=3.0, spread=0.0, weight=0.0, count=len(ratings))
    calibration.scores = {s: scoring.normalize(r) for s, r in ratings.items()}
    return calibration


def report_for(tax, service_ids, vc_ids, ratings, profile=None):
    return scoring.build_report(
        tax, {"role_id": ROLE, "service_ids": service_ids, "vc_ids": vc_ids}, ratings, profile
    )


# ------------------------------------------------------------------- basics


def test_normalize_maps_scale_to_percentage():
    assert scoring.normalize(1) == 0
    assert scoring.normalize(3) == 50
    assert scoring.normalize(5) == 100


@pytest.mark.parametrize("score,band", [(90, "strong"), (75, "strong"), (74.9, "emerging"),
                                        (60, "emerging"), (59, "stretch"), (45, "stretch"), (44, "gap")])
def test_band_boundaries(score, band):
    assert scoring.band_for(score)[0] == band


# -------------------------------------------------------------- calibration


def test_flat_top_ratings_land_below_full_marks(tax):
    """Everything rated 5 says nothing about which skills are stronger, so it
    should not read as a perfect score."""
    calibration = calibrate_ratings({f"skill-{i}": 5 for i in range(12)})
    assert calibration.spread == 0
    assert calibration.scores["skill-0"] == pytest.approx(85.0)


def test_a_harsh_rater_is_lifted_relative_to_their_own_scale(tax):
    harsh = {"a": 3, "b": 2, "c": 1, "d": 2, "e": 3, "f": 1,
             "g": 2, "h": 3, "i": 1, "j": 2, "k": 3, "l": 2}
    calibration = calibrate_ratings(harsh)
    # Their best answer is a 3, which at face value is 50.
    assert calibration.scores["a"] > scoring.normalize(3)
    # And their worst still sits below their best.
    assert calibration.scores["c"] < calibration.scores["a"]


def test_calibration_leans_on_face_value_when_there_is_little_to_go_on(tax):
    few = calibrate_ratings({"a": 5, "b": 1})
    many = calibrate_ratings({f"s{i}": (5 if i % 2 else 1) for i in range(12)})
    assert few.weight < many.weight
    assert many.weight == pytest.approx(scoring.CALIBRATION_WEIGHT)


def test_calibration_transform_works_on_hypothetical_ratings(tax):
    """Effort advice projects what a higher rating would do, so the transform has
    to apply to values the student has not given."""
    calibration = calibrate_ratings({f"s{i}": 3 for i in range(12)} | {"high": 5})
    assert calibration.transform(5) > calibration.transform(3)


# ---------------------------------------------------------------- bottleneck


def test_a_hard_gap_drags_the_score_below_the_average(tax):
    vc_id = "vc-design-rest-apis"
    vc = tax.vcs[vc_id]
    lopsided = {vc["technical_skills"][0]: 5, vc["technical_skills"][1]: 1,
                vc["transferable_skills"][0]: 5, vc["transferable_skills"][1]: 5}
    score = scoring.score_value_construct(tax, vc_id, face_value(lopsided), selected=True)

    straight_average = 0.6 * 50 + 0.4 * 100          # what plain averaging would say
    assert score.readiness < straight_average - 10


def test_an_even_profile_is_barely_touched_by_the_bottleneck(tax):
    vc_id = "vc-design-rest-apis"
    vc = tax.vcs[vc_id]
    even = {vc["technical_skills"][0]: 5, vc["technical_skills"][1]: 4,
            vc["transferable_skills"][0]: 4, vc["transferable_skills"][1]: 4}
    score = scoring.score_value_construct(tax, vc_id, face_value(even), selected=True)

    base = 0.6 * ((100 + 75) / 2) + 0.4 * 75
    assert base - score.readiness < 5


def test_technical_outweighs_transferable(tax):
    vc_id = "vc-design-rest-apis"
    vc = tax.vcs[vc_id]
    strong_technical = {s: 5 for s in vc["technical_skills"]} | {s: 1 for s in vc["transferable_skills"]}
    strong_transferable = {s: 1 for s in vc["technical_skills"]} | {s: 5 for s in vc["transferable_skills"]}

    technical_first = scoring.score_value_construct(tax, vc_id, face_value(strong_technical), True)
    transferable_first = scoring.score_value_construct(tax, vc_id, face_value(strong_transferable), True)
    assert technical_first.readiness > transferable_first.readiness


# ------------------------------------------------------- missing vs. weak


def test_an_unrated_value_construct_is_not_scored_zero(tax):
    score = scoring.score_value_construct(tax, "vc-design-rest-apis", face_value({}), selected=False)
    assert score.evidenced is False
    assert score.readiness is None
    assert score.band == ""


def test_one_answer_in_four_is_not_enough_to_score(tax):
    vc = tax.vcs["vc-design-rest-apis"]
    one = {vc_skill_ids(vc)[0]: 5}
    score = scoring.score_value_construct(tax, "vc-design-rest-apis", face_value(one), selected=False)
    assert score.coverage == 0.25
    assert score.evidenced is False


def test_half_rated_is_enough_to_score(tax):
    vc = tax.vcs["vc-design-rest-apis"]
    half = {skill: 5 for skill in vc_skill_ids(vc)[:2]}
    score = scoring.score_value_construct(tax, "vc-design-rest-apis", face_value(half), selected=False)
    assert score.evidenced is True
    assert score.readiness == pytest.approx(100.0)


# ---------------------------------------------------------------- confidence


def test_response_quality_penalises_straight_lining(tax):
    considered = response_quality({f"s{i}": [5, 3, 4, 2, 5, 3, 1, 4, 2, 5, 3, 4][i] for i in range(12)})
    identical = response_quality({f"s{i}": 4 for i in range(12)})
    assert considered["score"] > identical["score"]
    assert identical["score"] == scoring.MIN_RESPONSE_QUALITY
    assert identical["notes"]


def test_confidence_lowers_the_ranking_score_but_not_the_displayed_one(tax):
    vc_id = "vc-design-rest-apis"
    vc = tax.vcs[vc_id]
    ratings = {s: 4 for s in vc_skill_ids(vc)}
    sure = scoring.score_value_construct(tax, vc_id, face_value(ratings), True, quality=1.0)
    unsure = scoring.score_value_construct(tax, vc_id, face_value(ratings), True, quality=0.5)

    assert sure.readiness == unsure.readiness          # the number they see doesn't move
    assert unsure.adjusted < sure.adjusted             # the number we rank on does
    assert unsure.confidence < sure.confidence


def test_an_over_rater_loses_their_edge_once_confidence_is_applied(tax):
    """Straight 5s still score higher than honest 3s and 4s - we cannot prove
    someone is inflating. But the gap must narrow, not widen."""
    vc_ids = vcs_of(tax, API, 3)
    honest = report_for(tax, [API], vc_ids,
                        {s: (4 if i % 2 else 3) for i, s in enumerate(tax.skills_of_vcs(vc_ids))})
    inflated = report_for(tax, [API], vc_ids, rate(tax, vc_ids, 5))

    honest_service = next(s for s in honest["services"] if s["id"] == API)
    inflated_service = next(s for s in inflated["services"] if s["id"] == API)

    raw_gap = inflated_service["fit"] - honest_service["fit"]
    cautious_gap = inflated_service["adjusted"] - honest_service["adjusted"]
    assert cautious_gap < raw_gap
    assert inflated_service["confidence"] < honest_service["confidence"]
    assert inflated["flags"]["over_rating_suspected"] is True


# ----------------------------------------------------------------- estimates


def test_an_estimate_is_marked_and_costs_confidence(tax):
    """Rating one area tells us something about a neighbouring one - but it has
    to be labelled, and trusted less than something we actually asked."""
    vc_ids = vcs_of(tax, DB)
    ratings = rate(tax, vc_ids, 5)
    report = report_for(tax, [DB], vc_ids, ratings)

    measured = next(s for s in report["services"] if s["id"] == DB)
    estimated = [s for s in report["services"] if s["estimated"] and s["fit"] is not None]

    assert measured["estimated"] is False
    assert estimated, "rating one area should let us say something about its neighbours"
    for service in estimated:
        assert service["confidence"] < measured["confidence"]
        assert service["fit"] - service["adjusted"] > measured["fit"] - measured["adjusted"]


def test_an_estimate_never_outranks_a_measured_area_at_the_same_raw_score(tax):
    vc_ids = vcs_of(tax, DB)
    report = report_for(tax, [DB], vc_ids, rate(tax, vc_ids, 5))
    measured = next(s for s in report["services"] if s["id"] == DB)
    for service in report["services"]:
        if service["estimated"] and service["fit"] is not None:
            assert service["adjusted"] < measured["adjusted"]


def test_estimation_falls_back_quietly_when_nothing_relates(tax):
    calibration = calibrate_ratings({"sql": 5})
    estimator = SkillEstimator(tax, calibration, {"sql": 5})
    # oauth shares no value construct with sql, so there is no real signal.
    estimate = estimator.estimate("oauth")
    assert estimate is None or estimate[1] <= 0.2


# -------------------------------------------------------------------- effort


def test_effort_advice_actually_gets_you_there(tax):
    vc_id = "vc-design-rest-apis"
    vc = tax.vcs[vc_id]
    ratings = {s: 2 for s in vc_skill_ids(vc)}
    calibration = face_value(ratings)

    effort = scoring.effort_to_ready(tax, vc_id, ratings, calibration)
    assert effort["ready"] is True
    assert effort["points"] > 0

    improved = dict(ratings)
    for skill in effort["skills"]:
        improved[skill["id"]] = skill["to"]
    after = scoring.score_value_construct(tax, vc_id, face_value(improved), selected=True)
    assert after.readiness >= scoring.READY_THRESHOLD


def test_already_ready_work_needs_no_effort(tax):
    vc_id = "vc-design-rest-apis"
    ratings = {s: 5 for s in vc_skill_ids(tax.vcs[vc_id])}
    effort = scoring.effort_to_ready(tax, vc_id, ratings, face_value(ratings))
    assert effort["points"] == 0
    assert effort["skills"] == []
    assert effort["summary"] == "Already there"


def test_effort_targets_the_blocking_skill_not_merely_the_lowest(tax):
    """The bottleneck rule means the weak technical skill is what's holding the
    score down, so that is what the advice should name first."""
    vc_id = "vc-design-rest-apis"
    vc = tax.vcs[vc_id]
    ratings = {vc["technical_skills"][0]: 5, vc["technical_skills"][1]: 1,
               vc["transferable_skills"][0]: 3, vc["transferable_skills"][1]: 3}
    effort = scoring.effort_to_ready(tax, vc_id, ratings, face_value(ratings))
    assert vc["technical_skills"][1] in {skill["id"] for skill in effort["skills"]}


# ---------------------------------------------------------------- the grid


def test_the_grid_places_each_area_by_choice_and_readiness(tax):
    chosen = vcs_of(tax, API, 3)
    report = report_for(tax, [API], chosen, rate(tax, chosen, 5))
    boxes = report["grid"]["boxes"]

    placed = {entry["id"] for box in boxes.values() for entry in box}
    assert API in placed
    assert API in {entry["id"] for entry in boxes["sweet_spot"]}
    for entry in boxes["hidden_strength"] + boxes["park_it"]:
        assert entry["id"] != API


def test_readiness_in_the_grid_matches_the_band_the_student_is_shown(tax):
    """A student told "Emerging fit" must not simultaneously be filed under
    "not ready" - the band and the box have to agree."""
    chosen = vcs_of(tax, API, 3)
    report = report_for(tax, [API], chosen,
                        {s: (4 if i % 2 else 3) for i, s in enumerate(tax.skills_of_vcs(chosen))})
    boxes = report["grid"]["boxes"]
    for service in report["services"]:
        if service["fit"] is None:
            continue
        ready_boxes = {e["id"] for e in boxes["sweet_spot"] + boxes["hidden_strength"]}
        assert (service["id"] in ready_boxes) == (service["fit"] >= scoring.READY_THRESHOLD)


def test_weak_choices_land_in_stretch_not_sweet_spot(tax):
    chosen = vcs_of(tax, API, 3)
    report = report_for(tax, [API], chosen, rate(tax, chosen, 1))
    assert API in {entry["id"] for entry in report["grid"]["boxes"]["stretch"]}
    assert not report["grid"]["boxes"]["sweet_spot"]


# ---------------------------------------------------------------- verdicts


def test_strong_ratings_on_chosen_work_come_back_aligned(tax):
    chosen = vcs_of(tax, API, 3)
    report = report_for(tax, [API], chosen, rate(tax, chosen, 5))
    assert report["verdict"]["code"] == "aligned"


def test_a_clear_alternative_produces_a_redirect(tax):
    chosen = vcs_of(tax, API, 3)
    ratings = rate(tax, vcs_of(tax, DB), 5) | rate(tax, vcs_of(tax, AUTH), 5)
    ratings.update(rate(tax, chosen, 1))

    report = report_for(tax, [API], chosen, ratings)
    assert report["verdict"]["code"] == "redirect"
    assert report["verdict"]["alternatives"]


def test_low_everywhere_is_called_early_not_a_wrong_choice(tax):
    """Telling a beginner they picked the wrong thing, when nothing else scores
    higher for them either, would be both unkind and untrue."""
    chosen = vcs_of(tax, API, 3)
    report = report_for(tax, [API], chosen, rate(tax, chosen, 1))
    assert report["verdict"]["code"] == "early"
    assert report["verdict"]["alternatives"] == []


def test_mixed_ratings_produce_a_partial_verdict(tax):
    chosen = vcs_of(tax, API, 2) + vcs_of(tax, DB, 2)
    ratings = rate(tax, vcs_of(tax, DB, 2), 1) | rate(tax, vcs_of(tax, API, 2), 5)
    report = report_for(tax, [API, DB], chosen, ratings)

    assert report["verdict"]["code"] == "partial"
    assert report["verdict"]["keep"] and report["verdict"]["watch"]


def test_no_ratings_gives_an_honest_non_answer(tax):
    chosen = vcs_of(tax, API, 3)
    report = report_for(tax, [API], chosen, {})
    assert report["verdict"]["code"] == "insufficient"
    assert report["verdict"]["alternatives"] == []


def test_a_redirect_requires_a_real_margin_on_cautious_scores(tax):
    chosen = vcs_of(tax, API, 3)
    ratings = rate(tax, vcs_of(tax, DB), 3) | rate(tax, chosen, 3)
    report = report_for(tax, [API], chosen, ratings)
    for alternative in report["verdict"]["alternatives"]:
        assert alternative["adjusted"] >= report["selected_cautious"] + scoring.REDIRECT_MARGIN


def test_every_value_construct_in_the_role_is_scored(tax):
    chosen = vcs_of(tax, API, 3)
    report = report_for(tax, [API], chosen, rate(tax, chosen, 4))
    assert len(report["value_constructs"]) == len(tax.vcs)
    assert len(report["services"]) == len(tax.services_of_role(ROLE))


# ----------------------------------------------------------------- evidence


def test_a_claimed_skill_with_no_history_is_flagged(tax):
    ratings = rate(tax, ["vc-write-database-queries"], 5)
    profile = {"projects": [{"title": "Poster site", "description": "A static page", "tech": ["HTML"]}]}
    flagged = {skill["id"] for skill in scoring.unevidenced_claims(tax, ratings, profile)}
    assert "sql" in flagged and "orm-frameworks" in flagged


def test_evidence_in_a_project_clears_the_flag(tax):
    ratings = rate(tax, ["vc-write-database-queries"], 5)
    profile = {
        "projects": [{"title": "Attendance tracker", "description": "Postgres-backed API", "tech": ["SQLAlchemy"]}],
        "tool_stack": {"Databases": ["PostgreSQL"]},
    }
    flagged = {skill["id"] for skill in scoring.unevidenced_claims(tax, ratings, profile)}
    assert "sql" not in flagged and "orm-frameworks" not in flagged


def test_transferable_skills_are_never_flagged(tax):
    ratings = {s: 5 for s, skill in tax.skills.items() if skill["type"] == "transferable"}
    profile = {"projects": [{"title": "Something", "description": "Anything"}]}
    assert scoring.unevidenced_claims(tax, ratings, profile) == []


def test_no_profile_sits_between_backed_up_and_contradicted(tax):
    """Not having reached the optional section is not evidence of anything - but
    it cannot be worth as much as a project that plainly shows the skill, or
    filling the section in could only ever hurt."""
    ratings = rate(tax, ["vc-write-database-queries"], 5)
    unknown, _ = scoring.evidence_factor(tax, ratings, {})
    thin, thin_flags = scoring.evidence_factor(
        tax, ratings, {"projects": [{"title": "Poster site", "description": "A static page"}]})
    backed, backed_flags = scoring.evidence_factor(tax, ratings, {
        "projects": [{"title": "Attendance tracker", "description": "Postgres-backed API",
                      "tech": ["SQLAlchemy"]}],
        "tool_stack": {"Databases": ["PostgreSQL"]},
    })

    assert thin < unknown < backed
    assert thin_flags and not backed_flags
    assert scoring.EVIDENCE_FLOOR <= thin and backed <= 1.0


# ---------------------------------------------------- adaptive questioning


def test_the_first_round_is_the_skills_behind_the_choices(tax):
    chosen = vcs_of(tax, API, 3)
    selections = {"role_id": ROLE, "service_ids": [API], "vc_ids": chosen}
    batch = scoring.next_question_batch(tax, selections, {})

    assert batch["round"] == 0 and batch["done"] is False
    assert {s["id"] for s in batch["skills"]} == set(tax.skills_of_vcs(chosen))


def test_adaptive_rounds_terminate_and_never_repeat_a_question(tax):
    chosen = vcs_of(tax, API, 3)
    selections = {"role_id": ROLE, "service_ids": [API], "vc_ids": chosen}
    ratings = rate(tax, chosen, 4)
    asked: list[str] = []

    for _ in range(10):
        batch = scoring.next_question_batch(tax, selections, ratings)
        if batch["done"]:
            break
        for skill in batch["skills"]:
            assert skill["id"] not in ratings, "asked about a skill that was already rated"
            asked.append(skill["id"])
            ratings[skill["id"]] = 3
    else:
        pytest.fail("adaptive questioning never finished")

    assert len(asked) == len(set(asked))
    assert len(asked) <= scoring.BATCH_SIZE * scoring.MAX_EXTRA_ROUNDS


def test_questioning_stops_early_when_the_answer_is_already_clear(tax):
    """Nothing can overtake a chosen area rated at the ceiling, so there is
    nothing left worth asking."""
    chosen = vcs_of(tax, API)
    selections = {"role_id": ROLE, "service_ids": [API], "vc_ids": chosen}
    ratings = rate(tax, chosen, 5)

    rounds = 0
    while rounds < 10:
        batch = scoring.next_question_batch(tax, selections, ratings)
        if batch["done"]:
            break
        for skill in batch["skills"]:
            ratings[skill["id"]] = 1
        rounds += 1

    assert batch["done"] is True
    assert rounds < scoring.MAX_EXTRA_ROUNDS


# ------------------------------------------------------------- guidance


def test_skills_to_build_name_what_actually_blocks_the_work(tax):
    chosen = vcs_of(tax, API, 3)
    skills = tax.skills_of_vcs(chosen)
    ratings = {skill: (2 if index < 3 else 5) for index, skill in enumerate(skills)}
    report = report_for(tax, [API], chosen, ratings)

    assert report["skills_to_build"]
    for skill in report["skills_to_build"]:
        assert skill["to"] > skill["from"]
        assert skill["blocks"]


def test_recommendations_prefer_what_is_within_reach(tax):
    chosen = vcs_of(tax, API, 3)
    report = report_for(tax, [API], chosen, rate(tax, chosen, 3))
    recommended = report["recommended_value_constructs"]
    assert recommended
    efforts = [vc["effort"]["points"] for vc in recommended if vc["effort"]]
    assert efforts == sorted(efforts) or all(vc["adjusted"] >= scoring.READY_THRESHOLD for vc in recommended)


# ------------------------------------------------- the plain-language layer


def all_verdict_shapes(tax):
    """One report per verdict code, so the plain wording is exercised on all of
    them rather than only the happy path."""
    api = vcs_of(tax, API)
    db = vcs_of(tax, DB)
    return {
        "aligned": report_for(tax, [API], api[:3], rate(tax, api[:3], 5)),
        "early": report_for(tax, [API], api[:3], rate(tax, api[:3], 1)),
        "redirect": report_for(tax, [API], api[:3], rate(tax, db, 5) | rate(tax, api[:3], 1)),
        "partial": report_for(tax, [API, DB], api[:2] + db[:2],
                              rate(tax, db[:2], 1) | rate(tax, api[:2], 5)),
        "insufficient": report_for(tax, [API], api[:3], {}),
    }


def test_every_verdict_gets_a_plain_headline(tax):
    for expected, report in all_verdict_shapes(tax).items():
        plain = report["plain"]
        assert report["verdict"]["code"] == expected
        assert plain["headline"] and plain["detail"], expected
        assert plain["headline"].endswith("."), f"{expected}: headline should be a sentence"
        assert len(plain["headline"]) < 140, f"{expected}: headline too long to read at a glance"


def test_the_headline_names_a_real_area(tax):
    """A sentence that says "you're ready to start on X" has to have X be
    something the student can actually go and look up."""
    names = {service["name"] for service in tax.services.values()}
    for code, report in all_verdict_shapes(tax).items():
        if code in ("early", "insufficient"):
            continue                          # these two deliberately name no area
        assert any(name in report["plain"]["headline"] for name in names), code


def test_the_headline_carries_no_numbers_or_jargon(tax):
    banned = ["value construct", "business service", "transferable", "confidence",
              "adjusted", "cautious", "readiness"]
    for code, report in all_verdict_shapes(tax).items():
        headline = report["plain"]["headline"].lower()
        assert not any(word in headline for word in banned), f"{code}: {headline}"
        assert not any(character.isdigit() for character in headline), f"{code}: {headline}"


def test_next_steps_are_at_most_three_and_lead_with_something_to_start(tax):
    for code, report in all_verdict_shapes(tax).items():
        steps = report["next_steps"]
        assert len(steps) <= 3, code
        if code == "insufficient":
            continue
        assert steps and steps[0]["kind"] == "start", code
        assert all(step["title"] and step["why"] for step in steps), code


def test_next_steps_never_tell_you_to_learn_something_you_already_rate_highly(tax):
    """Telling someone who rated themselves 4 to go and learn it wastes one of
    only three slots that could have named the skill actually blocking them."""
    for code, report in all_verdict_shapes(tax).items():
        for step in report["next_steps"]:
            if step["kind"] == "learn":
                assert step["from"] <= 3, f"{code}: {step['title']} rated {step['from']}"
                assert step["to"] > step["from"]


def test_the_blocking_skills_named_in_the_detail_match_the_steps(tax):
    """The supporting sentence and the numbered list have to agree - two
    different answers to "what's holding me back" is worse than one."""
    report = report_for(tax, [API, DB], vcs_of(tax, API, 2) + vcs_of(tax, DB, 2),
                        rate(tax, vcs_of(tax, DB, 2), 1) | rate(tax, vcs_of(tax, API, 2), 5))
    learn = [step["title"] for step in report["next_steps"] if step["kind"] == "learn"]
    if learn:
        for name in learn:
            assert name in report["plain"]["detail"]


def test_every_score_carries_a_plain_label(tax):
    """No number should ever reach a student without a word next to it."""
    report = report_for(tax, [API], vcs_of(tax, API, 3), rate(tax, vcs_of(tax, API, 3), 4))
    assert report["role_fit"]["band_plain"] in scoring.PLAIN_BANDS.values()
    for service in report["services"]:
        if service["fit"] is not None:
            assert service["band_plain"] in scoring.PLAIN_BANDS.values(), service["name"]
    for vc in report["value_constructs"]:
        if vc["readiness"] is not None:
            assert vc["band_plain"] in scoring.PLAIN_BANDS.values(), vc["name"]


def test_an_area_is_only_called_guessed_when_guessing_drives_it(tax):
    """The area a student rated most thoroughly must never come back marked as
    something we guessed - that reads as a contradiction of their own effort."""
    chosen = vcs_of(tax, API, 3)
    report = report_for(tax, [API], chosen, rate(tax, chosen, 4))
    api_service = next(s for s in report["services"] if s["id"] == API)
    assert api_service["estimated"] is False
