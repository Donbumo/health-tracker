"""Deterministic Gym progression and metric contracts; fictional values only."""
from decimal import Decimal

from app.services.gym_progression import GymProgressionEngine, e1rm


def prescription(rmin=6, rmax=8, load="80", mode="direct_total"):
    return {"name": "QA Bench", "exercise_order": 1, "sets": [
        {"set_number": n, "reps_min": rmin, "reps_max": rmax,
         "load_value": load, "load_unit": "kg", "load_mode": mode, "rir": "2"}
        for n in (1, 2, 3)
    ]}


def row(values, date="01/10/2026", signature=None, unit="kg"):
    return {"date": date, "signature": signature, "sets": [
        {"number": n, "set_number": n, "load_kg": "80", "reps": reps,
         "rir": "2", "rpe": None, "mode": "direct_total", "unit": unit}
        for n, reps in enumerate(values, 1)
    ]}


def evaluate(sessions, p=None):
    p = p or prescription()
    from app.services.gym_progression import target_signature
    for item in sessions:
        item["signature"] = target_signature(p)
    return GymProgressionEngine.evaluate(prescription=p, identity="exercise-qa", program_id="program-qa",
        program_revision=1, revision_id="revision-qa", prescription_id="1:1:1", sessions=sessions)


def test_epley_uses_one_eligible_set_and_rejects_invalid_inputs():
    assert e1rm(80, 8, "direct_total") == Decimal("101.3333333333333333333333334")
    assert e1rm(80, 10, "direct_total") is not None
    assert e1rm(80, 11, "direct_total") is None
    assert e1rm(0, 5, "direct_total") is None
    assert e1rm(80, 5, "assistance") is None


def test_double_progression_increase_load_requires_two_complete_top_sessions():
    result = evaluate([row((8, 8, 8), date="24/09/2026"), row((8, 8, 8), date="01/10/2026")])
    assert result["state"] == "increase_load"
    assert result["proposal"]["load"] == "82.50"


def test_increase_reps_and_missing_effort_are_explicit():
    result = evaluate([row((7, 7, 7), date="24/09/2026"), row((8, 7, 7), date="01/10/2026")])
    assert result["state"] == "increase_reps"
    rows = [row((8, 8, 8), date="24/09/2026"), row((8, 8, 8), date="01/10/2026")]
    rows[1]["sets"][0]["rir"] = None
    result = evaluate(rows)
    assert result["state"] == "increase_load"
    assert any("RIR no disponible" in line for line in result["evidence"])


def test_review_for_identity_or_incompatible_mode():
    p = prescription(mode="bodyweight")
    assert evaluate([row((8, 8, 8)), row((8, 8, 8))], p)["state"] == "insufficient_data"
    p = prescription()
    result = GymProgressionEngine.evaluate(prescription=p, identity=None, program_id="p", program_revision=1,
        revision_id="r", prescription_id="1:1:1", sessions=[])
    assert result["state"] == "review"
