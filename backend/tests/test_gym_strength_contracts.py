"""Metrics, writes and public UX gates on isolated fictional data."""
import copy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from app.extensions import db
from app.models import User, TrainingSession, TrainingSet, TrainingPlanVersion
from app.services.gym_strength import StrengthReader, chart_projection
from app.services.gym_progression import e1rm, GymProgressionEngine, target_signature
from app.services.gym_progression_confirm import preview, confirm, _serializer, STALE
from app.services.gym_programs import GymError
from app.services.gym_sessions import start_session, workout_context
from app.services.training_plans import get_active_version
from tests.conftest import login
from tests.gym_strength_fixtures import strength_fixture
from tests.test_gym_progression import prescription, row, evaluate

@pytest.mark.parametrize("reps,expected", [(1,"82.6667"),(5,"93.3333"),(10,"106.6667")])
def test_epley_reps(reps, expected):
    assert e1rm(80,reps,"direct_total").quantize(Decimal(".0001")) == Decimal(expected)

@pytest.mark.parametrize("mode",["bodyweight","bodyweight_plus","assistance","duration_distance","unknown"])
def test_epley_excludes_modes(mode):
    assert e1rm(80,5,mode) is None

def test_epley_units():
    assert e1rm(Decimal("45.359237"),5,"direct_total","lb").quantize(Decimal(".01")) == Decimal("116.67")

@pytest.mark.parametrize("variant,state", [("missing_rir","increase_load"),("effort","maintain"),
    ("unit","review"),("mode","review"),("partial","insufficient_data"),("duplicate","review"),
    ("three_below","review"),("regression","review"),("one","insufficient_data"),
    ("one_top","maintain"),("zero","increase_load")])
def test_engine_decisions(variant,state):
    p=prescription()
    rows=[row((8,8,8)),row((8,8,8))]
    if variant == "missing_rir": rows[1]["sets"][0]["rir"] = None
    if variant == "effort": rows[1]["sets"][0]["rir"] = "1"
    if variant == "unit": rows[1]["sets"][0]["unit"] = "lb"
    if variant == "mode": rows[1]["sets"][0]["mode"] = "selector_stack"
    if variant == "partial": rows[1]["sets"].pop()
    if variant == "duplicate": rows[1]["sets"][0]["number"] = 2
    if variant == "three_below": rows=[row((5,5,5)) for _ in range(3)]
    if variant == "regression": rows=[row((8,8,8)),row((8,7,7)),row((7,7,7))]
    if variant == "one": rows=rows[:1]
    if variant == "one_top": rows[0]=row((8,7,7))
    if variant == "zero":
        p=prescription(load="0")
        for r in rows:
            for s in r["sets"]: s["load_kg"]="0"
    result=evaluate(rows,p)
    assert result["state"] == state
    if variant == "missing_rir": assert any("RIR no disponible" in v for v in result["evidence"])
    if variant == "zero": assert result["proposal"]["field_changes"] == []

def test_machine_is_conceptual_and_profile_increment_is_honored():
    p=prescription(); rows=[row((8,8,8)),row((8,8,8))]
    for r in rows: r["signature"]=target_signature(p)
    args=dict(prescription=p,identity="qa",program_id="qa",program_revision=1,revision_id="qa",prescription_id="1:1:1",sessions=rows)
    assert GymProgressionEngine.evaluate(**args,equipment="machine")["proposal"]["field_changes"] == []
    assert GymProgressionEngine.evaluate(**args,profile={"mode":"direct_total","unit":"kg","increments":["1.25"]})["proposal"]["load"] == "81.25"

def test_rpe_contradiction_blocks_load_increase():
    p = prescription()
    for target in p["sets"]:
        target["rpe"] = 8
    rows = [row((8, 8, 8)), row((8, 8, 8))]
    rows[-1]["sets"][0]["rpe"] = "9"
    assert evaluate(rows, p)["state"] == "maintain"

def test_pound_increment_remains_in_original_unit():
    p = prescription()
    for target in p["sets"]:
        target.update(load_unit="lb", load_value="100", weight_kg="45.359237")
    rows = [row((8, 8, 8)), row((8, 8, 8))]
    for occurrence in rows:
        for item in occurrence["sets"]:
            item.update(unit="lb", load_kg="45.359237")
    result = evaluate(rows, p)
    assert result["state"] == "increase_load"
    assert result["proposal"]["load"] == "105.00"
    assert result["proposal"]["field_changes"][0]["load_unit"] == "lb"

def test_valid_week_comparison_and_summary_variants(app, user):
    now = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
    plan, identities, sessions = strength_fixture(user, now=now)
    # Remove the optional and unresolved fixture occurrences from both weeks.
    for record in sessions:
        for occurrence in list(record.exercises):
            if occurrence.planned_exercise_order >= 4:
                db.session.delete(occurrence)
    db.session.commit()
    db.session.expire_all()
    reader = StrengthReader(user, now=now)
    assert reader.overview()["weekly"]["comparison"] == "0.00"
    summary = reader.summary(sessions[-1].public_id)
    assert summary["previous"]["sets"] == 9
    assert summary["today"]["volume"] == summary["previous"]["volume"]
    assert summary["candidates"]
    db.session.delete(sessions[-1].exercises[2])
    db.session.commit()
    db.session.expire_all()
    summary = StrengthReader(user, now=now).summary(sessions[-1].public_id)
    assert summary["previous"] is None
    assert summary["removed"] == ["QA Curl"]
    sessions[-1].exercises[0].sets[0].load_details_json = {"load_mode": "assistance", "original_unit": "kg"}
    db.session.commit()
    summary = StrengthReader(user, now=now).summary(sessions[-1].public_id)
    assert summary["today"]["partial"]
    assert summary["changes"][0]["change"] == "Sin sesión anterior comparable"

def test_summary_with_no_candidates(app, user):
    from app.services.gym_programs import publish_program_document
    plan, identities, sessions = strength_fixture(user, count=1)
    document = copy.deepcopy(get_active_version(plan, user).content)
    document["data"]["weeks"][0]["days"][0]["exercises"].pop()
    publish_program_document(document, user, plan_id=plan.public_id, base_revision=plan.revision)
    db.session.commit()
    summary = StrengthReader(user).summary(sessions[0].public_id)
    assert summary["previous"] is None
    assert summary["candidates"] == []

def test_week_boundaries_partial_and_consistency(app,user):
    now=datetime(2026,10,6,12,tzinfo=timezone.utc)
    account=db.session.get(User,user); account.timezone="America/Mexico_City"
    plan,identities,sessions=strength_fixture(user,now=now)
    sessions[-1].performed_at=datetime(2026,10,5,5,59,tzinfo=timezone.utc) # Sunday locally
    db.session.commit()
    model=StrengthReader(user,now=now).overview()
    assert model["weekly"]["sessions"] == 0 and model["weekly"]["comparison"] is None
    sessions[-1].performed_at=datetime(2026,10,5,6,tzinfo=timezone.utc) # Monday locally
    db.session.commit()
    reader=StrengthReader(user,now=now); model=reader.overview()
    assert model["weekly"]["sessions"] == 1 and model["weekly"]["sets"] == 15
    assert model["consistency_total"] == 4
    assert model["weekly"]["volume"] == "7560.00"
    sets=sessions[-1].exercises[0].sets
    sets[0].load_details_json={"load_mode":"assistance","original_unit":"kg"}
    db.session.commit()
    model=StrengthReader(user,now=now).overview()
    assert model["weekly"]["partial"] and model["weekly"]["comparison"] is None
    assert model["weekly"]["volume"] == "6920.00"

def test_same_set_top_and_estimate_chart_gap(app,user):
    plan,identities,sessions=strength_fixture(user)
    latest=sessions[-1].exercises[0].sets
    latest[0].weight_kg=100; latest[0].reps=1
    latest[1].weight_kg=80; latest[1].reps=10
    db.session.commit()
    detail=StrengthReader(user).detail(identities[0].public_id)
    assert detail["top_set"]["load"] == "100.00" and detail["top_set"]["reps"] == 1
    assert detail["estimate"] == "106.67"
    points=copy.deepcopy(detail["points"])
    points[1]["load"]=None
    assert len(chart_projection(points)["segments"]) == 2
    assert "None" not in str(chart_projection(points))

def test_all_views_share_evaluation_and_reads_never_publish(app,user):
    plan,identities,sessions=strength_fixture(user)
    reader=StrengthReader(user)
    home=reader.overview(); detail=reader.detail(identities[0].public_id); summary=reader.summary(sessions[-1].public_id)
    assert home["evaluations"][0] == detail["evaluation"] == summary["candidates"][0]
    assert {e["state"] for e in map(reader.evaluate, reader.contexts[:5])} == {"increase_load","increase_reps","maintain","insufficient_data","review"}
    assert db.session.query(TrainingPlanVersion).filter_by(user_id=user).count() == 1
    assert summary["previous"] is None # added fourth exercise breaks aggregate comparison
    assert summary["changes"][0]["change"] == "Sin cambios"
    assert reader.summary(sessions[0].public_id)["previous"] is None

def test_omitted_exercise_breaks_consecutive_evidence(app,user):
    plan,identities,sessions=strength_fixture(user)
    db.session.delete(sessions[-2].exercises[0]); db.session.commit()
    reader=StrengthReader(user)
    assert reader.evaluate(reader.context(plan.public_id,"1:1:1"))["state"] == "insufficient_data"

def test_confirm_new_revision_export_and_next_session(app,client,user):
    plan,identities,sessions=strength_fixture(user)
    original=copy.deepcopy(get_active_version(plan,user).content)
    original_id=sessions[0].training_plan_version_id
    prepared=preview(user,plan.public_id,"1:1:1")
    assert db.session.query(TrainingPlanVersion).count() == 1
    updated,duplicate=confirm(user,prepared["token"]); db.session.commit()
    assert not duplicate and updated.active_version_number == 2
    assert db.session.get(TrainingPlanVersion,original_id).content == original
    assert all(s.training_plan_version_id == original_id for s in sessions)
    version=get_active_version(plan,user)
    started=start_session(user,plan.public_id,version.public_id,1,1,str(uuid4())); db.session.commit()
    assert workout_context(started,user,"kg")["exercises"][0]["sets"][0]["target"]["load_value"] == "82.50"
    assert confirm(user,prepared["token"])[1]
    db.session.rollback()
    login(client)
    assert "82.50" in client.get(f"/gym/sessions/{started.public_id}").text

@pytest.mark.parametrize("variant",["tampered","expired","other_owner","changed_set","changed_revision","changed_rule","rollback"])
def test_confirmation_safety(app,user,monkeypatch,variant):
    plan,identities,sessions=strength_fixture(user)
    token=preview(user,plan.public_id,"1:1:1")["token"]
    owner=user
    if variant=="tampered": token=token[:-3]+"xyz"
    if variant=="expired": monkeypatch.setattr("app.services.gym_progression_confirm.TOKEN_TTL_SECONDS",-1)
    if variant=="other_owner":
        other=User(username="qa-other",role="user"); other.set_password("fictional-password")
        db.session.add(other); db.session.commit(); owner=other.id
    if variant=="changed_set": sessions[-1].exercises[0].sets[0].reps=6; db.session.commit()
    if variant=="changed_revision": plan.revision+=1; db.session.commit()
    if variant=="changed_rule":
        payload=_serializer().loads(token); payload["rule_version"]="obsolete"; token=_serializer().dumps(payload)
    if variant=="rollback":
        import app.services.gym_progression_confirm as service
        publisher=service.publish_program_document
        def failing(*args,**kwargs):
            publisher(*args,**kwargs)
            raise RuntimeError("QA rollback")
        monkeypatch.setattr(service,"publish_program_document",failing)
    with pytest.raises((GymError,RuntimeError)):
        confirm(owner,token)
    db.session.rollback()
    assert db.session.query(TrainingPlanVersion).filter_by(user_id=user).count()==1

def test_route_csrf_ownership_and_private_cache(app,client,user):
    plan,identities,sessions=strength_fixture(user)
    login(client)
    token=preview(user,plan.public_id,"1:1:1")["token"]
    app.config["WTF_CSRF_ENABLED"]=True
    assert client.post("/gym/progression/confirm",data={"token":token}).status_code==400
    for url in ["/training-plans",f"/gym/exercises/{identities[0].public_id}/progress",f"/gym/sessions/{sessions[-1].public_id}/summary"]:
        response=client.get(url)
        assert response.status_code==200 and "no-store" in response.headers["Cache-Control"]
    other=User(username="qa-isolated",role="user");other.set_password("fictional-password")
    db.session.add(other);db.session.commit()
    with pytest.raises(GymError): StrengthReader(other.id).detail(identities[0].public_id)
    with pytest.raises(GymError): StrengthReader(other.id).summary(sessions[-1].public_id)

def test_runtime_no_design_data():
    root=Path(__file__).resolve().parents[1]/"app/templates/gym"
    for name in ["programs.html","progress.html","completion.html","_strength.html","progression_preview.html"]:
        content=(root/name).read_text(encoding="utf-8")
        for marker in ["GymDesignFixtures","QA Press","datos ficticios","Ejemplo de diseño","fixture","mock","PROTOTIPO QA","prototype controls"]:
            assert marker not in content

def test_home_action_precedes_week_and_ai_reads_remain_read_only(app, client, user):
    from app.services.gym_capabilities import read_progression, read_program, read_session
    plan, identities, sessions = strength_fixture(user)
    login(client)
    page = client.get("/training-plans")
    assert page.text.index("Ver próxima sesión") < page.text.index('id="week-title"')
    before = db.session.query(TrainingPlanVersion).count()
    assert client.get("/ai").status_code == 200
    assert read_program(user, plan.public_id)["revision"] == 1
    assert read_session(user, sessions[-1].public_id)["status"] == "completed"
    evaluation = read_progression(user, plan.public_id, "1:1:1")
    assert evaluation["state"] == "increase_load"
    assert not {"provider", "model", "prompt", "api_key"}.intersection(evaluation)
    assert db.session.query(TrainingPlanVersion).count() == before
