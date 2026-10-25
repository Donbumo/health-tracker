"""Real Flask visual QA: temporary SQLite/storage, synthetic accounts only.

No NAS, persistent stack, personal credentials, production flags or domain POSTs.
Run from the repository root with .venv/Scripts/python.exe.
"""
import json
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

from werkzeug.serving import make_server

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from app import create_app
from app.extensions import db
from app.models import DailyNutrition, User
from app.services import energy_days
from tests.test_energy_days import document

storage = Path(tempfile.mkdtemp(prefix='QA-unified-health-'))
app = create_app({
    'TESTING': True, 'TEMPLATES_AUTO_RELOAD': True,
    'SECRET_KEY': 'fictional-unified-QA-session-signing-only',
    'API_TOKEN_SIGNING_KEY': 'fictional-unified-QA-api-signing-only',
    'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + (storage / 'qa.sqlite').as_posix(),
    'SQLALCHEMY_ENGINE_OPTIONS': {}, 'DATA_ROOT': storage,
    'UPLOAD_ROOT': storage / 'uploads/raw', 'GENERATED_UPLOAD_ROOT': storage / 'uploads/generated',
    'PORTABILITY_ROOT': storage / 'portability', 'SCHEMA_ROOT': ROOT / 'schemas',
    'APP_TIMEZONE': 'UTC', 'WTF_CSRF_ENABLED': False,
    'NUTRITION_INTELLIGENCE_ENABLED': True, 'NUTRITION_EXTERNAL_LOOKUP_ENABLED': False,
    'AI_ENABLED': False, 'API_RATE_LIMIT_ENABLED': False,
})


def seed():
    with app.app_context():
        db.create_all()
        owner = User(username='QA-unified-health', display_name='QA ficticia · Resumen',
                     role='user', timezone='America/Mexico_City')
        owner.set_password('fictional-unified-QA-password')
        db.session.add(owner); db.session.flush()
        target = date(2040, 2, 5)
        for ago in range(96):
            day = target - timedelta(days=ago)
            intake, expense, partial = 2200 + ago % 5 * 50, 2500 + ago % 7 * 30, False
            if ago < 7:
                intake, expense, partial = [(2280,2660,False),(2160,None,False),(2340,2610,False),
                    (None,None,False),(1450,2420,True),(2700,2490,False),(2180,2580,False)][ago]
            if intake is not None:
                db.session.add(DailyNutrition(user_id=owner.id, date=day, source='QA Nutrition', calories=intake,
                    nutrition_summary_json={'energy': {'state':'partial','value':str(intake)}} if partial else None))
            if expense is not None:
                energy_days.upsert_document(document(owner.id, 'QA gasto', day=day,
                    total_expenditure_kcal=expense), owner.id)
            if ago == 1:
                for label, value in [('QA fuente A',2500),('QA fuente B',2900)]:
                    energy_days.upsert_document(document(owner.id,label,day=day,total_expenditure_kcal=value),owner.id)
        zero = target + timedelta(days=1)
        db.session.add(DailyNutrition(user_id=owner.id,date=zero,source='QA cero',calories=0))
        energy_days.upsert_document(document(owner.id,'QA cero',day=zero,total_expenditure_kcal=0),owner.id)
        db.session.commit()


if __name__ == '__main__':
    seed()
    server = make_server('127.0.0.1', 0, app)
    print(json.dumps({'scope':'synthetic unified health QA', 'pid':os.getpid(),
                      'url':f'http://127.0.0.1:{server.server_port}'}), flush=True)
    server.serve_forever()
