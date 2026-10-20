"""B on existing LOCAL QA only, with real audit JSON queries and file checks."""
from pathlib import Path
import uuid,json,tempfile,copy,os
from datetime import timedelta
from sqlalchemy import text,event
from flask_migrate import check
from flask import g
from app import create_app
from app.extensions import db
from app.models import User,EnergyEvidenceEvent
from app.services import energy_provenance as provenance, energy_days
from tests.test_energy_provenance import seed,DAY
from tests.test_energy_days import document

report={'status':'PASS','scope':'existing LOCAL MariaDB isolated QA only','head':'20261018_0046','isolations':{}}
for isolation in ['READ COMMITTED','REPEATABLE READ']:
    storage=Path(tempfile.mkdtemp(prefix='QA-energy-B-'))
    app=create_app({'TESTING':True,'WTF_CSRF_ENABLED':False,'DATA_ROOT':storage,'UPLOAD_ROOT':storage/'uploads/raw',
        'GENERATED_UPLOAD_ROOT':storage/'uploads/generated','PORTABILITY_ROOT':storage/'portability',
        'SCHEMA_ROOT':Path('/schemas'),'SQLALCHEMY_ENGINE_OPTIONS':{'isolation_level':isolation},
        'NUTRITION_INTELLIGENCE_ENABLED':False,'NUTRITION_EXTERNAL_LOOKUP_ENABLED':False})
    with app.app_context():
        assert db.engine.url.database=='nutrition_intelligence_qa_20261009'
        assert db.session.scalar(text('SELECT DATABASE()'))=='nutrition_intelligence_qa_20261009'
        assert db.session.scalar(text('SELECT CURRENT_USER()')).startswith('progression_qa@')
        assert db.session.scalar(text('SELECT version_num FROM alembic_version'))==report['head']
        assert db.session.scalar(text('SELECT @@tx_isolation')).replace('-',' ')==isolation
        owner=User(username='QA-energy-B-'+uuid.uuid4().hex,role='user');owner.set_password('fictional-QA-password')
        db.session.add(owner);db.session.commit();data=seed(owner.id)
        for offset in range(110):
            energy_days.upsert_document(document(owner.id,'QA paginación',day=DAY-timedelta(days=offset+1),steps=offset),owner.id)
        db.session.commit()
        baseline=energy_days.state_fingerprint(owner.id,[DAY])
        before=db.session.query(EnergyEvidenceEvent).filter_by(user_id=owner.id).count()
        writes=[]
        def watch(conn,cursor,statement,parameters,context,executemany):
            if statement.lstrip().split()[0].upper() in ('INSERT','UPDATE','DELETE','REPLACE'):writes.append(statement.split()[0])
        event.listen(db.engine,'before_cursor_execute',watch)
        try:
            first=provenance.audit(owner.id,provenance.filters({}));assert first['total']>100
            sizes=[len(provenance.audit(owner.id,provenance.filters({'page':str(p)}))['items']) for p in range(1,first['pages']+1)]
            assert max(sizes)<=25 and sum(sizes)==first['total']
            selected=provenance.audit(owner.id,provenance.filters({'source':'QA paginación','from':'2040-02-01','to':'2040-02-02','operation':'import'}));assert selected['total']==2
            assert 'QA reloj' not in provenance.audit(data['other'],provenance.filters({}))['source_choices']
            with app.test_client() as client:
                with client.session_transaction() as session:session['_user_id']=str(owner.id);session['_fresh']=True
                assert client.get('/energy/sources?date=2040-02-03').status_code==200
                assert client.get('/energy/history?source=QA+paginaci%C3%B3n&page=5').status_code==200
                reference=provenance.original(owner.id,'source',data['row'],{f.id:f for f,_ in data['files']})['token']
                response=client.post('/energy/original',data={'reference':reference});assert response.status_code==200 and response.data==data['files'][0][1];response.close()
                with client.session_transaction() as session:session['_user_id']=str(data['other'])
                # This harness retains an outer application context; clear the
                # login cache that real WSGI request contexts naturally discard.
                g.pop('_login_user',None)
                assert client.post('/energy/original',data={'reference':reference}).status_code==404
            assert energy_days.state_fingerprint(owner.id,[DAY])==baseline and writes==[]
            assert db.session.query(EnergyEvidenceEvent).filter_by(user_id=owner.id).count()==before
        finally:event.remove(db.engine,'before_cursor_execute',watch)
        check(directory='/qa-backend/migrations')
        report['isolations'][isolation]={'status':'PASS','events':first['total'],'pages':len(sizes),'page_sizes':sizes,
            'json_source_and_combined_filters':'PASS','owner_isolation_and_original':'PASS','file_bytes':'identical',
            'domain_writes':0,'canonical_evidence_revision_events':'unchanged','db_check':'PASS'}
Path('/evidence/mariadb.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
