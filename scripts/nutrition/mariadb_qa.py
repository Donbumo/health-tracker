"""Run only in the explicitly reserved, initially empty Nutrition QA schema.

Never creates a container, reads .env, drops a schema or accesses existing data.
The default credential is the repository's clearly fictional local QA account.
An unavailable schema is a blocked gate, never a passing/skipped result.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from pathlib import Path
from threading import Barrier
import json
import sys
import tempfile
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from sqlalchemy import inspect, text
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from flask_migrate import upgrade, downgrade, check
from app import create_app
from app.extensions import db
from app.models import User, DailyNutrition, Recipe, NutritionItem
from app.models.nutrition_intelligence import MealLog
from app.services import food_catalog as catalog, nutrition_intelligence as ni
from app.services.nutrition_math import NutritionError
from tests.test_nutrition_intelligence import food

URI = ('mysql+pymysql://progression_qa:fictional-progression-qa-password'
       '@127.0.0.1:33381/nutrition_intelligence_qa_20261009?charset=utf8mb4')
temporary = Path(tempfile.mkdtemp(prefix='ht-nutrition-mariadb-qa-'))


def application(level):
    return create_app({'TESTING': True, 'SECRET_KEY': 'fictional-nutrition-mariadb-qa-only-secret',
        'API_TOKEN_SIGNING_KEY': 'fictional-nutrition-mariadb-qa-api-key-only',
        'SQLALCHEMY_DATABASE_URI': URI, 'SQLALCHEMY_ENGINE_OPTIONS': {'isolation_level': level},
        'DATA_ROOT': temporary, 'UPLOAD_ROOT': temporary / 'raw',
        'GENERATED_UPLOAD_ROOT': temporary / 'generated', 'PORTABILITY_ROOT': temporary / 'portable',
        'SCHEMA_ROOT': ROOT / 'schemas', 'NUTRITION_INTELLIGENCE_ENABLED': True, 'AI_ENABLED': False})


def race(app, owner, actions):
    barrier = Barrier(len(actions))

    def run(action):
        with app.app_context():
            # Deliberately establish an old consistent read before the owner lock.
            # RR must still recalculate from current locking reads after waiting.
            db.session.execute(db.select(User.id).where(User.id == owner)).scalar_one()
            barrier.wait(timeout=20)
            try:
                value = action()
                db.session.commit()
                return {'ok': True, 'result': value}
            except NutritionError as error:
                db.session.rollback()
                return {'ok': False, 'status': error.status}
            finally:
                db.session.remove()
    with ThreadPoolExecutor(max_workers=len(actions)) as pool:
        return list(pool.map(run, actions))


def ready(owner, ref, target):
    row = ni.create_draft(owner, target=target, entries=[{'ref': ref, 'amount': '100', 'unit': 'g'}])
    return ni.mutate_draft(owner, row.public_id, row.revision, 'accept', {'index': 0})


def run():
    report = {'engine': 'MariaDB isolated reserved schema', 'data': 'fictional QA only', 'isolations': []}
    app = application('READ COMMITTED')
    with app.app_context():
        with db.engine.connect() as connection:
            assert connection.execute(text('SELECT DATABASE()')).scalar() == 'nutrition_intelligence_qa_20261009'
            if inspect(connection).get_table_names():
                # Explicit recovery of this runner's interrupted empty baseline.
                if '--resume-baseline' not in sys.argv:
                    raise RuntimeError('Reserved QA schema must be empty; existing tables are never replaced.')
                assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == '20260928_0043'
                assert all(name == 'QA legacy migration' for name in connection.execute(text('SELECT username FROM users')).scalars())
        upgrade(directory=str(ROOT / 'backend/migrations'), revision='20260928_0043')
        exists = db.session.execute(text("SELECT id FROM users WHERE username='QA legacy migration'")).scalar_one_or_none()
        if exists is None:
            db.session.execute(text("INSERT INTO users (username,password_hash,role,timezone,public_id) VALUES ('QA legacy migration','QA fictional hash only','user','UTC',:identity)"), {'identity': str(uuid4())})
        owner = db.session.execute(text("SELECT id FROM users WHERE username='QA legacy migration'")).scalar_one()
        if exists is None:
            db.session.execute(text("INSERT INTO daily_nutrition (user_id,date,source,calories) VALUES (:owner,'2026-10-01','qa',1234.567)"), {'owner': owner})
            db.session.execute(text("INSERT INTO recipes (user_id,name,servings,source) VALUES (:owner,'QA legacy migration recipe',1,'manual')"), {'owner': owner})
        db.session.commit()
        upgrade(directory=str(ROOT / 'backend/migrations'), revision='head')
        # Rollback is supported only before any new Nutrition consumption exists.
        downgrade(directory=str(ROOT / 'backend/migrations'), revision='20260928_0043')
        upgrade(directory=str(ROOT / 'backend/migrations'), revision='head')
        upgrade(directory=str(ROOT / 'backend/migrations'), revision='head')
        check(directory=str(ROOT / 'backend/migrations'))
        with db.engine.connect() as connection:
            assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == '20261009_0044'
            assert not compare_metadata(MigrationContext.configure(connection, opts={'compare_type': True}), db.metadata)
            assert connection.execute(text("SELECT calories FROM daily_nutrition WHERE user_id=:owner"), {'owner': owner}).scalar_one() == Decimal('1234.567')
            assert len(connection.execute(text('SELECT public_id FROM recipes WHERE user_id=:owner'), {'owner': owner}).scalar_one()) == 36
        report['migration'] = 'base to 0043, fictitious legacy records, 0044 to head; downgrade/upgrade before consumption; repeated upgrade; db check and metadata match'
        report['head'] = '20261009_0044'
        source = {'schema_version': '2.0', 'source': 'qa_fictional', 'revision': '1', 'license': 'QA synthetic', 'foods': [food()]}
        catalog.stage(source); catalog.activate('qa_fictional', '1', 1); db.session.commit()

    for index, level in enumerate(['READ COMMITTED', 'REPEATABLE READ']):
        app = application(level)
        with app.app_context():
            owner = User(username='QA nutrition ' + level, role='user', timezone='UTC')
            owner.set_password('QA fictional password only')
            db.session.add(owner); db.session.commit()
            user_id = owner.id
            ref = catalog.search(user_id)[0]['ref']
            target = f'2026-10-{20+index:02}'
            first = ready(user_id, ref, target); token = ni.confirmation_token(first)
            db.session.commit()
        result = race(app, user_id, [lambda: ni.confirm(user_id, token)[1], lambda: ni.confirm(user_id, token)[1]])
        assert all(r['ok'] for r in result) and sorted(r['result'] for r in result) == [False, True]
        with app.app_context():
            assert db.session.query(MealLog).filter_by(user_id=user_id).count() == 1
            assert db.session.query(NutritionItem).filter_by(user_id=user_id).count() == 1
            second, third = ready(user_id, ref, target), ready(user_id, ref, target)
            tokens = [ni.confirmation_token(second), ni.confirmation_token(third)]
            db.session.commit()
        result = race(app, user_id, [lambda t=t: ni.confirm(user_id, t)[1] for t in tokens])
        assert all(r['ok'] for r in result)
        with app.app_context():
            day = db.session.execute(db.select(DailyNutrition).where(DailyNutrition.user_id == user_id, DailyNutrition.date == date.fromisoformat(target))).scalar_one()
            assert day.calories == Decimal('495')
            assert Decimal(day.nutrition_summary_json['energy']['value']) == Decimal('495')
            draft = ready(user_id, ref, target)
            key, revision = draft.public_id, draft.revision
            db.session.commit()
        result = race(app, user_id, [lambda: ni.mutate_draft(user_id, key, revision, 'amount', {'index': 0, 'amount': '120', 'unit': 'g'}).revision,
                                     lambda: ni.mutate_draft(user_id, key, revision, 'amount', {'index': 0, 'amount': '130', 'unit': 'g'}).revision])
        assert sum(r['ok'] for r in result) == 1 and any(r.get('status') == 409 for r in result)
        with app.app_context():
            draft = ready(user_id, ref, target)
            recipe = ni.save_template(user_id, draft.public_id, draft.revision)
            recipe_key, recipe_revision = recipe.public_id, recipe.revision
            a = ni.template_draft(user_id, recipe_key, target); b = ni.template_draft(user_id, recipe_key, target)
            a = ni.mutate_draft(user_id, a.public_id, a.revision, 'amount', {'index': 0, 'amount': '140', 'unit': 'g'})
            b = ni.mutate_draft(user_id, b.public_id, b.revision, 'amount', {'index': 0, 'amount': '150', 'unit': 'g'})
            a = ni.mutate_draft(user_id, a.public_id, a.revision, 'accept', {'index': 0})
            b = ni.mutate_draft(user_id, b.public_id, b.revision, 'accept', {'index': 0})
            keys = [(a.public_id, a.revision), (b.public_id, b.revision)]; db.session.commit()
        result = race(app, user_id, [lambda k=k, r=r: ni.save_template(user_id, k, r, recipe_key=recipe_key, base_revision=recipe_revision).revision for k, r in keys])
        assert sum(r['ok'] for r in result) == 1 and any(r.get('status') == 409 for r in result)
        with app.app_context():
            draft = ready(user_id, ref, target); token = ni.confirmation_token(draft); db.session.commit()
            ni.confirm(user_id, token); db.session.rollback()
            assert db.session.query(MealLog).filter_by(user_id=user_id).count() == 3
        report['isolations'].append({'level': level, 'same_event': 'pass', 'distinct_events_current_totals': 'pass',
            'stale_draft': 'pass', 'stale_template': 'pass', 'caller_rollback': 'pass'})
    (ROOT / 'design/nutrition-intelligence-2/production-qa/mariadb-results.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    try:
        run()
    except Exception as error:
        # Do not print connection URLs, SQL parameters or payloads.
        print('MariaDB gate failed or blocked: ' + type(error).__name__, file=sys.stderr)
        import traceback
        for frame in traceback.extract_tb(error.__traceback__):
            if 'nutrition' in frame.filename:
                print(f'{Path(frame.filename).name}:{frame.lineno} in {frame.name}', file=sys.stderr)
        sys.exit(1)
