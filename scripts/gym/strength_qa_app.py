"""Explicit disposable MariaDB QA harness. Never opens .env or the ordinary stack.

Uses only the dedicated loopback database and synthetic test fixtures. Existing
public catalog files may be read from a pinned snapshot; nothing is downloaded.
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time
import shutil
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app import create_app
from app.extensions import db
from app.models import User, Exercise, TrainingPlan, TrainingSession, ExerciseCatalogSource, ExternalExercise
from app.services.exercise_catalog_source import FreeExerciseDBSource
from tests.gym_strength_fixtures import strength_fixture

URI = "mysql+pymysql://progression_qa:fictional-progression-qa-password@127.0.0.1:33381/gym_progression_qa?charset=utf8mb4"
REVISION = "f00c92c7dcf1216a928a52c3706c7ce8e2f71ed5"


def build_app(storage, catalog_root=None):
    storage = Path(storage).resolve()
    assert storage.is_relative_to(Path(tempfile.gettempdir()).resolve()) and storage.name.startswith("ht-strength-qa-")
    return create_app({"SECRET_KEY":"fictional-strength-qa-local-secret-only",
        "API_TOKEN_SIGNING_KEY":"fictional-strength-qa-local-api-signing-only",
        "SQLALCHEMY_DATABASE_URI":URI, "DATA_ROOT":storage,
        "UPLOAD_ROOT":storage/"uploads/raw", "GENERATED_UPLOAD_ROOT":storage/"uploads/generated",
        "PORTABILITY_ROOT":storage/"portability", "SCHEMA_ROOT":ROOT/"schemas",
        "EXERCISE_CATALOG_ROOT":storage/"catalog",
        "APP_TIMEZONE":"America/Mexico_City", "AI_ENABLED":False,
        "SESSION_COOKIE_SECURE":False, "WTF_CSRF_ENABLED":True})


def seed(app, catalog_root=None):
    from flask_migrate import upgrade, check
    with app.app_context():
        upgrade(directory=str(ROOT/"backend/migrations"))
        check(directory=str(ROOT/"backend/migrations"))
        user=db.session.execute(db.select(User).where(User.username=="strength-qa")).scalar_one_or_none()
        if user is None:
            user=User(username="strength-qa",role="user",timezone="America/Mexico_City",preferred_load_unit="kg")
            user.set_password("fictional-strength-qa-password")
            db.session.add(user);db.session.commit()
            plan,identities,sessions=strength_fixture(user.id)
        else:
            plan=db.session.execute(db.select(TrainingPlan).where(TrainingPlan.user_id==user.id,TrainingPlan.gym_active.is_(True))).scalar_one()
            identities=list(db.session.execute(db.select(Exercise).where(Exercise.user_id==user.id).order_by(Exercise.id)).scalars())
            sessions=list(db.session.execute(db.select(TrainingSession).where(TrainingSession.user_id==user.id).order_by(TrainingSession.performed_at)).scalars())
        if catalog_root:
            source=FreeExerciseDBSource()
            snapshot=Path(catalog_root).resolve()/source.source_id/REVISION
            assert snapshot.is_relative_to(Path(tempfile.gettempdir()).resolve())
            entries=source.validate((snapshot/"exercises.json").read_bytes())
            wanted=["Barbell_Bench_Press_-_Medium_Grip","Bent_Over_Barbell_Row","Barbell_Curl"]
            entries=[e for e in entries if e["id"] in wanted]
            qa_snapshot=Path(app.config["EXERCISE_CATALOG_ROOT"])/source.source_id/REVISION
            # Only copy the public, already committed design media into disposable QA.
            # The full old temp snapshot may have been pruned. No network fallback.
            assets=ROOT/"design/gym-progression-strength/assets"
            mapping={wanted[0]:["bench-0.jpg","bench-1.jpg"],wanted[1]:["row-0.jpg"],wanted[2]:["curl-0.jpg"]}
            for entry in entries:
                images=[]
                for position,name in enumerate(mapping[entry["id"]]):
                    relative=f'{entry["id"]}/{position}.jpg'
                    target=qa_snapshot/"exercises"/relative
                    target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(assets/name,target)
                    images.append(relative)
                entry["images"]=images
            media=source.media(qa_snapshot,entries)
            state=ExerciseCatalogSource(source_id=source.source_id,active_snapshot=REVISION,
                manifest={"source_name":source.source_name,"license":source.license,
                          "repository":source.repository,"commit_sha":REVISION})
            db.session.add(state);db.session.flush()
            by_id={}
            for values in source.normalize(entries):
                row=ExternalExercise(source=source.source_id,**values,media=media[values["external_id"]],available=True)
                db.session.add(row);by_id[row.external_id]=row
            db.session.flush()
            for identity,external_id in zip(identities,wanted):
                if external_id in by_id: identity.external_catalog_id=by_id[external_id].id
            db.session.commit()
        return {"program":plan.public_id,"exercise":identities[0].public_id,
                "summary":sessions[-1].public_id,"username":"strength-qa"}


def measure(app):
    from sqlalchemy import event
    from flask import g
    output=[]
    with app.app_context():
        for exercises,sessions in [(5,4),(40,4),(5,10),(5,200),(40,200)]:
            user=User(username="qa-perf-"+uuid4().hex,role="user",timezone="UTC")
            user.set_password("fictional-password");db.session.add(user);db.session.commit()
            owner=user.id
            plan,identities,records=strength_fixture(owner,count=sessions,exercise_count=exercises)
            urls={"home":"/training-plans", "detail":f"/gym/exercises/{identities[0].public_id}/progress",
                  "summary":f"/gym/sessions/{records[-1].public_id}/summary"}
            client=app.test_client()
            g.pop("_login_user", None)
            with client.session_transaction() as session:
                session["_user_id"]=str(owner);session["_fresh"]=True
            for name,url in urls.items():
                db.session.remove()
                counts=[]
                def count(*args): counts.append(1)
                engine=db.engine
                event.listen(engine,"before_cursor_execute",count)
                started=time.perf_counter()
                try: response=client.get(url)
                finally: event.remove(engine,"before_cursor_execute",count)
                assert response.status_code==200
                output.append({"page":name,"exercises":exercises,"sessions":sessions,
                               "queries":len(counts),"ms":round((time.perf_counter()-started)*1000,1)})
            db.session.execute(db.delete(User).where(User.id==owner));db.session.commit()
    return output


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("mode",choices=["seed","serve","measure"])
    parser.add_argument("--storage",required=True)
    parser.add_argument("--catalog-root")
    args=parser.parse_args()
    app=build_app(args.storage,args.catalog_root)
    if args.mode=="seed": print(json.dumps(seed(app,args.catalog_root)))
    if args.mode=="measure": print(json.dumps(measure(app),indent=2))
    if args.mode=="serve": app.run(host="127.0.0.1",port=8016,use_reloader=False)
