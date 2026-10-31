"""Issue #36, exclusively synthetic 2.1 source imports."""
import io
import json
import sys
import copy
import re
import os
import types
import subprocess
from datetime import timedelta
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.extensions import db
from app.models import FoodProduct,MealLog,NutritionImportReceipt,UploadedFile,User,NutritionImportDraft,DailyNutrition
from app.services import nutrition_import as imports,nutrition_import_review as review
from app.services.nutrition_math import NUTRIENTS,NutritionError
from app.services.validation import JsonSchemaValidationError,validate_json_document
from tests.conftest import login
from tests.test_nutrition_import_summary import token

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/nutrition'))
from qa_source_21_fixtures import source21,variant


@pytest.fixture
def app(app,tmp_path):
    """The same acceptance tests also run on a guarded disposable MariaDB."""
    url=os.environ.get('QA_SOURCE21_DATABASE_URL')
    if not url:
        yield app
        return
    from sqlalchemy.engine import make_url
    from sqlalchemy import text
    from flask_migrate import upgrade,check
    from app import create_app
    target=make_url(url)
    assert target.host=='127.0.0.1' and target.port==33436 and target.database=='nutrition_preview_qa'
    isolation=os.environ['QA_ISOLATION'];assert isolation in ['READ COMMITTED','REPEATABLE READ']
    config={k:app.config[k] for k in ['SECRET_KEY','API_TOKEN_SIGNING_KEY','SCHEMA_ROOT','APP_TIMEZONE']}
    isolated=create_app(dict(config,TESTING=True,WTF_CSRF_ENABLED=False,SQLALCHEMY_DATABASE_URI=url,
        SQLALCHEMY_ENGINE_OPTIONS={'isolation_level':isolation},DATA_ROOT=tmp_path,
        UPLOAD_ROOT=tmp_path/'uploads/raw',GENERATED_UPLOAD_ROOT=tmp_path/'generated',PORTABILITY_ROOT=tmp_path/'portability',
        AI_ENABLED=False,NUTRITION_EXTERNAL_LOOKUP_ENABLED=False))
    with isolated.app_context():
        assert db.session.execute(text('SELECT DATABASE()')).scalar()=='nutrition_preview_qa'
        db.session.rollback();db.drop_all();db.session.execute(text('DROP TABLE IF EXISTS alembic_version'));db.session.commit()
        upgrade(directory=str(ROOT/'backend/migrations'));check(directory=str(ROOT/'backend/migrations'))
        assert db.session.execute(text('SELECT version_num FROM alembic_version')).scalar()=='20261018_0046'
        db.session.rollback()
        yield isolated
        db.session.remove();db.drop_all();db.session.execute(text('DROP TABLE IF EXISTS alembic_version'));db.session.commit()


def test_source21_upload_recovers_nested_foods(app,client,user):
    app.config['NUTRITION_INTELLIGENCE_ENABLED']=True
    app.config['PROPAGATE_EXCEPTIONS']=False
    login(client)
    response=client.post('/nutrition/import',data={'file':(io.BytesIO(json.dumps(source21()).encode()),'QA synthetic 21.json')})
    assert response.status_code==302
    page=client.get(response.location)
    assert page.status_code==200 and page.text.count('class="ni-preview-record"')==21
    assert db.session.query(FoodProduct).count()==db.session.query(MealLog).count()==db.session.query(NutritionImportReceipt).count()==0
    assert 'ni-row-edit-form' not in page.text and not re.search(r'name="consent_consumed"[^>]*checked',page.text)


def start(app,user,document=None):
    app.config['NUTRITION_INTELLIGENCE_ENABLED']=True
    row=imports.start(user,json.dumps(document or source21()).encode(),'QA fictional source21.json')
    db.session.commit()
    return row


def expected(document):
    totals={k:Decimal(0) for k in NUTRIENTS}
    for entry in document['data']['entries']:
        for b in entry['bindings']:
            n=b['new_food']['nutrition'];factor=Decimal(b['amount'])/Decimal(n['basis_amount'])
            for k,v in n['nutrients'].items():
                if v['state']=='known':totals[k]+=Decimal(v['value'])*factor
    return totals


def test_all_nutrients_preview_daily_micros_dashboard_and_restore(app,client,user):
    from app.services import nutrition_intelligence as ni,nutrition_micros
    from app.services.exporters.user_data import build_user_data_document
    from app.services.account_restore import AccountRestoreService
    from app.services.nutrition_portability import export_bundle,semantic_snapshot
    doc=source21();totals=expected(doc);row=start(app,user,doc);login(client)
    view=review.overview(row)
    assert view['counts']==dict(ready=21,decision=0,invalid=0,omitted=0)
    assert len(view['groups'])==4 and len(view['day_summaries'])==1
    for k,total in totals.items():
        assert Decimal(view['batch_summary'][k]['value'])==total
        assert sum(Decimal(g['summary'][k]['value']) for g in view['groups'])==total
    assert sum(bool(r['item'].get('unit_label')) for r in view['records'])==3
    assert all(not r['confirmed'] and r['resolution']=='declared' and not r['ingredients'] for r in row.review_json['rows'])
    assert 'No contabilizados:' in client.get('/nutrition/import/'+row.public_id).text
    canonical=review.document(row);validate_json_document(canonical,'nutrition_import_2_1')
    with pytest.raises(JsonSchemaValidationError):validate_json_document(doc,'nutrition_import_2_1')
    values=dict(revision=row.revision,token=token(client,row))
    assert client.post('/nutrition/import/'+row.public_id+'/confirm',data=values).status_code==422
    assert db.session.query(MealLog).count()==0
    values['consent_consumed']='yes'
    assert client.post('/nutrition/import/'+row.public_id+'/confirm',data=values).status_code==200
    assert db.session.query(MealLog).count()==21 and db.session.query(FoodProduct).count()==0
    assert db.session.query(NutritionImportReceipt).count()==1
    day=ni.daily_summary(user,date(2026,1,15))['summary']
    for k,total in totals.items():assert Decimal(day[k]['value'])==total
    assert Decimal(day['carbohydrate_total']['value'])==210 and Decimal(day['net_carbs']['value'])==168
    logs=db.session.scalars(db.select(MealLog).order_by(MealLog.id)).all()
    for log,record in zip(logs,view['records']):
        assert log.snapshot_json['summary']==record['preview']
        assert log.snapshot_json['declared_nutrition']['original_values']==record['item']['original']
    assert len(db.session.query(DailyNutrition).one().meals)==4
    for period in [7,30,90]:
        micros=nutrition_micros.overview(user,date(2026,1,15),period,'calcium')
        assert Decimal(micros['summary']['calcium']['value'])==totals['calcium']
        assert len(micros['chart']['samples'])==period
        assert client.get('/nutrition/micronutrients?date=2026-01-15&period='+str(period)).status_code==200
        assert client.get('/dashboard?period='+str(period)+'&as_of=2026-01-15').status_code==200
        from app.services.dashboard import DashboardDateRange,DashboardSummaryService
        selected=DashboardDateRange.from_query({'as_of':'2026-01-15','period':str(period)},'UTC')
        dashboard=DashboardSummaryService().build(user,selected,'kg')
        for key,total in totals.items():assert Decimal(dashboard['nutrient_details']['2026-01-15'][key]['value'])==total
    assert client.get('/nutrition/?date=2026-01-15').status_code==200
    assert client.post('/nutrition/import/'+row.public_id+'/confirm',data=values).status_code==200
    assert db.session.query(MealLog).count()==21
    target=User(username='QA source21 restore',role='user');target.set_password('fictional restore only')
    db.session.add(target);db.session.commit()
    payload=build_user_data_document(db.session.get(User,user),user)
    service=AccountRestoreService();plan=service.preview(payload,user_id=target.id)
    assert service.commit(payload,user_id=target.id,confirmation_token=plan['confirmation_token'])['committed']
    assert [semantic_snapshot(r['snapshot']) for r in export_bundle(target.id)['logs']]==[semantic_snapshot(r['snapshot']) for r in export_bundle(user)['logs']]


@pytest.mark.parametrize('case',['malformed','wrong-version','wrong-type','bad-binding','bad-ref-unit','missing-nutrition'])
def test_irrecoverable_is_controlled_before_storage(app,client,user,case):
    app.config['NUTRITION_INTELLIGENCE_ENABLED']=True;login(client);doc=source21()
    if case=='malformed':doc=variant('malformed')
    elif case=='wrong-version':doc['schema_version']='99.0'
    elif case=='wrong-type':doc['type']='unknown_type'
    elif case=='bad-binding':doc['data']['entries'][0]['bindings'][0]='not a binding'
    elif case=='bad-ref-unit':doc['data']['entries'][0]['bindings'][0]=dict(ref='catalog:00000000-0000-0000-0000-000000000000',food_revision='1',amount='20',unit={})
    else:doc['data']['entries'][0]['bindings'][0]['new_food']['nutrition']=None
    response=client.post('/nutrition/import',data={'file':(io.BytesIO(json.dumps(doc).encode()),'QA invalid.json')})
    assert response.status_code==422 and 'Traceback' not in response.text
    assert db.session.query(UploadedFile).count()==db.session.query(NutritionImportDraft).count()==0
    assert not list(Path(app.config['UPLOAD_ROOT']).rglob('*'))


def test_post_storage_validation_failure_no_orphans_or_duplicate_damage(app,client,user,monkeypatch):
    row=start(app,user);login(client);before=copy.deepcopy(row.review_json);source=db.session.query(UploadedFile).one()
    files=list(Path(app.config['UPLOAD_ROOT']).rglob('*'));source_id=source.id
    def fail(*args,**kwargs):raise JsonSchemaValidationError(['QA_PRIVATE_PAYLOAD_MUST_NOT_BE_RENDERED'])
    monkeypatch.setattr(imports,'_review_from_source',fail)
    for doc in [source21(),variant('partial')]:
        result=client.post('/nutrition/import',data={'file':(io.BytesIO(json.dumps(doc).encode()),'QA failing.json')})
        assert result.status_code==422 and 'QA_PRIVATE_PAYLOAD' not in result.text
    assert db.session.query(UploadedFile).one().id==source_id
    assert db.session.get(NutritionImportDraft,row.id).review_json==before
    assert list(Path(app.config['UPLOAD_ROOT']).rglob('*'))==files


def test_partial_qualifiers_and_net_only_remain_unknown(app,client,user):
    row=start(app,user,variant('partial'));view=review.overview(row);login(client)
    assert view['counts']['ready']==21
    for key in ['vitamin_d','iron','zinc','carbohydrate_total']:
        assert view['batch_summary'][key]['value'] is None
    assert view['batch_summary']['net_carbs']['value']=='168'
    assert client.post('/nutrition/import/'+row.public_id+'/confirm',data=dict(revision=row.revision,token=token(client,row),consent_consumed='yes')).status_code==200
    from app.services.nutrition_micros import overview
    view=overview(user,date(2026,1,15),7,'iron')
    assert view['qualifiers']['iron']['trace']==21 and view['qualifiers']['zinc']['below_limit']==21
    assert view['summary']['vitamin_d']['value'] is None


def test_one_conflict_scoped_correction_and_strict_canonical_roundtrip(app,user):
    row=start(app,user,variant('conflict'));before=copy.deepcopy(row.review_json)
    assert review.overview(row)['counts']['decision']==1
    review.save_decisions(user,row.public_id,row.revision,dict(edit_index='1',r1_basis_amount=before['rows'][1]['basis_amount'],r1_basis_unit='g',r1_basis_verified='yes'))
    db.session.commit();assert review.overview(row)['counts']['ready']==21
    assert all(a==b for i,(a,b) in enumerate(zip(before['rows'],row.review_json['rows'])) if i!=1)
    doc=review.document(row);validate_json_document(doc,'nutrition_import_2_1')
    again=start(app,user,doc)
    assert review.overview(again)['counts']['ready']==21
    assert review.overview(again)['batch_summary']==review.overview(row)['batch_summary']


def test_same_unit_concentration_scales_once_and_keeps_evidence(app,user):
    doc=source21();b=doc['data']['entries'][0]['bindings'][1]
    b['new_food']['nutrition']['basis_amount']=str(Decimal(b['amount'])*2)
    row=start(app,user,doc);record=review.overview(row)['records'][1]
    for key,n in b['new_food']['nutrition']['nutrients'].items():assert Decimal(record['preview'][key]['value'])==Decimal(n['value'])/2
    assert record['item']['original']['new_food']['nutrition']['provenance']['additional_nutrients']


def test_nominal_plural_labels_and_unsupported_notes_are_auditable(app,user):
    doc=source21();b=doc['data']['entries'][0]['bindings'][0];b['unit']='bolsas'
    doc['data']['notes']='QA ONLY: biotin 300 ug and B5 2 mg are unsupported prose, never verified amounts.'
    doc['data']['entries'][0]['notes']='QA parent evidence retained once in its first ingredient.'
    row=start(app,user,doc);view=review.overview(row)
    assert view['counts']['ready']==21
    assert row.review_json['rows'][0]['unit_label']==row.review_json['rows'][0]['basis_label']=='bolsa'
    assert row.review_json['rows'][0]['original']['unit']=='bolsas'
    assert row.source_json['document_notes']==[doc['data']['notes']]
    assert any('Biotina' in w and 'No contabilizados' in w for w in row.review_json['rows'][0]['warnings'])
    assert any('B5' in w for w in row.review_json['rows'][0]['warnings'])
    assert row.review_json['rows'][0]['original']['source_entry']['notes']==doc['data']['entries'][0]['notes']
    assert all('notes' not in r['original']['source_entry'] for r in row.review_json['rows'][1:5])


def test_canonical_source_cannot_preaccept_existing_day(app,client,user):
    row=start(app,user);login(client);document=review.document(row)
    assert client.post('/nutrition/import/'+row.public_id+'/confirm',data=dict(revision=row.revision,token=token(client,row),consent_consumed='yes')).status_code==200
    for entry in document['data']['entries']:entry.update(conflict_action='keep_and_add',authority='disjoint_aggregate',confirmed=True)
    again=start(app,user,document)
    assert review.overview(again)['counts']['decision']==21
    assert all(not r.get('conflict_action') and not r.get('authority') and not r['confirmed'] for r in again.review_json['rows'])
    assert db.session.query(MealLog).count()==21


def test_owner_csrf_signature_stale_and_atomic_rollback(app,client,user,monkeypatch):
    row=start(app,user);login(client);path='/nutrition/import/'+row.public_id;signed=token(client,row)
    app.config['WTF_CSRF_ENABLED']=True
    assert client.post(path+'/confirm',data=dict(revision=row.revision,token=signed,consent_consumed='yes')).status_code==400
    app.config['WTF_CSRF_ENABLED']=False
    assert client.post(path+'/confirm',data=dict(revision=row.revision,token='invalid-signature',consent_consumed='yes')).status_code==409
    assert client.post(path+'/confirm',data=dict(revision=row.revision-1,token=signed,consent_consumed='yes')).status_code==409
    original=imports.apply_document
    def fail(*args,**kwargs):original(*args,**kwargs);raise RuntimeError('QA synthetic rollback after writes')
    monkeypatch.setattr(imports,'apply_document',fail)
    response=client.post(path+'/confirm',data=dict(revision=row.revision,token=signed,consent_consumed='yes'))
    assert response.status_code==409
    assert db.session.query(MealLog).count()==db.session.query(FoodProduct).count()==db.session.query(NutritionImportReceipt).count()==0
    other=User(username='QA source21 other owner',role='user');other.set_password('fictional only');db.session.add(other);db.session.commit()
    from flask import g
    with client.session_transaction() as session:session['_user_id']=str(other.id)
    g.pop('_login_user',None)
    assert client.get(path).status_code==404
    assert client.post(path+'/decisions',data=dict(revision=row.revision,user_id=user)).status_code==404


def test_exact_catalog_binding_preserves_revision_and_owner(app,user):
    from app.services import food_catalog as catalog
    fixtures=ROOT/'examples/qa/nutrition-import-ux'
    catalog.stage(json.loads((fixtures/'catalog.json').read_text(encoding='utf-8')))
    catalog.activate('qa_import_ux','1',1);db.session.commit()
    food=catalog.detail(user,catalog.search(user,'',limit=1)[0]['ref'])
    doc=source21();doc['data']['entries'][0]['bindings'][1]=dict(ref=food['ref'],food_revision=str(food['revision']),amount='25',unit='g')
    row=start(app,user,doc);view=review.overview(row)
    assert view['counts']['ready']==21
    item=view['records'][1]['item'];assert item['ingredients'][0]['ref']==food['ref']
    assert item['name']==food['name'] and not item.get('resolution')


def test_canonical_compound_authority_keeps_exact_bindings(app,user):
    from app.services import food_catalog as catalog
    fixtures=ROOT/'examples/qa/nutrition-import-ux'
    catalog.stage(json.loads((fixtures/'catalog.json').read_text(encoding='utf-8')))
    catalog.activate('qa_import_ux','1',1);db.session.commit()
    food=catalog.detail(user,catalog.search(user,'',limit=1)[0]['ref'])
    row=start(app,user);doc=review.document(row);entry=doc['data']['entries'][1]
    entry['bindings']=[dict(ref=food['ref'],food_revision=str(food['revision']),amount=entry['portion_amount'],unit=entry['portion_unit'])]
    doc['data']['entries']=[entry];validate_json_document(doc,'nutrition_import_2_1')
    again=start(app,user,doc);item=review.overview(again)['records'][0]['item']
    assert item['ingredients']==entry['bindings'] and review.overview(again)['counts']['ready']==1
    assert Decimal(review.overview(again)['batch_summary']['energy']['value'])==Decimal(entry['declaration']['nutrients']['energy']['value'])


@pytest.mark.parametrize('expired',[False,True])
def test_actual_v5_accepted_basis_survives_unrelated_v6_adapter(app,user,expired):
    app.config['NUTRITION_INTELLIGENCE_ENABLED']=True
    modules={}
    for kind,path in [('parser','backend/app/services/importers/nutrition_sources.py'),('service','backend/app/services/nutrition_import.py')]:
        module=types.ModuleType('qa36_prior_v5_'+kind);module.__file__=str(ROOT/path)
        exec(compile(subprocess.check_output(['git','show','01b49cafc36ec95e11d0aed3aca11dcfdf49a5c0:'+path]),str(ROOT/path),'exec'),module.__dict__)
        modules[kind]=module
    modules['service'].extract=modules['parser'].extract
    modules['service'].EXTRACTOR_VERSION=modules['parser'].EXTRACTOR_VERSION
    payload=(ROOT/'examples/qa/nutrition-note-semantics/long-note-23.json').read_bytes()
    old=modules['service'].start(user,payload,'QA actual v5 synthetic.json');db.session.commit()
    review.save_decisions(user,old.public_id,old.revision,{'accept_legacy_totals':'yes'});db.session.commit()
    assert review.overview(old)['counts']['ready']==23
    if expired:old.created_at-=timedelta(days=2);db.session.commit()
    frozen=copy.deepcopy(old.review_json);created=old.created_at;revision=old.revision
    from app.services.nutrition_import_reprocess import reprocess
    fresh=reprocess(user,old.public_id,old.revision);db.session.commit()
    assert fresh.id!=old.id and fresh.source_sha256==old.source_sha256
    assert review.overview(fresh)['counts']['ready']==23
    assert fresh.source_json['reprocess_pending']
    with pytest.raises(NutritionError):review.document(fresh)
    review.save_decisions(user,fresh.public_id,fresh.revision,{'accept_previous':'yes'});db.session.commit()
    assert review.document(fresh)['data']['entries']
    assert old.review_json==frozen and old.created_at==created and old.revision==revision
