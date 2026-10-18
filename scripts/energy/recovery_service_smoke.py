"""Read-only HTTP smoke on restored LOCAL QA; no host port, NAS or real account."""
from datetime import date
import hashlib
import html
import http.cookiejar
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request

from sqlalchemy import text
from app import create_app
from app.extensions import db
from app.models import User, DailyEnergy, EnergyDay, EnergyEvidenceEvent
from app.models.nutrition_intelligence import MealLog
from app.services import energy_days

app = create_app()
with app.app_context():
    assert db.engine.url.host == 'db'
    assert db.session.scalar(text('SELECT DATABASE()')) == 'energy18_recovery_qa_20261018_c'
    assert db.session.scalar(text('SELECT version_num FROM alembic_version')) == '20261018_0046'
    owner = db.session.scalar(db.select(User).where(User.username.like('QA-recovery-baseline-%')))
    assert owner is not None
    username, uid = owner.username, owner.id
    canonical = energy_days.view(uid, date(2040, 2, 3))
    assert canonical.total_calories is None and canonical.steps == 1200
    log = db.session.scalar(db.select(MealLog).where(MealLog.user_id == uid))
    assert log.snapshot_json['summary']['energy']['value'] == '297.0'
    before = hashlib.sha256(json.dumps(log.snapshot_json, sort_keys=True).encode()).hexdigest()

base = 'http://127.0.0.1:8000'
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
assert json.loads(opener.open(base + '/healthz').read())['status'] == 'ok'
page = opener.open(base + '/login').read().decode()
csrf = html.unescape(re.search(r'name="csrf_token"[^>]*value="([^"]*)"', page)[1])
opener.open(base + '/login', urllib.parse.urlencode({'username': username, 'password': 'fictional-QA-only', 'csrf_token': csrf}).encode()).read()
for path in ['/daily-energy', f'/daily-energy/{canonical.id}', '/nutrition/?date=2040-02-03', '/nutrition/micronutrients?date=2040-02-03', '/nutrition/saved']:
    response = opener.open(base + path)
    assert response.status == 200 and '/login' not in response.url

with app.app_context():
    log = db.session.scalar(db.select(MealLog).where(MealLog.user_id == uid))
    assert hashlib.sha256(json.dumps(log.snapshot_json, sort_keys=True).encode()).hexdigest() == before
    assert energy_days.view(uid, date(2040, 2, 3)).total_calories is None
    assert db.session.query(EnergyEvidenceEvent).count() > 0
    assert db.session.query(DailyEnergy).filter(DailyEnergy.deleted_at.is_not(None)).count() > 0
Path('/evidence/recovery-service-http.json').write_text(json.dumps({'head': '20261018_0046', 'http': 'Gunicorn real; loopback only',
    'healthz_login_csrf': 'PASS', 'energy_history_conflict_steps': 'PASS', 'nutrition_21_dashboard_micros_saved': 'PASS',
    'historical_snapshot': 'identical', 'new_events_and_tombstones': 'retained'}, indent=2), encoding='utf-8')
print('recovery service HTTP PASS')
