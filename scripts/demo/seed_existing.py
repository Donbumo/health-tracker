"""Run the reviewed generator once in an existing container, without deployment.

Password arrives exclusively through DEMO_USER_PASSWORD and process stdin.
Trusted source modules are loaded in the administrative process's memory only;
the running web workers, image, checkout, volumes and migrations stay in place.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
MODULES = ("demo_fixtures", "gym_sessions", "demo_seed")
DEPENDENCIES = ("nutrition_intelligence.py", "nutrition_math.py", "food_catalog.py", "energy_days.py", "gym_programs.py")

BOOTSTRAP = r'''
import hashlib, importlib.util, json, os, sys, types
from datetime import date
from pathlib import Path
from sqlalchemy import text
payload=json.load(sys.stdin)
os.environ['DEMO_USER_PASSWORD']=payload.pop('password')
from app import create_app
from app.extensions import db
from app.models import User, DailyEnergy, DailyNutrition, TrainingSession, TrainingSet
app=create_app()
app.config.update(DEMO_SEED_ENABLED=True, DEMO_SEED_ENVIRONMENT=payload['environment'])
try:
    with app.app_context():
        assert db.session.scalar(text('SELECT version_num FROM alembic_version'))=='20261018_0046', 'schema_not_ready'
        assert app.config.get('NUTRITION_INTELLIGENCE_ENABLED') is True, 'nutrition_not_enabled'
        for name,digest in payload['dependencies'].items():
            assert hashlib.sha256((Path('/app/app/services')/name).read_text().encode()).hexdigest()==digest, 'domain_code_mismatch'
        baseline_owners=db.session.scalars(db.select(User.id)).all()
        # Compare entirely on the server. No row values or hashes leave this process.
        def unchanged_state():
            result={}
            for table in db.metadata.sorted_tables:
                if table.name=='users':query=table.select().where(table.c.id.in_(baseline_owners))
                elif 'user_id' in table.c:query=table.select().where(table.c.user_id.in_(baseline_owners))
                else:continue
                digest=hashlib.sha256()
                for row in db.session.execute(query.order_by(*table.primary_key.columns)):
                    digest.update(json.dumps(list(row),default=str,sort_keys=True).encode())
                result[table.name]=digest.digest()
            return result
        import app.services
        for name,source in payload['modules'].items():
            full='app.services.'+name
            module=types.ModuleType(full)
            module.__file__='<reviewed-demo-generator>/'+name+'.py'
            sys.modules[full]=module
            setattr(app.services,name,module)
            exec(compile(source,module.__file__,'exec'),module.__dict__)
        from app.services.demo_seed import seed_demo_data,DEMO_PUBLIC_ID
        existing=db.session.scalar(db.select(User).where(User.public_id==DEMO_PUBLIC_ID))
        if existing:baseline_owners.remove(existing.id)
        baseline=unchanged_state()
        reference=date.fromisoformat(payload['as_of']) if payload['as_of'] else None
        account,created=seed_demo_data(as_of=reference,confirmed=True,production=payload['environment']=='production')
        assert baseline==unchanged_state(), 'non_demo_integrity_changed'
        _,replay=seed_demo_data(as_of=reference,confirmed=True,production=payload['environment']=='production')
        assert not any(replay.values()), 'replay_created_rows'
        assert baseline==unchanged_state(), 'non_demo_integrity_changed'
        counts={model.__tablename__:db.session.scalar(db.select(db.func.count()).select_from(model).where(model.user_id==account.id))
                for model in (DailyEnergy,DailyNutrition,TrainingSession,TrainingSet)}
        print(json.dumps({'created':created,'counts':counts,'replay_created':sum(replay.values()),'non_demo_unchanged':True,
                          'email':account.email,'first_day':db.session.scalar(db.select(db.func.min(DailyNutrition.date)).where(DailyNutrition.user_id==account.id)).isoformat(),
                          'last_day':db.session.scalar(db.select(db.func.max(DailyNutrition.date)).where(DailyNutrition.user_id==account.id)).isoformat()}))
except Exception as error:
    db.session.rollback()
    # Never print SQL, parameters, credentials, payloads or exception messages.
    print(json.dumps({'error_type':type(error).__name__,'result':'seed_or_verification_failed'}))
    sys.exit(1)
finally:
    os.environ.pop('DEMO_USER_PASSWORD',None)
'''


def make_payload(as_of, production):
    password = os.environ.get("DEMO_USER_PASSWORD", "")
    if len(password) < 12:
        raise ValueError("Set DEMO_USER_PASSWORD with at least 12 characters.")
    services = ROOT / "backend/app/services"
    return {"as_of": as_of, "environment": "production" if production else "local", "password": password,
            "modules": {name: (services / (name + ".py")).read_text(encoding="utf-8") for name in MODULES},
            "dependencies": {name: hashlib.sha256((services / name).read_text(encoding="utf-8").encode()).hexdigest() for name in DEPENDENCIES}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", help="Reference date; defaults to the application's local today.")
    parser.add_argument("--container", default="health-tracker-web-1")
    parser.add_argument("--ssh-host")
    parser.add_argument("--ssh-user")
    parser.add_argument("--ssh-port", type=int, default=22)
    parser.add_argument("--confirm-local", action="store_true")
    parser.add_argument("--confirm-production", action="store_true")
    args = parser.parse_args()
    if args.confirm_local == args.confirm_production:
        parser.error("Select exactly one explicit environment confirmation.")
    if args.ssh_host and not args.confirm_production:
        parser.error("Remote execution requires --confirm-production and prior authorization.")
    payload = json.dumps(make_payload(args.as_of, args.confirm_production))
    command = ["docker", "exec", "-i", args.container, "python", "-c", BOOTSTRAP]
    if args.ssh_host:
        if not args.ssh_user:
            parser.error("--ssh-user is required.")
        # The remote command is constant Python, receiving JSON via SSH stdin.
        import shlex
        remote = "PATH=/usr/local/bin:$PATH " + shlex.join(command)
        command = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=yes",
                   "-p", str(args.ssh_port), args.ssh_user + "@" + args.ssh_host, remote]
    result = subprocess.run(command, input=payload, capture_output=True, text=True, encoding="utf-8")
    # Bootstrap emits aggregate metadata only; keep third-party stderr private.
    if result.stdout.strip().startswith('{'):
        print(result.stdout.strip())
    if result.returncode:
        print("DEMO operation failed; no credentials or raw diagnostics displayed.", file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
