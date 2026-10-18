"""0045 full-schema fixture -> 0046 in an ephemeral SQLite file only.

The unrelated historical 0015 FK ALTER cannot bootstrap SQLite from empty.
The focused test separately migrates duplicates across two fictional owners.
"""
import json
from pathlib import Path
import sys
import tempfile
from datetime import date
import uuid

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
from app import create_app
from app.extensions import db
from app.models import User
from flask_migrate import upgrade,check,stamp
from sqlalchemy import MetaData,text

storage=Path(tempfile.mkdtemp(prefix='QA-energy18-sqlite45-'))
app=create_app({'TESTING':True,'SQLALCHEMY_DATABASE_URI':'sqlite:///'+(storage/'qa.sqlite').as_posix(),
    'SQLALCHEMY_ENGINE_OPTIONS':{},'DATA_ROOT':storage,'SCHEMA_ROOT':ROOT/'schemas',
    'SECRET_KEY':'fictional-energy18-migration-key-only'})
with app.app_context():
    baseline=MetaData()
    for table in db.metadata.sorted_tables:
        if table.name not in {'energy_days','energy_evidence_events'}:
            table.to_metadata(baseline)
    original=baseline.tables['daily_energy']
    for name in ['deleted_at','source_file_sha256']:
        original._columns.remove(original.c[name])
    baseline.create_all(db.engine)
    owner=User(username='QA-sqlite45-duplicates',role='user');owner.set_password('fictional')
    db.session.add(owner);db.session.commit()
    with db.engine.begin() as connection:
        connection.execute(original.insert(),[{'user_id':owner.id,'date':date(2040,1,1),'source':source,
            'public_id':str(uuid.uuid4()),'steps':1200,'revision':1} for source in ['qa_a','qa_b']])
    migrations=str(ROOT/'backend/migrations')
    stamp(directory=migrations,revision='20261013_0045')
    upgrade(directory=migrations)
    assert db.session.scalar(text('SELECT version_num FROM alembic_version'))=='20261018_0046'
    assert db.session.scalar(text('SELECT COUNT(*) FROM daily_energy'))==2
    assert db.session.scalar(text('SELECT COUNT(*) FROM energy_days'))==1
    check(directory=migrations)
    db.session.rollback();upgrade(directory=migrations)
    print(json.dumps({'scope':'ephemeral SQLite QA','baseline':'0045 schema fixture','head':'20261018_0046',
        'source_rows':2,'canonical_days':1,'db_check':'pass','repeated_upgrade':'safe no-op'}))
