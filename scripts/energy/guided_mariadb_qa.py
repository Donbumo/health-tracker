"""C on existing LOCAL isolated MariaDB QA only; fictional owners and private temp files."""
from pathlib import Path
from datetime import timedelta
import json,tempfile,uuid,hashlib
from unittest.mock import patch
from sqlalchemy import text
from flask_migrate import check
from flask import g
from app import create_app
from app.extensions import db
from app.models import User,DailyEnergy,EnergyEvidenceEvent,UploadedFile
from app.services import energy_days as energy
from app.services.importers.standard_import_executor import StandardImportExecutor
from tests.test_energy_guided import final_import,advance,final_review,seed_conflict,hidden
from tests.test_energy_days import document,DAY

report={'status':'PASS','scope':'existing LOCAL MariaDB QA only; fictional fixtures','head':'20261018_0046','isolations':{}}
for isolation in ('READ COMMITTED','REPEATABLE READ'):
    storage=Path(tempfile.mkdtemp(prefix='QA-energy-C-'))
    app=create_app({'TESTING':True,'WTF_CSRF_ENABLED':False,'SECRET_KEY':'fictional-C-local-MariaDB-signing-key',
        'DATA_ROOT':storage,'UPLOAD_ROOT':storage/'uploads/raw','GENERATED_UPLOAD_ROOT':storage/'uploads/generated',
        'PORTABILITY_ROOT':storage/'portability','SCHEMA_ROOT':Path('/schemas'),
        'SQLALCHEMY_ENGINE_OPTIONS':{'isolation_level':isolation},'NUTRITION_INTELLIGENCE_ENABLED':False,'NUTRITION_EXTERNAL_LOOKUP_ENABLED':False})
    with app.app_context():
        assert db.engine.url.database=='nutrition_intelligence_qa_20261009'
        assert db.session.scalar(text('SELECT DATABASE()'))=='nutrition_intelligence_qa_20261009'
        assert db.session.scalar(text('SELECT CURRENT_USER()')).startswith('progression_qa@')
        assert db.session.scalar(text('SELECT version_num FROM alembic_version'))==report['head']
        assert db.session.scalar(text('SELECT @@tx_isolation')).replace('-',' ')==isolation
        owner=User(username='QA-C-'+uuid.uuid4().hex,role='user');owner.set_password('fictional-C-password')
        other=User(username='QA-C-other-'+uuid.uuid4().hex,role='user');other.set_password('fictional-C-password')
        db.session.add_all([owner,other]);db.session.commit();seed_conflict(owner.id)
        baseline=energy.state_fingerprint(owner.id,[DAY]);event_count=db.session.query(EnergyEvidenceEvent).filter_by(user_id=owner.id).count()
        with app.test_client() as client:
            with client.session_transaction() as session:session['_user_id']=str(owner.id);session['_fresh']=True
            import_day=DAY+timedelta(days=10);doc=document(owner.id,'QA C Maria',day=import_day,steps=0)
            final=final_import(client,doc)
            assert energy.view(owner.id,import_day) is None
            assert db.session.query(UploadedFile).filter_by(user_id=owner.id).count()==0
            assert energy.state_fingerprint(owner.id,[DAY])==baseline
            assert advance(client,final,'confirm',confirm='yes').status_code==302
            result=energy.view(owner.id,import_day);assert result.steps==0 and result.total_calories is None
            revision=result.revision;events=db.session.query(EnergyEvidenceEvent).filter_by(user_id=owner.id).count()
            assert events==event_count+1
            raw=json.dumps(doc).encode();original_file=db.session.scalar(db.select(UploadedFile).where(UploadedFile.user_id==owner.id))
            assert original_file.sha256==hashlib.sha256(raw).hexdigest() and original_file.size_bytes==len(raw)
            assert advance(client,final,'confirm',confirm='yes').status_code==302
            assert energy.view(owner.id,import_day).revision==revision
            assert db.session.query(EnergyEvidenceEvent).filter_by(user_id=owner.id).count()==events
            final_decision=final_review(client,choice_total_calories='manual',value_total_calories='2450',choice_steps='clear')
            assert energy.view(owner.id,DAY).total_calories is None
            assert advance(client,final_decision,'confirm',path='/energy/review',confirm='yes').status_code==302
            assert energy.view(owner.id,DAY).total_calories==2450 and energy.view(owner.id,DAY).steps is None
            assert {r.total_calories for r in db.session.scalars(db.select(DailyEnergy).where(DailyEnergy.user_id==owner.id,DailyEnergy.date==DAY))}=={2400,2500}
            stale=final_review(client,choice_total_calories='manual',value_total_calories='2460')
            energy.edit_day(owner.id,DAY,energy.view(owner.id,DAY).revision,{'total_calories':2470});db.session.commit()
            assert advance(client,stale,'confirm',path='/energy/review',confirm='yes').status_code==409
            assert energy.view(owner.id,DAY).total_calories==2470
            failure_day=DAY+timedelta(days=20);failure=final_import(client,document(owner.id,'QA C rollback',day=failure_day,steps=1))
            original=StandardImportExecutor._apply_document
            def failure_after_flush(self,*args,**kwargs):
                original(self,*args,**kwargs);db.session.flush();raise RuntimeError('fictional QA rollback')
            with patch.object(StandardImportExecutor,'_apply_document',failure_after_flush):
                assert advance(client,failure,'confirm',confirm='yes').status_code==409
            assert energy.view(owner.id,failure_day) is None
            assert db.session.scalar(db.select(db.func.count()).select_from(EnergyEvidenceEvent).where(EnergyEvidenceEvent.user_id==owner.id,EnergyEvidenceEvent.date==failure_day))==0
            foreign=final_review(client,choice_total_calories='manual',value_total_calories='2480')
            with client.session_transaction() as session:session['_user_id']=str(other.id)
            g.pop('_login_user',None)
            assert advance(client,foreign,'confirm',path='/energy/review',confirm='yes').status_code==404
            assert energy.view(owner.id,DAY).total_calories==2470 and energy.view(other.id,DAY) is None
        check(directory='/qa-backend/migrations')
        report['isolations'][isolation]={'status':'PASS','four_stages_and_preview_no_writes':'PASS','unknown_vs_zero':'PASS',
            'exact_original_and_single_event':'PASS','replay_no_revision_or_event':'PASS','explicit_manual_and_clear':'PASS',
            'source_values_and_history':'preserved','stale_revision_409':'PASS','domain_rollback_after_flush':'PASS',
            'owner_isolation_404':'PASS','db_check':'PASS'}
Path('/evidence/mariadb.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
