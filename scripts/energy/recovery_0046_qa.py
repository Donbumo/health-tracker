"""LOCAL disposable QA only. No downgrade, stamp, table removal or main DB access.

Run phases with recovery_0046_qa.ps1; SQL dumps and files stay outside Git.
The interrupted database is retained. Recovery uses a verified fresh clone,
then the unmodified migration, never an in-place replay of partial DDL.
"""
import argparse
import hashlib
import json
from pathlib import Path
import uuid

from sqlalchemy import inspect, text
from flask_migrate import upgrade, check

from app import create_app
from app.extensions import db

PREFIX = 'energy18_recovery_qa_20261018_'
BASE = '20261013_0045'
HEAD = '20261018_0046'
parser = argparse.ArgumentParser()
parser.add_argument('phase', choices=['baseline', 'verify-baseline', 'interrupt', 'upgrade', 'roundtrip', 'postwrite', 'verify-post', 'freeze'])
parser.add_argument('--schema', required=True, choices=[PREFIX + suffix for suffix in 'abc'])
args = parser.parse_args()
out = Path('/evidence')


def application(level='READ COMMITTED'):
    app = create_app({'TESTING': True, 'NUTRITION_INTELLIGENCE_ENABLED': True,
                      'NUTRITION_EXTERNAL_LOOKUP_ENABLED': False,
                      'SQLALCHEMY_ENGINE_OPTIONS': {'isolation_level': level, 'pool_pre_ping': True}})
    with app.app_context():
        assert db.engine.url.host == 'db' and db.engine.url.database == args.schema
        assert db.session.scalar(text('SELECT DATABASE()')) == args.schema
        assert db.session.scalar(text('SELECT CURRENT_USER()')).startswith('progression_qa@')
    return app


def head():
    return db.session.scalar(text('SELECT version_num FROM alembic_version'))


def snapshot(columns=None):
    metadata = inspect(db.engine)
    columns = columns or {table: [col['name'] for col in metadata.get_columns(table)]
                          for table in metadata.get_table_names() if table != 'alembic_version'}
    hashes = {}
    counts = {}
    for table, cols in columns.items():
        # Identifiers are inspected metadata or our own previous QA manifest.
        assert table in metadata.get_table_names()
        assert all(col in {c['name'] for c in metadata.get_columns(table)} for col in cols)
        rows = [list(row) for row in db.session.execute(text('SELECT ' + ','.join('`' + col + '`' for col in cols) + ' FROM `' + table + '`'))]
        encoded = sorted(json.dumps(row, default=str, ensure_ascii=True) for row in rows)
        hashes[table] = hashlib.sha256(json.dumps(encoded).encode()).hexdigest()
        counts[table] = len(rows)
    return {'columns': columns, 'hashes': hashes, 'counts': counts}


def write(name, value):
    (out / name).write_text(json.dumps(value, indent=2), encoding='utf-8')


app = application()
with app.app_context():
    if args.phase == 'baseline':
        assert args.schema.endswith('_a') and head() == BASE
        from app.models import User
        from app.services import food_catalog as catalog, nutrition_intelligence as ni
        from app.services.files import store_uploaded_file
        from tests.test_nutrition_intelligence import food, ready
        from werkzeug.datastructures import FileStorage
        import io
        row = User(username='QA-recovery-baseline-' + uuid.uuid4().hex, role='user')
        row.set_password('fictional-QA-only'); db.session.add(row); db.session.commit()
        catalog.stage({'schema_version': '2.0', 'source': 'qa_fictional', 'revision': '1', 'license': 'QA synthetic', 'foods': [food()]})
        catalog.activate('qa_fictional', '1', 1); db.session.commit()
        ref = catalog.search(row.id)[0]['ref']
        draft = ready(row.id, ref, '2040-02-03')
        ni.save_template(row.id, draft.public_id, draft.revision)
        ni.confirm(row.id, ni.confirmation_token(draft)); db.session.commit()
        for source, steps, total in [('qa_steps', 1200, None), ('qa_energy', None, 2400), ('qa_conflict', None, 2500)]:
            payload = {'schema_version': '1.0', 'record_type': 'daily_energy', 'user_id': row.id, 'source_type': 'uploaded',
                       'data': {'date': '2040-02-03', 'source': source, 'steps': steps, 'total_expenditure_kcal': total}}
            raw = json.dumps(payload).encode()
            upload, _ = store_uploaded_file(FileStorage(stream=io.BytesIO(raw), filename='QA-' + source + '.json'), row.id)
            db.session.execute(text('INSERT INTO daily_energy (public_id,user_id,date,source,steps,total_calories,revision,client_event_id,source_file_id,raw_payload_json) VALUES (:pid,:uid,:day,:source,:steps,:total,3,:event,:file,:payload)'),
                               {'pid': str(uuid.uuid4()), 'uid': row.id, 'day': '2040-02-03', 'source': source, 'steps': steps, 'total': total,
                                'event': str(uuid.uuid4()), 'file': upload.id, 'payload': json.dumps(payload)})
        db.session.commit()
        engines = db.session.execute(text('SELECT DISTINCT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()')).scalars().all()
        assert engines == ['InnoDB'], engines
        write('recovery-baseline-private.json', snapshot())
    elif args.phase == 'verify-baseline':
        assert args.schema.endswith('_b') and head() == BASE
        baseline = json.loads((out / 'recovery-baseline-private.json').read_text())
        assert snapshot(baseline['columns']) == baseline
        write('recovery-clone-0045.json', {'head': BASE, 'all_tables_and_original_columns_identical': True})
    elif args.phase == 'interrupt':
        assert args.schema.endswith('_a') and head() == BASE
        import alembic.op as op
        original = op.create_table
        injected = []

        def interrupted(name, *columns, **kwargs):
            result = original(name, *columns, **kwargs)
            if name == 'energy_days':
                injected.append(True)
                raise RuntimeError('QA_INJECTED_AFTER_NONTRANSACTIONAL_DDL')
            return result

        # Never retry a partial DDL. On a second diagnostic invocation, inspect
        # the retained failed schema without executing migration operations.
        if 'energy_days' not in inspect(db.engine).get_table_names():
            op.create_table = interrupted
            db.session.rollback()
            try:
                upgrade(directory='/app/migrations')
                raise AssertionError('Failure injection did not run')
            except (RuntimeError, SystemExit):
                # Flask-Migrate translates RuntimeError into SystemExit(1).
                assert injected
            finally:
                op.create_table = original
                db.session.remove()
        assert head() == BASE
        metadata = inspect(db.engine)
        assert 'energy_days' in metadata.get_table_names()
        assert 'energy_evidence_events' not in metadata.get_table_names()
        assert {'deleted_at', 'source_file_sha256'} <= {col['name'] for col in metadata.get_columns('daily_energy')}
        baseline = json.loads((out / 'recovery-baseline-private.json').read_text())
        assert snapshot(baseline['columns']) == baseline
        write('recovery-interrupted.json', {'head': BASE, 'partial_ddl_committed': True, 'original_columns_identical': True,
                                          'action': 'retained failed schema; recover into preverified isolated clone; no blind retry'})
    elif args.phase == 'upgrade':
        assert args.schema.endswith('_b') and head() == BASE
        db.session.rollback(); upgrade(directory='/app/migrations')
        assert head() == HEAD
        baseline = json.loads((out / 'recovery-baseline-private.json').read_text())
        assert snapshot(baseline['columns']) == baseline
        db.session.rollback(); check(directory='/app/migrations')
        db.session.rollback(); upgrade(directory='/app/migrations')
        from app.services.energy_days import views
        from app.models import User, DailyEnergy
        uid = db.session.scalar(db.select(User.id))
        assert len(views(uid)) == 1 and views(uid)[0].total_calories is None
        assert views(uid)[0].steps == 1200
        assert db.session.query(DailyEnergy).filter_by(user_id=uid).count() == 3
        write('recovery-upgrade.json', {'from': BASE, 'to': HEAD, 'db_check': 'PASS', 'repeat_upgrade': 'no-op PASS',
                                     'all_original_columns_catalog_nutrition_snapshots': 'identical', 'canonical_days': 1, 'sources': 3})
    elif args.phase == 'postwrite':
        assert args.schema.endswith('_b') and head() == HEAD
        from tests.test_energy_account_roundtrip import make_owner, seed_account
        seed_account(make_owner())
        write('recovery-postwrite-private.json', snapshot())
    elif args.phase == 'verify-post':
        assert args.schema.endswith('_c') and head() == HEAD
        expected = json.loads((out / 'recovery-postwrite-private.json').read_text())
        assert snapshot(expected['columns']) == expected
        from app.models import DailyEnergy, EnergyDay, EnergyEvidenceEvent, UploadedFile
        for model in [DailyEnergy, EnergyEvidenceEvent]:
            for row in db.session.scalars(db.select(model)):
                if row.source_file_id is not None:
                    upload = db.session.get(UploadedFile, row.source_file_id)
                    assert upload.user_id == row.user_id and upload.sha256 == row.source_file_sha256
        for row in db.session.scalars(db.select(UploadedFile)):
            content = (Path(app.config['DATA_ROOT']) / row.storage_path).read_bytes()
            assert hashlib.sha256(content).hexdigest() == row.sha256
        db.session.rollback(); check(directory='/app/migrations')
        client = app.test_client()
        assert client.get('/healthz').status_code == 200
        assert db.session.query(EnergyEvidenceEvent).count() > 0
        assert db.session.query(DailyEnergy).filter(DailyEnergy.deleted_at.is_not(None)).count() > 0
        write('recovery-postwrite.json', {'head': HEAD, 'all_tables_identical': True, 'original_bytes_and_hashes': 'PASS',
                                        'events_revisions_tombstones_uuids_nutrition_snapshots_catalog': 'identical',
                                        'db_check': 'PASS', 'flask_healthz': 'PASS'})
    elif args.phase == 'freeze':
        assert args.schema.endswith('_b') and head() == HEAD
        from sqlalchemy.exc import DBAPIError
        try:
            db.session.execute(text('UPDATE energy_days SET revision=revision WHERE id=1'))
            raise AssertionError('Frozen QA writer unexpectedly authorized')
        except DBAPIError as error:
            assert error.orig.args[0] == 1142
            db.session.rollback()
        write('recovery-freeze.json', {'write_attempt': 'denied 1142', 'reads': 'available', 'scope': 'isolated QA schema only'})
    elif args.phase == 'roundtrip':
        assert args.schema.endswith(('_b', '_c')) and head() == HEAD

if args.phase == 'roundtrip':
    from tests.test_energy_account_roundtrip import make_owner, test_complete_energy_account_roundtrip, test_legacy_10_account_restore_remains_conservative
    results = {}
    for level in ['READ COMMITTED', 'REPEATABLE READ']:
        app = application(level)
        with app.app_context():
            assert db.session.scalar(text('SELECT @@tx_isolation')).replace('-', ' ') == level
            for mode in ['json', 'zip']:
                test_complete_energy_account_roundtrip(app, make_owner(), mode)
            test_legacy_10_account_restore_remains_conservative(app, make_owner())
            results[level] = {'JSON_1_1_full_account': 'PASS', 'ZIP_originals': 'PASS', 'second_restore': 'PASS',
                              'stale_review_and_delete': 'blocked PASS', 'JSON_1_0': 'PASS',
                              'mobile_uuid_events_revisions': 'PASS', 'owner_only': 'PASS', 'balance_trends_no_double_count': 'PASS'}
    write('control1-mariadb.json', results)
print(args.phase + ' PASS')
