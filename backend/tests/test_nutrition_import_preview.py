"""Issue #32: fictional cross-format preview, scoped editing and final snapshots."""
import copy
import io
import json
import re
import subprocess
import sys
import types
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import event

from app.extensions import db
from app.models import FoodProduct, MealLog, NutritionImportReceipt, User
from app.services import nutrition_import as imports, nutrition_import_review as review
from app.services.nutrition_import_reprocess import reprocess
from app.services.nutrition_math import NutritionError
from tests.conftest import login
from tests.test_nutrition_import_summary import token

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/nutrition'))
from qa_preview_fixtures import source, table


def start(app,user,document=None,payload=None,filename='QA fictional preview.json'):
    app.config['NUTRITION_INTELLIGENCE_ENABLED']=True
    row=imports.start(user,payload or json.dumps(document or source()).encode(),filename)
    db.session.commit()
    return row


def edit(row,user,index=0,**fields):
    result=review.save_decisions(user,row.public_id,row.revision,dict(edit_index=str(index),
        **{f'r{index}_'+key:value for key,value in fields.items()}))
    db.session.commit()
    return result


def test_clean_21_no_individual_forms_one_atomic_save(app,client,user):
    row=start(app,user);frozen=copy.deepcopy(row.review_json);login(client)
    page=client.get('/nutrition/import/'+row.public_id)
    assert page.status_code==200 and 'Revisar importación' in page.text
    assert page.text.count('class="ni-preview-record"')==21
    assert page.text.count('>Editar</a>')==21 and 'ni-row-edit-form' not in page.text
    assert '200 kcal' not in page.text.split('id="import-records"')[0]  # no competing hero/acceptance
    assert page.text.count('>Guardar todo</button>')==1
    assert page.text.index('id="batch-title"')<page.text.index('>Guardar todo</button>')
    assert not re.search(r'name="consent_consumed"[^>]*checked',page.text)
    view=review.overview(row)
    assert view['counts']==dict(ready=21,decision=0,invalid=0,omitted=0)
    assert Decimal(view['batch_summary']['energy']['value'])==4200
    assert all(record['preview']['protein']['value']=='10' for record in view['records'])
    assert row.review_json==frozen
    signed=token(client,row);values=dict(revision=row.revision,token=signed,consent_consumed='yes')
    assert client.post('/nutrition/import/'+row.public_id+'/confirm',data=values).status_code==200
    assert db.session.query(MealLog).count()==21 and db.session.query(FoodProduct).count()==0
    assert db.session.query(NutritionImportReceipt).count()==1
    assert client.post('/nutrition/import/'+row.public_id+'/confirm',data=values).status_code==200
    assert db.session.query(MealLog).count()==21


def test_one_error_51_fix_only_one_row_totals_and_snapshots(app,client,user):
    row=start(app,user,source(51,True));login(client)
    frozen=copy.deepcopy(row.review_json)
    view=review.overview(row)
    assert view['counts']==dict(ready=50,decision=1,invalid=0,omitted=0)
    assert view['batch_summary']['energy']['state']=='partial'
    assert Decimal(view['batch_summary']['energy']['value'])==10000
    assert {r['index'] for r in view['records'] if r['issues']}=={25}
    page=client.get('/nutrition/import/'+row.public_id)
    assert page.text.count('>Corregir</a>')==1 and 'ni-row-edit-form' not in page.text
    edit(row,user,index=25,basis_amount='100',basis_unit='g',basis_verified='yes')
    assert all(old==new for i,(old,new) in enumerate(zip(frozen['rows'],row.review_json['rows'])) if i!=25)
    view=review.overview(row)
    assert view['counts']['ready']==51 and Decimal(view['batch_summary']['energy']['value'])==10200
    assert view['batch_summary']['energy']['state']=='complete'
    assert db.session.query(MealLog).count()==db.session.query(FoodProduct).count()==0
    signed=token(client,row)
    assert client.post('/nutrition/import/'+row.public_id+'/confirm',data=dict(revision=row.revision,token=signed,consent_consumed='yes')).status_code==200
    assert db.session.query(MealLog).count()==51 and db.session.query(NutritionImportReceipt).count()==1
    log=db.session.query(MealLog).filter(MealLog.snapshot_json['name'].as_string()=='QA alimento ficticio 26').one()
    assert Decimal(log.snapshot_json['summary']['energy']['value'])==200
    assert log.snapshot_json['declared_nutrition']['original_values']==frozen['rows'][25]['original']
    assert log.snapshot_json['declared_nutrition']['provenance']['corrections']
    from app.services.exporters.user_data import build_user_data_document
    from app.services.account_restore import AccountRestoreService
    from app.services.nutrition_portability import export_bundle,semantic_snapshot
    from app.models import DailyNutrition
    assert len(db.session.query(DailyNutrition).one().meals)==2
    target=User(username='QA Issue32 restore 51',role='user');target.set_password('fictional restore password')
    db.session.add(target);db.session.commit()
    payload=build_user_data_document(db.session.get(User,user),user)
    service=AccountRestoreService();plan=service.preview(payload,user_id=target.id)
    assert service.commit(payload,user_id=target.id,confirmation_token=plan['confirmation_token'])['committed']
    assert [semantic_snapshot(r['snapshot']) for r in export_bundle(target.id)['logs']]==[
        semantic_snapshot(r['snapshot']) for r in export_bundle(user)['logs']]


def test_voluntary_amount_macro_cancel_exact_and_others_unchanged(app,client,user):
    row=start(app,user);login(client);frozen=copy.deepcopy(row.review_json)
    path='/nutrition/import/'+row.public_id
    old_signed=token(client,row);old_revision=row.revision
    assert 'ni-row-edit-form' in client.get(path+'?edit=0&panel=quantity').text
    edit(row,user,amount='150')
    assert client.post(path+'/confirm',data=dict(revision=old_revision,token=old_signed,consent_consumed='yes')).status_code==409
    view=review.overview(row)
    assert Decimal(view['records'][0]['preview']['energy']['value'])==300
    edit(row,user,contribution_protein='11')
    assert Decimal(review.overview(row)['records'][0]['preview']['protein']['value'])==11
    edit(row,user,amount='75')
    view=review.overview(row)
    assert Decimal(view['records'][0]['preview']['protein']['value'])==Decimal('5.5')
    assert Decimal(view['records'][0]['preview']['energy']['value'])==150
    after=copy.deepcopy(row.review_json);rev=row.revision
    # Opening a different editor and cancelling is entirely read-only.
    assert client.get(path+'?edit=1&panel=nutrition').status_code==200
    assert client.get(path+'#record-1').status_code==200
    assert row.review_json==after and row.revision==rev
    assert row.review_json['rows'][1:]==frozen['rows'][1:]
    assert row.review_json['rows'][0]['original']==frozen['rows'][0]['original']
    assert db.session.query(MealLog).count()==db.session.query(FoodProduct).count()==0
    assert not any(r['issues'] for r in review.overview(row)['records']), [(r['index'],r['issues']) for r in review.overview(row)['records'] if r['issues']]
    assert client.post(path+'/confirm',data=dict(revision=row.revision,token=token(client,row),consent_consumed='yes')).status_code==200
    log=db.session.query(MealLog).order_by(MealLog.id).first()
    assert Decimal(log.snapshot_json['summary']['protein']['value'])==Decimal('5.5')
    assert Decimal(log.snapshot_json['summary']['energy']['value'])==150


@pytest.mark.parametrize('fmt',['csv','tsv','xlsx','text','json21'])
def test_same_common_preview_across_formats(app,user,fmt):
    document=source()
    if fmt=='json21':
        first=start(app,user,document)
        payload=json.dumps(review.document(first)).encode()
    elif fmt=='xlsx':
        from openpyxl import Workbook
        workbook=Workbook();sheet=workbook.active;rows=document['records']
        sheet.append(list(rows[0]));[sheet.append(list(row.values())) for row in rows]
        output=io.BytesIO();workbook.save(output);payload=output.getvalue()
    else:payload=table(document,'\t' if fmt=='tsv' else '|' if fmt=='text' else ',')
    row=start(app,user,payload=payload,filename='QA fictional.'+fmt)
    if row.review_json['destination']!='consumed':
        review.save_decisions(user,row.public_id,row.revision,dict(destination='consumed'));db.session.commit()
    view=review.overview(row)
    assert view['counts']==dict(ready=21,decision=0,invalid=0,omitted=0)
    assert Decimal(view['batch_summary']['energy']['value'])==4200
    assert all(record['preview']['protein']['value']=='10' for record in view['records'])


def test_unknown_estimated_trace_zero_and_no_unit_invention(app,user):
    data=source(4)
    data['records'][0]['quality']='estimated'
    data['records'][1].pop('protein_g')
    data['records'][2]['nutrients']={'vitamin_d':dict(state='known',value='0',unit='ug'),
        'zinc':dict(state='trace',value=None,unit='mg')}
    data['records'][3]['protein_g']='20 %'
    row=start(app,user,data);view=review.overview(row)
    assert view['counts']['ready']==3 and view['counts']['decision']==1
    assert view['records'][0]['quality']=='Estimado'
    assert 'estimated_source_declaration' in view['records'][0]['preview']['energy']['sources']
    assert view['records'][1]['preview']['protein']['value'] is None
    assert view['records'][2]['preview']['vitamin_d']['value']=='0'
    assert view['records'][2]['preview']['zinc']['value'] is None
    assert view['batch_summary']['protein']['state']=='partial'


def test_sufficient_declaration_does_not_require_partial_composition(app,user):
    data=source(1);data['records'][0]['ingredients']=[{'name':'QA unknown optional component','amount':'25','unit':'g'}]
    row=start(app,user,data)
    view=review.overview(row)
    assert view['counts']['ready']==1 and view['records'][0]['item']['resolution']=='declared'
    assert review.document(row)['data']['entries'][0]['bindings']==[]


def test_changing_products_to_consumed_does_not_force_product_creation(app,user):
    data=source(1);data['destination']='products'
    row=start(app,user,data)
    assert review.overview(row)['counts']['ready']==1
    review.save_decisions(user,row.public_id,row.revision,dict(destination='consumed'));db.session.commit()
    document=review.document(row)
    assert document['data']['entries'][0]['bindings']==[]
    assert review.overview(row)['counts']['ready']==1
    assert db.session.query(FoodProduct).count()==0


def test_contextual_base_values_preserve_zero_and_valid_nutrient_provenance(app,user):
    row=start(app,user,source(1));fiber=copy.deepcopy(row.review_json['rows'][0]['declaration']['fiber'])
    edit(row,user,declared_fiber='0',declared_protein='12')
    assert row.review_json['rows'][0]['declaration']['fiber']==fiber
    assert review.document(row)['data']['entries'][0]['declaration']['nutrients']['protein']['value']=='12'


def test_v3_same_clean_file_requires_extra_technical_acceptance(app,user):
    app.config['NUTRITION_INTELLIGENCE_ENABLED']=True
    sha='c9cbb86b7b558d6b8c1e838e64966e2a48700bd9';modules={}
    for name,path in [('parser','backend/app/services/importers/nutrition_sources.py'),('service','backend/app/services/nutrition_import.py'),('review','backend/app/services/nutrition_import_review.py')]:
        code=subprocess.check_output(['git','show',sha+':'+path],cwd=ROOT)
        module=types.ModuleType('qa_baseline_'+name);exec(compile(code,sha+'/'+path,'exec'),module.__dict__);modules[name]=module
    service=modules['service'];service.extract=modules['parser'].extract;service.EXTRACTOR_VERSION=modules['parser'].EXTRACTOR_VERSION
    baseline=modules['review'];baseline.imports=service
    old=service.start(user,json.dumps(source()).encode(),'QA exact31 baseline.json');db.session.commit()
    assert baseline.overview(old)['counts']==dict(ready=0,decision=21,invalid=0,omitted=0)
    baseline.save_decisions(user,old.public_id,old.revision,dict(use_declarations='yes'));db.session.commit()
    assert baseline.overview(old)['counts']['ready']==21


def test_inline_owner_csrf_stale_expiry_and_get_no_writes(app,client,user):
    row=start(app,user);login(client);path='/nutrition/import/'+row.public_id
    def guard(conn,cursor,stmt,params,context,many):
        assert stmt.lstrip().split()[0].upper() not in {'INSERT','UPDATE','DELETE','REPLACE','CREATE','ALTER','DROP'}
    event.listen(db.engine,'before_cursor_execute',guard)
    try:
        for panel in ['quantity','nutrition','identity','date','basis','catalog','correction']:
            response=client.get(path+'?edit=0&panel='+panel)
            assert response.status_code==200 and response.headers['Cache-Control']=='private, no-store'
    finally:event.remove(db.engine,'before_cursor_execute',guard)
    app.config['WTF_CSRF_ENABLED']=True
    assert client.post(path+'/decisions',data=dict(revision=row.revision,edit_index='0',r0_amount='200')).status_code==400
    app.config['WTF_CSRF_ENABLED']=False
    oldrev=row.revision;edit(row,user,amount='200')
    assert client.post(path+'/decisions',data=dict(revision=oldrev,edit_index='0',r0_amount='300')).status_code==409
    other=User(username='QA second preview owner',role='user');other.set_password('QA-only fictional password')
    db.session.add(other);db.session.commit()
    with client.session_transaction() as session:session['_user_id']=str(other.id)
    from flask import g
    g.pop('_login_user',None)
    assert client.get(path+'?edit=0').status_code==404
    assert client.post(path+'/decisions',data=dict(revision=row.revision,edit_index='0',r0_amount='300',user_id=user)).status_code==404
    row.created_at-=timedelta(days=2);db.session.commit()
    with pytest.raises(NutritionError):edit(row,user,amount='300')
    assert db.session.query(MealLog).count()==0


def test_invalid_inline_input_stays_in_row_with_accessible_error(app,client,user):
    row=start(app,user);login(client);before=copy.deepcopy(row.review_json);revision=row.revision
    page=client.post('/nutrition/import/'+row.public_id+'/decisions',data=dict(
        revision=revision,edit_index='0',editor_panel='quantity',r0_amount='not a number',r0_unit='g'))
    assert page.status_code==422 and 'role="alert"' in page.text
    assert 'value="not a number"' in page.text and 'ni-row-edit-form' in page.text
    assert row.review_json==before and row.revision==revision
    assert db.session.query(MealLog).count()==db.session.query(FoodProduct).count()==0


def test_details_do_not_render_arbitrary_source_metadata(app,client,user):
    data=source(1);data['records'][0]['api_key']='QA_ONLY_NOT_A_REAL_KEY_DO_NOT_RENDER'
    row=start(app,user,data);login(client)
    page=client.get('/nutrition/import/'+row.public_id)
    assert page.status_code==200 and 'QA_ONLY_NOT_A_REAL_KEY_DO_NOT_RENDER' not in page.text
    assert row.review_json['rows'][0]['original']['api_key']=='QA_ONLY_NOT_A_REAL_KEY_DO_NOT_RENDER'


def test_name_brand_date_and_meal_survive_canonical_reupload(app,user):
    row=start(app,user,source(1))
    edit(row,user,name='QA revised identity',brand='QA revised brand',date='2026-01-16',meal_type='dinner')
    document=review.document(row)
    entry=document['data']['entries'][0]
    assert entry['name']=='QA revised identity' and entry['date']=='2026-01-16' and entry['meal_type']=='dinner'
    assert entry['declaration']['provenance']['display_brand']=='QA revised brand'
    again=start(app,user,payload=json.dumps(document).encode(),filename='QA reupload21.json')
    assert again.review_json['rows'][0]['brand']=='QA revised brand'


def test_catalog_composition_amount_edit_recalculates_all_ratios(app,user):
    from app.services import food_catalog as catalog
    fixtures=ROOT/'examples/qa/nutrition-import-ux'
    app.config['NUTRITION_INTELLIGENCE_ENABLED']=True
    catalog.stage(json.loads((fixtures/'catalog.json').read_text(encoding='utf-8')))
    catalog.activate('qa_import_ux','1',1);db.session.commit()
    source_doc=json.loads((fixtures/'mixed-13.json').read_bytes())
    source_doc['plan']=source_doc['plan'][:1]
    row=start(app,user,source_doc)
    initial=review.overview(row)['records'][0]
    original=initial['preview'];original_bindings=copy.deepcopy(initial['item']['ingredients'])
    item=row.review_json['rows'][0]
    # The whole preparation's amount is explicit in this source.
    assert item.get('amount')
    edit(row,user,amount=str(Decimal(item['amount'])*2))
    preview=review.overview(row)['records'][0]['preview']
    assert Decimal(preview['energy']['value'])==Decimal(original['energy']['value'])*2
    assert preview['iron']['value'] is original['iron']['value'] is None
    updated=review.overview(row)['records'][0]['item']['ingredients']
    assert len(updated)==len(original_bindings)
    assert all(Decimal(new['amount'])==Decimal(old['amount'])*2 for old,new in zip(original_bindings,updated))


def test_inline_quantity_keeps_verified_original_total_basis(app,user):
    from tests.test_nutrition_import_legacy_semantics import resolve
    payload=(ROOT/'examples/qa/nutrition-import-ux/legacy-daily-semantic-21.json').read_bytes()
    row=start(app,user,payload=payload);resolve(row,user)
    before=copy.deepcopy(row.review_json);old=review.overview(row)['records'][1]['preview']
    edit(row,user,index=1,amount=str(Decimal(before['rows'][1]['amount'])*2))
    state=review.overview(row)
    assert state['counts']['ready']==21
    assert Decimal(state['records'][1]['preview']['energy']['value'])==Decimal(old['energy']['value'])*2
    assert row.review_json['rows'][:1]==before['rows'][:1] and row.review_json['rows'][2:]==before['rows'][2:]


@pytest.mark.parametrize('sha',['1cf8d830ba801a8c8121cf594b07a0269a6d6e6f','12bad71a60b96b57d282cfaf745fc0dc4ed27ab6','c9cbb86b7b558d6b8c1e838e64966e2a48700bd9'])
@pytest.mark.parametrize('expired',[False,True])
def test_actual_29_30_31_reprocess_keeps_original_and_decisions(app,user,sha,expired):
    app.config['NUTRITION_INTELLIGENCE_ENABLED']=True
    modules={}
    for name,path in [('parser','backend/app/services/importers/nutrition_sources.py'),('service','backend/app/services/nutrition_import.py')]:
        code=subprocess.check_output(['git','show',sha+':'+path],cwd=ROOT)
        module=types.ModuleType('qa_'+name);exec(compile(code,sha+'/'+path,'exec'),module.__dict__);modules[name]=module
    service=modules['service'];service.extract=modules['parser'].extract
    service.EXTRACTOR_VERSION=getattr(modules['parser'],'EXTRACTOR_VERSION','nutrition-import-v1')
    old=service.start(user,json.dumps(source()).encode(),'QA actual predecessor.json')
    service.update(user,old.public_id,old.revision,'fields',dict(index='0',_section='identity',name='QA prior corrected name',date='2026-01-15',meal_type='breakfast'))
    if expired:old.created_at-=timedelta(days=2)
    db.session.commit();frozen=copy.deepcopy(old.review_json);original_sha=old.source_sha256
    fresh=reprocess(user,old.public_id,old.revision);db.session.commit()
    assert old.review_json==frozen and fresh.source_sha256==original_sha
    assert fresh.review_json['rows'][0]['name']=='QA prior corrected name'
    assert fresh.source_json['reprocess_pending']
    edit(fresh,user,index=1,name='QA later corrected name')
    assert reprocess(user,old.public_id,old.revision).id==fresh.id
    assert fresh.review_json['rows'][1]['name']=='QA later corrected name'
    assert old.review_json==frozen and db.session.query(MealLog).count()==0
