"""0046 migrates synthetic duplicates without removing source identities."""
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa


def test_0046_additive_reconciliation_preserves_every_original_column(tmp_path):
    path = Path(__file__).parents[1] / 'migrations/versions/20261018_0046_canonical_energy_days.py'
    spec = importlib.util.spec_from_file_location('energy_0046', path)
    migration = importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    engine = sa.create_engine('sqlite:///' + str(tmp_path / 'qa-energy.db'))
    meta = sa.MetaData()
    users = sa.Table('users', meta, sa.Column('id',sa.Integer,primary_key=True))
    uploads = sa.Table('uploaded_files', meta, sa.Column('id',sa.Integer,primary_key=True),sa.Column('user_id',sa.Integer),sa.Column('sha256',sa.String(64)))
    energy = sa.Table('daily_energy', meta, sa.Column('id',sa.Integer,primary_key=True),sa.Column('user_id',sa.Integer),
        sa.Column('date',sa.Date),sa.Column('source',sa.String(32)),sa.Column('public_id',sa.String(36)),sa.Column('revision',sa.Integer),
        sa.Column('source_file_id',sa.Integer),sa.Column('raw_payload_json',sa.JSON),sa.Column('total_calories',sa.Numeric(10,2)),sa.Column('steps',sa.BigInteger),
        sa.UniqueConstraint('user_id','date','source',name='uq_daily_energy_user_date_source'))
    meta.create_all(engine)
    from datetime import date
    import uuid
    with engine.begin() as connection:
        connection.execute(users.insert(),[{'id':1},{'id':2}])
        connection.execute(uploads.insert(),[{'id':1,'user_id':1,'sha256':'a'*64}])
        connection.execute(energy.insert(),[
            {'id':1,'user_id':1,'date':date(2040,1,1),'source':'qa_steps','public_id':str(uuid.uuid4()),'revision':4,'source_file_id':1,'raw_payload_json':{'fixture':'QA partial'},'total_calories':None,'steps':1200},
            {'id':2,'user_id':1,'date':date(2040,1,1),'source':'qa_full','public_id':str(uuid.uuid4()),'revision':7,'source_file_id':None,'raw_payload_json':{'fixture':'QA full'},'total_calories':2400,'steps':1200},
            {'id':3,'user_id':2,'date':date(2040,1,1),'source':'qa_other','public_id':str(uuid.uuid4()),'revision':2,'source_file_id':None,'raw_payload_json':{'fixture':'QA other owner'},'total_calories':2300,'steps':0}])
        before = connection.execute(sa.select(energy).order_by(energy.c.id)).all()
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert connection.execute(sa.select(energy).order_by(energy.c.id)).all() == before
        assert connection.scalar(sa.text('SELECT COUNT(*) FROM energy_days')) == 2
        assert connection.scalar(sa.text('SELECT source_file_sha256 FROM daily_energy WHERE id=1')) == 'a'*64
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(sa.text("INSERT INTO energy_days (user_id,date,revision) VALUES (1,'2040-01-01',1)"))
        with pytest.raises(RuntimeError, match='never destructive downgrade'):
            migration.downgrade()
