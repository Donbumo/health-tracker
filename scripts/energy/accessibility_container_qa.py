"""Offline Linux regression and LOCAL MariaDB D gates; no production targets."""
from pathlib import Path
from datetime import date
import json,subprocess,sys,tempfile,uuid

venv=Path('/tmp/energy-D-venv')
python=str(venv/'bin/python')
if '--ready' not in sys.argv:
    subprocess.run([sys.executable,'-m','venv','--system-site-packages',str(venv)],check=True)
    subprocess.run([python,'-m','pip','install','--no-index','--find-links','/qa-wheels','pytest'],check=True)
    subprocess.run([python,__file__,'--ready'],check=True)
    sys.exit(0)
subprocess.run([python,'-m','pytest','-q','--tb=short','-o','cache_dir=/tmp/energy-D-pytest-cache',
    'tests/test_energy_accessibility.py','tests/test_energy_experience.py','tests/test_energy_guided.py',
    'tests/test_energy_provenance.py','tests/test_energy_days.py','tests/test_energy_account_roundtrip.py',
    '--junitxml=/evidence/linux-focal.xml'],cwd='/qa-backend',check=True)
# C regression includes official writer, rollback, owner, replay and db check in both isolations.
subprocess.run([python,'/qa-scripts/guided_mariadb_qa.py'],cwd='/qa-backend',check=True)
from sqlalchemy import text
from flask_migrate import check
from app import create_app
from app.extensions import db
from app.models import User
from app.services import energy_days as energy
from app.services.energy_history import consultation, MIN_DAY, MAX_DAY
from tests.test_energy_days import document,DAY

report=json.loads(Path('/evidence/mariadb.json').read_text())
report['delivery']='D with C regression';report['D']={}
for isolation in ('READ COMMITTED','REPEATABLE READ'):
    storage=Path(tempfile.mkdtemp(prefix='QA-energy-D-'))
    app=create_app({'TESTING':True,'WTF_CSRF_ENABLED':False,'SECRET_KEY':'fictional-D-local-MariaDB-signing-key',
        'DATA_ROOT':storage,'UPLOAD_ROOT':storage/'uploads/raw','GENERATED_UPLOAD_ROOT':storage/'uploads/generated',
        'PORTABILITY_ROOT':storage/'portability','SCHEMA_ROOT':Path('/schemas'),
        'SQLALCHEMY_ENGINE_OPTIONS':{'isolation_level':isolation},'NUTRITION_INTELLIGENCE_ENABLED':False,'NUTRITION_EXTERNAL_LOOKUP_ENABLED':False})
    with app.app_context():
        assert db.engine.url.database=='nutrition_intelligence_qa_20261009'
        assert db.session.scalar(text('SELECT DATABASE()'))=='nutrition_intelligence_qa_20261009'
        assert db.session.scalar(text('SELECT CURRENT_USER()')).startswith('progression_qa@')
        assert db.session.scalar(text('SELECT version_num FROM alembic_version'))=='20261018_0046'
        assert db.session.scalar(text('SELECT @@tx_isolation')).replace('-',' ')==isolation
        owner=User(username='QA-D-'+uuid.uuid4().hex,role='user');owner.set_password('fictional-D-password')
        other=User(username='QA-D-other-'+uuid.uuid4().hex,role='user');other.set_password('fictional-D-password')
        db.session.add_all([owner,other]);db.session.commit()
        energy.upsert_document(document(owner.id,'QA D known',total_expenditure_kcal=2450),owner.id)
        energy.upsert_document(document(other.id,'QA D foreign',total_expenditure_kcal=9999),other.id);db.session.commit()
        before=energy.state_fingerprint(owner.id,[DAY]);writes=[]
        from sqlalchemy import event
        def capture(conn,cursor,statement,parameters,context,executemany):
            if statement.lstrip().split()[0].upper() in ('INSERT','UPDATE','DELETE','REPLACE'):writes.append(statement.split()[0])
        event.listen(db.engine,'before_cursor_execute',capture)
        try:
            for target in (MIN_DAY,MAX_DAY):
                for period in (7,30,90):
                    result=consultation(owner.id,target,period)
                    assert all(result[k] is None or MIN_DAY<=result[k]<=MAX_DAY for k in ('previous','next','previous_month','next_month'))
            with app.test_client() as client:
                with client.session_transaction() as session:session['_user_id']=str(owner.id);session['_fresh']=True
                for path,code in (('/energy?date=1900-01-01',200),('/energy?date=9998-12-31',200),('/energy?date=bad',400),('/energy/sources?date='+str(DAY),200),('/energy/history',200),('/energy/review?date='+str(DAY),200)):
                    response=client.get(path);assert response.status_code==code
                    assert response.headers['Cache-Control']=='private, no-store'
                    assert b'QA D foreign' not in response.data
                response=client.post('/energy/review',data={'date':str(DAY),'action':'review','choice_steps':'manual','value_steps':'2.5'})
                assert response.status_code==400 and b'aria-invalid="true"' in response.data
            assert writes==[] and energy.state_fingerprint(owner.id,[DAY])==before
        finally:event.remove(db.engine,'before_cursor_execute',capture)
        check(directory='/qa-backend/migrations')
        report['D'][isolation]={'boundary_7_30_90':'PASS','owner_only':'PASS','recoverable_form_without_writes':'PASS','private_headers':'PASS','canonical_unchanged':'PASS','db_check':'PASS','DDL':False}
Path('/evidence/mariadb.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'status':'PASS','delivery':'D','isolations':list(report['D']),'head':'20261018_0046'}))
