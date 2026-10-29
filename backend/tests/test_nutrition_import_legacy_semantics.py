"""Synthetic structure regression for daily_nutrition 1.0 semantics, never personal data."""
import copy
import json
import subprocess
import types
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import event
from app.extensions import db
from app.models import DailyNutrition, FoodProduct, MealLog, NutritionImportDraft, NutritionImportReceipt, User
from app.services import nutrition_import as imports, nutrition_import_review as compact
from app.services.importers.nutrition_sources import extract, EXTRACTOR_VERSION
from app.services.nutrition_import_reprocess import reprocess
from app.services.nutrition_math import NutritionError
from tests.conftest import login
from tests.test_nutrition_import_summary import token

ROOT=Path(__file__).resolve().parents[2]
FIXTURE=ROOT/'examples/qa/nutrition-import-ux/legacy-daily-semantic-21.json'


def start(app,user,payload=None):
    app.config['NUTRITION_INTELLIGENCE_ENABLED']=True
    row=imports.start(user,payload or FIXTURE.read_bytes(),'QA legacy semantic fictional.json')
    db.session.commit()
    return row


def decisions():
    return {'accept_legacy_totals':'yes','use_declarations':'yes',
        'r10_interpretation':'consumed_total','r11_nutrient_fiber_action':'unknown'}


def resolve(row,user):
    compact.save_decisions(user,row.public_id,row.revision,decisions());db.session.commit()


def test_structure_missing_bases_and_grouped_interpretation(app,user):
    payload=FIXTURE.read_bytes(); source=json.loads(payload)
    original=[i for m in source['data']['meals'] for i in m['items']]
    assert len(original)==21 and sum('basis_amount' not in r for r in original)==20
    row=start(app,user);frozen=copy.deepcopy(row.review_json)
    view=compact.overview(row)
    assert view['counts']==dict(ready=3,decision=18,invalid=0,omitted=0),view['counts']
    assert view['legacy_total_count']==17
    assert row.review_json==frozen  # GET/read helpers never persist normalization
    compact.save_decisions(user,row.public_id,row.revision,{'accept_legacy_totals':'yes'});db.session.commit()
    view=compact.overview(row)
    assert view['counts']['ready']==19 and view['counts']['decision']==2
    assert {r['index'] for r in view['records'] if r['issues']}=={10,11}
    with pytest.raises(NutritionError):compact.document(row)
    resolve(row,user)
    assert compact.overview(row)['counts']['ready']==21
    assert imports.verified_original(row)[1]['rows']
    assert imports.verified_original(row)[0].sha256==row.source_sha256


def test_totals_scale_once_quality_unknown_zero_trace_limit(app,client,user):
    row=start(app,user);resolve(row,user)
    document=compact.document(row); entries=document['data']['entries']
    for i in [1,2,3,4,5,6,7,12,13,14,15,16,17,18,19,20]:
        entry=entries[i]
        assert Decimal(entry['declaration']['basis_amount'])==Decimal(entry['portion_amount'])
    expected=Decimal(0)
    for entry in entries:
        expected+=Decimal(entry['declaration']['nutrients']['energy']['value'])*Decimal(entry['portion_amount'])/Decimal(entry['declaration']['basis_amount'])
    assert entries[3]['declaration']['nutrients']['energy']['provenance']['quality']=='estimated'
    assert entries[3]['declaration']['provenance']['basis_interpretation']['measurement_verified'] is False
    login(client)
    signed=token(client,row); assert signed
    data={'revision':row.revision,'token':signed}
    assert client.post('/nutrition/import/'+row.public_id+'/confirm',data=data).status_code==422
    data['consent_consumed']='yes'
    assert client.post('/nutrition/import/'+row.public_id+'/confirm',data=data).status_code==200
    assert client.post('/nutrition/import/'+row.public_id+'/confirm',data=data).status_code==200
    logs=db.session.query(MealLog).all()
    assert len(logs)==21 and db.session.query(FoodProduct).count()==0 and db.session.query(NutritionImportReceipt).count()==1
    assert sum(Decimal(log.snapshot_json['summary']['energy']['value']) for log in logs)==expected
    byname={log.snapshot_json['name']:log.snapshot_json for log in logs}
    assert byname[entries[3]['name']]['declared_nutrition']['nutrients']['energy']['provenance']['quality']=='estimated'
    assert byname[entries[2]['name']]['summary']['energy']['total_weight'] is None
    assert byname[entries[7]['name']]['summary']['energy']['total_weight'] is None
    assert byname[entries[11]['name']]['summary']['fiber']['value'] is None
    assert byname[entries[1]['name']]['summary']['fiber']['value']=='0'
    assert all(log.snapshot_json['summary']['vitamin_c']['value'] is None for log in logs)
    def no_dml(conn,cursor,stmt,params,context,many):
        assert stmt.lstrip().split()[0].upper() not in {'INSERT','UPDATE','DELETE','CREATE','ALTER','DROP','REPLACE'}
    event.listen(db.engine,'before_cursor_execute',no_dml)
    try:
        paths=['/nutrition/?date=2026-01-15','/dashboard?as_of=2026-01-15','/energy?date=2026-01-15','/nutrition/library']
        paths+=['/nutrition/micronutrients?date=2026-01-15&period='+str(period) for period in [7,30,90]]
        for path in paths:
            response=client.get(path);assert response.status_code==200,(path,response.status_code)
    finally:event.remove(db.engine,'before_cursor_execute',no_dml)
    assert Decimal(byname[entries[8]['name']]['summary']['energy']['value'])==Decimal('72')
    assert Decimal(byname[entries[9]['name']]['summary']['energy']['value'])==Decimal('122.5')
    from app.services.nutrition_portability import export_bundle,semantic_snapshot
    from app.services.exporters.user_data import build_user_data_document
    from app.services.account_restore import AccountRestoreService
    target=User(username='QA semantic restore',role='user');target.set_password('QA fictitious');db.session.add(target);db.session.commit()
    original=export_bundle(user);payload=build_user_data_document(db.session.get(User,user),user)
    service=AccountRestoreService();preview=service.preview(payload,user_id=target.id)
    assert service.commit(payload,user_id=target.id,confirmation_token=preview['confirmation_token'])['committed']
    restored=export_bundle(target.id)
    assert [semantic_snapshot(r['snapshot']) for r in restored['logs']]==[semantic_snapshot(r['snapshot']) for r in original['logs']]


@pytest.mark.parametrize('choice,quantity,expected',[('source_total','180','60.991735537190'),('consumed_total','180','41'),('per_100ml','180','73.8')])
def test_conscious_quantity_correction_vs_original_total(app,user,choice,quantity,expected):
    row=start(app,user)
    compact.save_decisions(user,row.public_id,row.revision,{'r1_amount':quantity,'r1_interpretation':choice});db.session.commit()
    view=compact.overview(row);item=view['records'][1]
    assert item['state']=='ready',item['issues']
    assert Decimal(item['preview']['energy']['value'])==Decimal(expected)


def test_group_cannot_accept_changed_quantity_or_unknown_contract(app,user):
    row=start(app,user)
    compact.save_decisions(user,row.public_id,row.revision,{'r1_amount':'180'});db.session.commit()
    assert compact.overview(row)['legacy_total_count']==16
    compact.save_decisions(user,row.public_id,row.revision,{'accept_legacy_totals':'yes'});db.session.commit()
    assert row.review_json['rows'][1]['basis_interpretation']['status']=='proposed'
    assert row.review_json['rows'][10]['basis_interpretation']['status']=='proposed'
    assert not row.review_json['rows'][6].get('equivalence_confirmed')
    assert compact.overview(row)['records'][6]['state']=='ready'


def test_unknown_version_and_conflicting_bases_are_never_grouped(app,user):
    doc=json.loads(FIXTURE.read_bytes());doc['schema_version']='9.9'
    row=start(app,user,json.dumps(doc).encode())
    assert compact.overview(row)['legacy_total_count']==0
    doc=json.loads(FIXTURE.read_bytes());item=doc['data']['meals'][0]['items'][0]
    item.update(basis_amount='1',basis_unit='portion')
    row=start(app,user,json.dumps(doc).encode())
    assert row.review_json['rows'][0]['basis_interpretation']['kind']=='contradictory_basis'
    assert compact.overview(row)['records'][0]['state']=='decision'


def test_commercial_nominal_basis_does_not_invent_mass(app,user):
    row=start(app,user,(FIXTURE.parent/'legacy-commercial-basis.json').read_bytes())
    item=row.review_json['rows'][0]
    assert item['basis_amount']=='1' and item['basis_unit']=='portion'
    assert item['basis_label']=='lata' and item['unit_label']=='lata'
    assert compact.overview(row)['counts']['ready']==1
    document=compact.document(row)
    snapshot=imports.meal_snapshot(document['data']['entries'][0],[],'UTC')
    assert snapshot['summary']['energy']['value']=='104'
    assert snapshot['summary']['energy']['total_weight'] is None


@pytest.mark.parametrize('sha',['1cf8d830ba801a8c8121cf594b07a0269a6d6e6f','12bad71a60b96b57d282cfaf745fc0dc4ed27ab6'])
@pytest.mark.parametrize('expired',[False,True])
def test_real_prior_code_forks_preserve_original_and_later_edits(app,user,sha,expired):
    app.config['NUTRITION_INTELLIGENCE_ENABLED']=True
    modules={}
    for name,path in [('parser','backend/app/services/importers/nutrition_sources.py'),('service','backend/app/services/nutrition_import.py')]:
        code=subprocess.check_output(['git','show',sha+':'+path],cwd=ROOT)
        module=types.ModuleType('qa_'+name);exec(compile(code,sha+'/'+path,'exec'),module.__dict__);modules[name]=module
    service=modules['service'];service.extract=modules['parser'].extract
    if hasattr(modules['parser'],'EXTRACTOR_VERSION'):service.EXTRACTOR_VERSION=modules['parser'].EXTRACTOR_VERSION
    old=service.start(user,FIXTURE.read_bytes(),'QA same retained legacy.json')
    service.update(user,old.public_id,old.revision,'destination',{'destination':'consumed','name':'QA prior decisions'})
    service.update(user,old.public_id,old.revision,'fields',{'index':'1','_section':'identity','name':'QA preserved name','date':'2026-01-15','meal_type':'breakfast'})
    from app.services import food_catalog as catalog
    catalog.stage(json.loads((FIXTURE.parent/'consumed-catalog.json').read_text(encoding='utf-8')))
    catalog.activate('qa_import_consumed','1',1);db.session.commit()
    ref=next(h['ref'] for h in catalog.search(user,source='qa_import_consumed') if h['source_food_id']=='1')
    service.update(user,old.public_id,old.revision,'bind',{'index':'0','ref':ref,'food_revision':'1','amount':'120','unit':'g'})
    assert compact.overview(old)['counts']['ready']==1
    assert compact.overview(old)['counts']['decision']==20
    service.update(user,old.public_id,old.revision,'fields',{'index':'1','_section':'composition','amount':'180','unit':'g'})
    if expired:old.created_at-=timedelta(days=2)
    db.session.commit();frozen=copy.deepcopy(old.review_json);source=copy.deepcopy(old.source_json);created=old.created_at;revision=old.revision
    fresh=reprocess(user,old.public_id,revision);db.session.commit()
    assert fresh.source_json['extractor_version']==EXTRACTOR_VERSION and fresh.source_json['reprocess_pending']
    assert fresh.review_json['rows'][1]['name']=='QA preserved name' and fresh.review_json['rows'][1]['amount']=='180'
    assert fresh.review_json['rows'][1]['basis_amount']=='121'  # original quantity, not the later correction
    compact.save_decisions(user,fresh.public_id,fresh.revision,{'r2_name':'QA later independent edit'});db.session.commit()
    assert reprocess(user,old.public_id,revision).id==fresh.id
    assert fresh.review_json['rows'][2]['name']=='QA later independent edit'
    assert old.review_json==frozen and old.source_json==source and old.created_at==created
    assert db.session.query(MealLog).count()==db.session.query(FoodProduct).count()==0
    assert db.session.query(NutritionImportDraft).count()==2
    with pytest.raises(NutritionError,match='campos conservados'):compact.document(fresh)


def test_get_owner_csrf_signature_rollback_existing_day_and_stale_revision(app,client,user):
    row=start(app,user);login(client);key=row.public_id
    def guard(conn,cursor,stmt,params,context,many):
        assert stmt.lstrip().split()[0].upper() not in {'INSERT','UPDATE','DELETE','CREATE','ALTER','REPLACE','DROP'}
    event.listen(db.engine,'before_cursor_execute',guard)
    try:
        response=client.get('/nutrition/import/'+key)
        assert response.status_code==200 and 'Interpretación del archivo' in response.text
        assert 'private, no-store' in response.headers.get('Cache-Control','')
    finally:event.remove(db.engine,'before_cursor_execute',guard)
    other=User(username='QA another owner',role='user');other.set_password('QA');db.session.add(other);db.session.commit()
    with pytest.raises(NutritionError) as error:compact.save_decisions(other.id,key,row.revision,decisions())
    assert error.value.status==404
    from flask import g
    other_client=app.test_client()
    g.pop('_login_user',None)  # fixture keeps one app context across requests
    login(other_client,'QA another owner','QA')
    assert other_client.get('/nutrition/import/'+key).status_code==404
    assert other_client.post('/nutrition/import/'+key+'/decisions',data={'revision':row.revision,**decisions()}).status_code==404
    g.pop('_login_user',None)
    app.config['WTF_CSRF_ENABLED']=True
    assert client.post('/nutrition/import/'+key+'/decisions',data=decisions()).status_code==400
    app.config['WTF_CSRF_ENABLED']=False
    old_revision=row.revision;resolve(row,user)
    assert client.post('/nutrition/import/'+key+'/decisions',data={'revision':old_revision,**decisions()}).status_code==409
    assert client.post('/nutrition/import/'+key+'/confirm',data={'revision':row.revision,'token':'QA invalid','consent_consumed':'yes'}).status_code==409
    from app.services import nutrition_intelligence as ni
    actual=ni.confirm
    def fail_after_flush(*args,**kwargs):
        actual(*args,**kwargs);raise NutritionError('QA induced rollback')
    with patch.object(ni,'confirm',side_effect=fail_after_flush):
        assert client.post('/nutrition/import/'+key+'/confirm',data={'revision':row.revision,'token':token(client,row),'consent_consumed':'yes'}).status_code==409
    assert db.session.query(MealLog).count()==db.session.query(NutritionImportReceipt).count()==0
    day=DailyNutrition(user_id=user,date=date(2026,1,15),calories=100,source='manual')
    db.session.add(day);db.session.commit()
    assert compact.overview(row)['counts']['decision']==21
    compact.save_decisions(user,key,row.revision,{'day_2026-01-15_conflict_action':'keep_and_add','day_2026-01-15_authority':'disjoint_aggregate'});db.session.commit()
    assert compact.overview(row)['counts']['ready']==21


def test_mixed_bases_and_new_extracted_nutrients_cannot_be_silently_lost(app,user):
    doc=json.loads(FIXTURE.read_bytes());item=doc['data']['meals'][0]['items'][1]
    item['calories_per_100g']=99
    row=start(app,user,json.dumps(doc).encode())
    assert row.review_json['rows'][1]['basis_interpretation']['kind']=='contradictory_basis'
    assert compact.overview(row)['records'][1]['state']=='decision'


def test_qualified_states_explicit_basis_and_canonical_roundtrip(app,user):
    doc=json.loads(FIXTURE.read_bytes());item=doc['data']['meals'][0]['items'][0]
    item['nutrients']={'iron':{'state':'trace','unit':'mg'},'sodium':{'state':'below_limit','unit':'mg','limit':'2'},'vitamin_d':{'state':'known','unit':'ug','value':'0'}}
    row=start(app,user,json.dumps(doc).encode());resolve(row,user)
    document=compact.document(row)
    snapshot=imports.meal_snapshot(document['data']['entries'][0],[],'UTC')
    vector=snapshot['declared_nutrition']['nutrients']
    assert vector['iron']['state']=='trace' and vector['sodium']['state']=='below_limit'
    assert vector['sodium']['limit']=='2.4'
    assert Decimal(snapshot['summary']['vitamin_d']['value'])==0
    again=start(app,user,json.dumps(document).encode())
    doc2=compact.document(again)
    assert doc2['data']['entries'][0]['declaration']['provenance']['basis_interpretation']==document['data']['entries'][0]['declaration']['provenance']['basis_interpretation']


def test_group_preserves_previous_explicit_basis_and_empty_reviewed_vector(app,user):
    row=start(app,user)
    data=copy.deepcopy(row.review_json);data['rows'][1].update(basis_amount='100',basis_unit='ml')
    row.review_json=data;db.session.commit()
    assert compact.overview(row)['legacy_total_count']==16
    compact.save_decisions(user,row.public_id,row.revision,{'accept_legacy_totals':'yes'});db.session.commit()
    assert row.review_json['rows'][1]['basis_amount']=='100'
    assert row.review_json['rows'][1]['basis_interpretation']['status']=='proposed'
    compact.save_decisions(user,row.public_id,row.revision,{'r1_interpretation':'explicit_basis'});db.session.commit()
    assert compact.overview(row)['records'][1]['state']=='ready'
    from types import SimpleNamespace
    from app.services.nutrition_import_reprocess import carry_decisions
    old=SimpleNamespace(review_json=copy.deepcopy(row.review_json))
    fresh=SimpleNamespace(review_json=copy.deepcopy(row.review_json))
    old.review_json['rows'][1]['declaration']={}
    carry_decisions(old,fresh)
    assert fresh.review_json['rows'][1]['declaration']=={}


@pytest.mark.parametrize('note',['QA: valores por 100 g','QA: macros expresados por porción'])
def test_source_note_conflicting_with_daily_contract_requires_conscious_choice(app,user,note):
    doc=json.loads(FIXTURE.read_bytes());doc['data']['meals'][0]['items'][1]['notes']=note
    row=start(app,user,json.dumps(doc).encode())
    assert row.review_json['rows'][1]['basis_interpretation']['kind']=='contradictory_basis'
    compact.save_decisions(user,row.public_id,row.revision,{'accept_legacy_totals':'yes'});db.session.commit()
    assert compact.overview(row)['records'][1]['state']=='decision'


def test_equivalent_explicit_numeric_basis_is_not_a_false_conflict(app,user):
    doc=json.loads(FIXTURE.read_bytes());item=doc['data']['meals'][0]['items'][0]
    item.update(basis_amount='100.00',basis_unit='G')
    row=start(app,user,json.dumps(doc).encode())
    assert row.review_json['rows'][0]['basis_interpretation']['status']=='explicit'
    assert compact.overview(row)['records'][0]['state']=='ready'
