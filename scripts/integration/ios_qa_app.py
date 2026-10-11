"""Disposable loopback backend for iOS CI; all identities and fixtures are fictitious."""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(os.environ['HT_QA_CHECKOUT']).resolve()
sys.path.insert(0, str(ROOT / 'backend'))
from app import create_app
from app.extensions import db
from app.models import Exercise, User
from tests.test_mobile_sync import _api_login, _completed_payload

temporary = Path(tempfile.mkdtemp(prefix='ht-ios-integration-qa-'))
app = create_app({
    'TESTING': True,
    'SECRET_KEY': 'fictional-ios-ci-session-secret-at-least-32-chars',
    'API_TOKEN_SIGNING_KEY': 'fictional-ios-ci-api-secret-at-least-32-chars',
    'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + (temporary / 'qa.sqlite').as_posix(),
    'SQLALCHEMY_ENGINE_OPTIONS': {},
    'DATA_ROOT': temporary, 'UPLOAD_ROOT': temporary / 'raw',
    'GENERATED_UPLOAD_ROOT': temporary / 'generated', 'PORTABILITY_ROOT': temporary / 'portability',
    'SCHEMA_ROOT': ROOT / 'schemas', 'APP_TIMEZONE': 'UTC',
    'NUTRITION_INTELLIGENCE_ENABLED': True, 'AI_ENABLED': False,
    'API_RATE_LIMIT_ENABLED': False,
})
with app.app_context():
    db.create_all()
    user = User(username='ios-ci-qa', role='user', timezone='UTC')
    user.set_password('fictional-ios-ci-qa-password')
    db.session.add(user)
    db.session.flush()
    db.session.add(Exercise(user_id=user.id, canonical_name='Sentadilla QA', normalized_name='sentadilla qa'))
    db.session.commit()

client = app.test_client()
token = _api_login(client, username='ios-ci-qa', password='fictional-ios-ci-qa-password')['access_token']
auth = {'Authorization': 'Bearer ' + token}

def post(path, payload):
    response = client.post(path, json=payload, headers={**auth, 'Idempotency-Key': str(uuid4())})
    assert response.status_code in (200, 201), f"QA seed failed: status={response.status_code} code={response.get_json().get('error', {}).get('code')} message={response.get_json().get('error', {}).get('message')}"
    return response.get_json()['data']

plan = post('/api/v1/mobile/plans', {'public_id': str(uuid4()), 'name': 'Rutina CI QA'})
workout = post('/api/v1/mobile/plans/' + plan['public_id'] + '/workouts', {
    'public_id': str(uuid4()), 'base_revision': plan['revision'], 'name': 'Fuerza CI QA',
    'exercises': [{'id': str(uuid4()), 'name': 'Sentadilla QA', 'sets': [{
        'id': str(uuid4()), 'reps': 8, 'weight_kg': '40', 'load_value': '40',
        'load_unit': 'kg', 'load_mode': 'direct_total', 'rest_seconds': 30,
    }]}],
})
now = datetime.now(timezone.utc)
for days in (2, 1, 0):
    moment = now - timedelta(days=days)
    planned = post('/api/v1/mobile/workouts/' + workout['public_id'] + '/schedule', {
        'public_id': str(uuid4()), 'scheduled_for_date': moment.date().isoformat(), 'timezone': 'UTC',
    })
    if days:
        payload = _completed_payload(planned['public_id'])
        payload.update(started_at=moment.isoformat(), completed_at=(moment + timedelta(minutes=45)).isoformat(),
                       client_updated_at=(moment + timedelta(minutes=46)).isoformat(), timezone='UTC')
        payload['exercises'][0]['name'] = 'Sentadilla QA'
        payload['exercises'][0]['sets'] = payload['exercises'][0]['sets'][:1]
        post('/api/v1/completed-workouts', payload)

print('Synthetic iOS CI backend ready on loopback:8026', flush=True)
app.run(host='127.0.0.1', port=8026, debug=False, use_reloader=False)
