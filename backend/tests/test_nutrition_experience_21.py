"""Fictional owner-isolated QA: extraction, review, consumption and portability."""
import copy
import io
import json
import zipfile
from datetime import date,timedelta
from decimal import Decimal
from pathlib import Path
import pytest
from app.extensions import db
from app.models import User,DailyNutrition,DailyEnergy,FoodProduct,NutritionPlan,NutritionImportReceipt,MealLog,NutritionItem
from app.services import nutrition_import as imports,nutrition_intelligence as ni,food_catalog as catalog
from app.services.nutrition_math import NutritionError
from app.services.importers.nutrition_sources import extract
from app.services.importers.standard_import_executor import StandardImportExecutor
from tests.test_nutrition_intelligence import enabled,food,ready
from tests.conftest import login

FIXTURES=Path(__file__).resolve().parents[2]/'examples/nutrition-2-1/fixtures'


def reviewed(user,ref,destination='plan',file='compound-macros.json'):
    row=imports.start(user,(FIXTURES/file).read_bytes(),file)
    review=copy.deepcopy(row.review_json);review['destination']=destination
    for item in review['rows']:
        item.update(confirmed=True,meal_type='lunch',date=item.get('date') or '2026-10-05',
            ingredients=[{'ref':ref,'food_revision':'1','amount':'220','unit':'g'}])
    row.review_json=review;db.session.commit();return row


def commit(row,user):
    document=imports.canonical(row)
    result=StandardImportExecutor().commit_documents([document],user_id=user,target_type='nutrition_import',confirmed=True)
    assert result['committed'],result
    return document,result


@pytest.mark.parametrize('name',[p.name for p in FIXTURES.iterdir() if p.name!='manifest.json'])
def test_real_representative_fixture_extraction(app,name):
    result=extract((FIXTURES/name).read_bytes(),'misleading.bin','application/octet-stream')
    assert result['rows'] and result['signature_detected']
    assert all(row['confirmed'] is False for row in result['rows'])
    assert all('sha256' in row['evidence'] for row in result['rows'])
    if name.startswith('label'):
        row=result['rows'][0]
        assert row['basis_amount']=='100' and row['basis_unit']=='ml'
        assert row['amount']=='250' and row['unit']=='ml'
        assert row['declaration']['carbohydrate_total']['value']=='7'
        assert 'vitamin_a_rae' not in row['declaration']
    if name.startswith('diet-') or name.startswith('prescribed'):
        assert result['classification_hint']=='plan'


def test_extractor_never_silently_truncates_or_accepts_zip_traversal(app):
    with pytest.raises(NutritionError):extract(json.dumps([{'name':'QA'}]*251).encode(),'too-many.json')
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w') as archive:archive.writestr('../private.json','{}')
    with pytest.raises(NutritionError):extract(buffer.getvalue(),'QA.zip')
    with pytest.raises(NutritionError):extract(b'\x00binary','QA.csv')


def test_prescribed_plan_does_not_consume_then_explicit_consumption(app,user,enabled):
    row=reviewed(user,enabled);document,result=commit(row,user)
    assert db.session.query(NutritionPlan).count()==1
    from app.models import UploadedFile
    assert db.session.query(UploadedFile).one().import_status=='imported'
    assert db.session.query(DailyNutrition).count()==db.session.query(MealLog).count()==0
    plan=db.session.query(NutritionPlan).one()
    draft=imports.use_plan(user,plan.public_id,0,'2026-10-07')
    assert ni.pending(draft)==1
    draft=ni.mutate_draft(user,draft.public_id,draft.revision,'accept',{'index':0})
    log,_=ni.confirm(user,ni.confirmation_token(draft));db.session.commit()
    assert Decimal(log.snapshot_json['summary']['energy']['value'])==450
    assert Decimal(log.snapshot_json['summary']['protein']['value'])==35
    assert Decimal(log.snapshot_json['composition_summary']['energy']['value'])==363
    assert log.snapshot_json['summary']['vitamin_d']['state']=='partial'
    assert abs(Decimal(log.snapshot_json['summary']['vitamin_d']['coverage'])-Decimal(220)/300*100)<Decimal('1e-24')
    assert ni.daily_summary(user,date(2026,10,7))['summary']['energy']['value']=='450'
    assert db.session.query(NutritionItem).count()==1


def test_consumed_idempotency_changed_review_conflict_snapshot_and_repeat(app,user,enabled):
    row=reviewed(user,enabled,'consumed');document,_=commit(row,user)
    duplicate=StandardImportExecutor().commit_documents([document],user_id=user,target_type='nutrition_import',confirmed=True)
    assert duplicate['skips']==1 and db.session.query(MealLog).count()==1
    changed=copy.deepcopy(document);changed['data']['entries'][0]['name']='QA changed'
    assert StandardImportExecutor().plan_documents([changed],user_id=user,target_type='nutrition_import')['conflicts']==1
    log=db.session.query(MealLog).one();before=copy.deepcopy(log.snapshot_json)
    draft=ni.repeat(user,log.public_id,'2026-10-08')
    ni.mutate_draft(user,draft.public_id,draft.revision,'portion',{'portion_factor':'0.5'})
    assert Decimal(draft.snapshot_json['summary']['energy']['value'])==225
    assert Decimal(draft.snapshot_json['ingredients'][0]['amount'])==110
    assert log.snapshot_json==before


def test_duplicate_bytes_with_another_filename_are_omitted(app,user,enabled):
    first=reviewed(user,enabled);commit(first,user)
    duplicate=reviewed(user,enabled,file='duplicate.json')
    document=imports.canonical(duplicate)
    assert StandardImportExecutor().plan_documents([document],user_id=user,target_type='nutrition_import')['skips']==1


def test_partial_composition_not_confirmed_complete(app,user,enabled):
    row=reviewed(user,enabled);review=copy.deepcopy(row.review_json);review['rows'][0]['composition_complete']=True;row.review_json=review
    document=imports.canonical(row)
    with pytest.raises(NutritionError):imports.validate_document(document,user)
    assert db.session.query(NutritionPlan).count()==0


def test_private_volume_label_no_density_no_invented_zero(app,user,enabled):
    row=imports.start(user,(FIXTURES/'label.png').read_bytes(),'label.png');db.session.commit()
    row=imports.update(user,row.public_id,row.revision,'private',{'index':0})
    row=imports.update(user,row.public_id,row.revision,'confirm',{'index':0});db.session.commit()
    commit(row,user)
    product=db.session.query(FoodProduct).one();detail=catalog.detail(user,'user:'+product.public_id)
    assert detail['basis_amount']=='100' and detail['basis_unit']=='ml'
    assert product.calories_per_100g is None
    assert detail['nutrients'].get('vitamin_d') is None
    assert detail['density_g_ml'] is None


def test_review_conflict_ownership_date_conflict_flag(app,user,enabled):
    row=reviewed(user,enabled,'consumed')
    with pytest.raises(NutritionError):imports.owned(user+1,row.public_id)
    with pytest.raises(NutritionError):imports.update(user,row.public_id,row.revision-1,'skip',{'index':0})
    db.session.add(DailyNutrition(user_id=user,date=date(2026,10,5),source='qa',calories=100));db.session.commit()
    with pytest.raises(NutritionError):imports.validate_document(imports.canonical(row),user)
    app.config['NUTRITION_INTELLIGENCE_ENABLED']=False
    with pytest.raises(NutritionError):imports.start(user,b'{}','QA.json')


def test_atomic_rollback_audit_if_second_write_fails(app,user,enabled,monkeypatch):
    row=reviewed(user,enabled,'consumed');document=imports.canonical(row)
    document['data']['entries'].append(copy.deepcopy(document['data']['entries'][0]))
    original=ni.confirm;calls=[]
    def fail_second(*args,**kwargs):
        calls.append(1)
        if len(calls)==2:raise RuntimeError('QA induced failure')
        return original(*args,**kwargs)
    monkeypatch.setattr(ni,'confirm',fail_second)
    result=StandardImportExecutor().commit_documents([document],user_id=user,target_type='nutrition_import',confirmed=True)
    assert result['rollback'] and not result['committed']
    assert db.session.query(MealLog).count()==db.session.query(NutritionImportReceipt).count()==0


def test_thirty_day_history_mixed_empty_today_unknown_and_partial(app,user,enabled):
    from app.services.nutrition_history import history
    for i in range(30):
        target=date(2026,9,1)+timedelta(days=i)
        if i%3==0:
            db.session.add(DailyNutrition(user_id=user,date=target,source='qa',calories=1000+i,protein_g=30,total_carbs_g=50))
        else:
            draft=ready(user,enabled,target.isoformat());ni.confirm(user,ni.confirmation_token(draft))
        db.session.add(DailyEnergy(user_id=user,date=target,source='qa',total_calories=2000))
    db.session.commit()
    result=history(user,date(2026,10,13),30)
    assert result['day'] is None and result['recent'] and result['latest']==date(2026,9,30)
    assert len(result['points'])==30 and result['points'][-1]['balance'] is None
    assert result['points'][-1]['values']['calories'] is None


def test_functional_flask_history_import_library_templates(app,client,user,enabled):
    login(client)
    for path in ['/nutrition/','/nutrition/?period=90','/nutrition/import','/nutrition/library','/nutrition/foods?q=QA','/nutrition/my-food']:
        response=client.get(path)
        assert response.status_code==200,(path,response.status_code)
    row=reviewed(user,enabled)
    response=client.get('/nutrition/import/'+row.public_id+'?step=4')
    assert response.status_code==200 and 'Confirmar y guardar'.encode() in response.data


def test_plan_and_receipt_official_json_restore(app,user,enabled):
    from app.services.exporters.user_data import build_user_data_document
    from app.services.account_restore import AccountRestoreService
    from app.services.nutrition_portability import export_bundle
    row=reviewed(user,enabled);commit(row,user)
    bundle=export_bundle(user);assert bundle['schema_version']=='2.1' and len(bundle['plans'])==1
    target=User(username='QA-21-restore',role='user');target.set_password('QA fictional password');db.session.add(target);db.session.commit()
    payload=build_user_data_document(db.session.get(User,user),user)
    service=AccountRestoreService();preview=service.preview(payload,user_id=target.id)
    result=service.commit(payload,user_id=target.id,confirmation_token=preview['confirmation_token'])
    assert result['committed'],result
    restored=export_bundle(target.id)
    assert restored['plans'][0]['snapshot']['meals'][0]['snapshot']==bundle['plans'][0]['snapshot']['meals'][0]['snapshot']
    assert restored['receipts'][0]['document']['user_id']==target.id
    assert db.session.query(DailyNutrition).filter_by(user_id=target.id).count()==0


def test_recipe_dual_provenance_yield_and_edit_preserves_consumed_snapshot(app,user,enabled):
    row=reviewed(user,enabled,'consumed');commit(row,user)
    log=db.session.query(MealLog).one();frozen=copy.deepcopy(log.snapshot_json)
    draft=ni.repeat(user,log.public_id,'2026-10-08')
    ni.mutate_draft(user,draft.public_id,draft.revision,'accept',{'index':0})
    recipe=ni.save_template(user,draft.public_id,draft.revision);db.session.commit()
    assert recipe.totals()['calories']==450 and recipe.yield_weight_g==300
    assert recipe.per_100g()['calories']==150
    editing=ni.template_draft(user,recipe.public_id,'2026-10-09')
    ni.mutate_draft(user,editing.public_id,editing.revision,'amount',{'index':0,'amount':'200','unit':'g'})
    ni.mutate_draft(user,editing.public_id,editing.revision,'accept',{'index':0})
    ni.save_template(user,editing.public_id,editing.revision,recipe_key=recipe.public_id,base_revision=recipe.revision);db.session.commit()
    assert recipe.revision==2 and recipe.totals()['calories']==450
    assert log.snapshot_json==frozen


def test_plan_revision_edit_and_stale_conflict_after_consumption(app,user,enabled):
    row=reviewed(user,enabled);commit(row,user)
    plan=db.session.query(NutritionPlan).one();draft=imports.use_plan(user,plan.public_id,0,'2026-10-08')
    ni.mutate_draft(user,draft.public_id,draft.revision,'accept',{'index':0});log,_=ni.confirm(user,ni.confirmation_token(draft));db.session.commit()
    frozen=copy.deepcopy(log.snapshot_json)
    first=imports.edit_plan(user,plan.public_id);second=imports.edit_plan(user,plan.public_id)
    for review in [first,second]:
        data=copy.deepcopy(review.review_json);data['rows'][0]['confirmed']=True;review.review_json=data
    data=copy.deepcopy(first.review_json);data['name']='QA revised plan';first.review_json=data;db.session.commit()
    commit(first,user)
    assert plan.revision==2 and log.snapshot_json==frozen
    assert StandardImportExecutor().plan_documents([imports.canonical(second)],user_id=user,target_type='nutrition_import')['conflicts']==1


def test_volume_declared_per_100ml_scales_explicit_serving_not_density(app,user,enabled):
    row=imports.start(user,(FIXTURES/'label.png').read_bytes(),'label.png');db.session.commit()
    imports.update(user,row.public_id,row.revision,'private',{'index':0})
    data=copy.deepcopy(row.review_json);data['destination']='consumed';data['rows'][0].update(confirmed=True,date='2026-10-08',meal_type='snack');row.review_json=data;db.session.commit()
    commit(row,user);log=db.session.query(MealLog).one()
    assert Decimal(log.snapshot_json['summary']['energy']['value'])==Decimal('112.5')
    assert log.snapshot_json['summary']['energy']['coverage'] is None
    assert log.snapshot_json['declared_nutrition']['provenance']['original_basis']['nutrients']['energy']['value']=='45'


def test_explicit_percentage_binding_requires_total_mass(app,user,enabled):
    row=reviewed(user,enabled);data=copy.deepcopy(row.review_json);data['rows'][0]['ingredients']=[];row.review_json=data;db.session.commit()
    with pytest.raises(NutritionError):imports.update(user,row.public_id,row.revision,'bind',{'index':0,'ref':enabled,'percent':'50','unit':'g'})
    data=copy.deepcopy(row.review_json);data['rows'][0]['total_mass_g']='300';row.review_json=data;db.session.commit()
    imports.update(user,row.public_id,row.revision,'bind',{'index':0,'ref':enabled,'percent':'50','unit':'g'})
    assert row.review_json['rows'][0]['ingredients'][0]['amount']=='150'


def test_external_public_lookup_consent_cache_bounds_no_database_write(app,user,monkeypatch):
    from app.services.nutrition_sources import OpenFoodFactsLookup
    calls=[]
    response={'status':1,'product':{'code':'0000000000001','product_name':'QA public fixture','nutrition_data_per':'100ml','nutriments':{'energy-kcal_100g':45,'sodium_100g':.03}}}
    class Opener:
        def open(self,request,timeout):
            calls.append(request.full_url);return io.BytesIO(json.dumps(response).encode())
    monkeypatch.setattr('app.services.nutrition_sources.urllib.request.build_opener',lambda *args:Opener())
    lookup=OpenFoodFactsLookup()
    with pytest.raises(NutritionError):lookup.lookup('0000000000001')
    result=lookup.lookup('0000000000001',consent=True)
    assert Decimal(result[0]['nutrients']['sodium']['value'])==30
    assert lookup.lookup('0000000000001',consent=True)==result and len(calls)==1
    assert db.session.query(FoodProduct).count()==0


def test_import_csrf_and_other_owner_review_hidden(app,client,user,enabled):
    login(client);row=reviewed(user,enabled)
    app.config['WTF_CSRF_ENABLED']=True
    assert client.post('/nutrition/import/'+row.public_id+'/change',data={'revision':row.revision,'action':'cancel'}).status_code==400
    other=User(username='QA other nutrition21',role='user');other.set_password('QA fictional other');db.session.add(other);db.session.commit()
    with client.session_transaction() as session:session['_user_id']=str(other.id)
    # The fixture keeps an outer app context across requests; clear its cached
    # login proxy so this simulates the fresh context of a real HTTP request.
    from flask import g
    g.pop('_login_user',None)
    assert client.get('/nutrition/import/'+row.public_id).status_code==404


def test_full_volume_product_edit_revision_historical_snapshot_and_legacy_guard(app,user,enabled):
    from app.services.mobile_health import patch_food,MobileSyncError
    row=imports.start(user,(FIXTURES/'label.png').read_bytes(),'label.png');db.session.commit()
    imports.update(user,row.public_id,row.revision,'private',{'index':0})
    data=copy.deepcopy(row.review_json);data['destination']='consumed';data['rows'][0].update(confirmed=True,date='2026-10-08',meal_type='snack');row.review_json=data;db.session.commit();commit(row,user)
    product=db.session.query(FoodProduct).one();log=db.session.query(MealLog).one();frozen=copy.deepcopy(log.snapshot_json)
    vector=copy.deepcopy(product.nutrition_json['nutrients']);vector['energy']['value']='50'
    definition={'public_id':product.public_id,'base_revision':product.revision,'name':product.name,'brand':product.brand,'basis_amount':'100','basis_unit':'ml','nutrients':vector,'barcode':'0000000000001'}
    catalog.save_personal_definition(user,definition);db.session.commit()
    assert product.revision==2 and product.nutrition_json['nutrients']['energy']['value']=='50'
    assert product.calories_per_100g is None and log.snapshot_json==frozen
    catalog.save_personal_definition(user,definition)  # exact confirmation replay
    with pytest.raises(MobileSyncError) as error:patch_food(user,product.public_id,{'base_revision':2,'calories_per_100g':'100'})
    assert error.value.status==422
    assert product.nutrition_json['basis_unit']=='ml'


def test_daily_aggregate_without_invented_food_name_keeps_micros(app,user,enabled):
    source={'schema_version':'1.0','record_type':'daily_nutrition','user_id':user,'source_type':'uploaded','data':{'date':'2026-10-05','calories_kcal':450,'protein_g':35}}
    row=imports.start(user,json.dumps(source).encode(),'QA daily.json');data=copy.deepcopy(row.review_json)
    data.update(destination='daily_aggregate');item=data['rows'][0];item.update(confirmed=True,basis_amount='1',basis_unit='portion')
    item['declaration']['iron']={'state':'known','value':'2.1','unit':'mg'};row.review_json=data;db.session.commit()
    document,result=commit(row,user)
    assert 'name' not in document['data']['entries'][0]
    assert ni.daily_summary(user,date(2026,10,5))['summary']['iron']['value']=='2.1'
    assert db.session.query(MealLog).count()==0


def test_untyped_carbohydrates_require_explicit_total_net_or_unknown(app,user,enabled):
    payload=json.dumps({'records':[{'name':'QA carbs ambiguity','amount':'100','unit':'g','kcal':120,'carbs':'10 g'}]}).encode()
    row=imports.start(user,payload,'QA ambiguous carbs.json');data=copy.deepcopy(row.review_json);data['destination']='plan'
    data['rows'][0].update(confirmed=True,meal_type='lunch',ingredients=[{'ref':enabled,'food_revision':'1','amount':'100','unit':'g'}]);row.review_json=data;db.session.commit()
    assert 'carbohydrate_total' not in row.review_json['rows'][0]['declaration']
    with pytest.raises(NutritionError,match='sin clasificar'):imports.canonical(row)
    imports.update(user,row.public_id,row.revision,'fields',{'index':0,'name':'QA carbs ambiguity','amount':'100','unit':'g','meal_type':'lunch','nutrient_energy':'120','carbohydrate_classification':'net'})
    imports.update(user,row.public_id,row.revision,'confirm',{'index':0});db.session.commit();document,_=commit(row,user)
    declaration=document['data']['entries'][0]['declaration']
    assert declaration['nutrients']['net_carbs']['value']=='10'
    assert 'carbohydrate_total' not in declaration['nutrients'] and declaration['original_values']['carbs']=='10 g'


def test_off_untyped_carbs_and_reference_percent_do_not_become_absolute_nutrients():
    from app.services.nutrition_sources import off_food
    result=off_food({'code':'0000000000001','product_name':'QA public percent','nutrition_data_per':'100g',
        'nutriments':{'carbohydrates_100g':7,'vitamin-c_100g':.01,'vitamin-c_unit':'% DV'}})
    assert 'carbohydrate_total' not in result['nutrients'] and 'vitamin_c' not in result['nutrients']
    assert result['provenance']['ambiguous_fields']['carbohydrates']['value']=='7'
    assert result['provenance']['ambiguous_fields']['vitamin_c']['classification']=='reference_basis_required'


def test_compound_known_mass_cannot_double_count_whole_dish_and_components(app,user,enabled):
    row=reviewed(user,enabled);data=copy.deepcopy(row.review_json)
    data['rows'][0]['ingredients']=[{'ref':enabled,'food_revision':'1','amount':'300','unit':'g'}]*2;row.review_json=data
    with pytest.raises(NutritionError,match='masa vinculada'):imports.validate_document(imports.canonical(row),user)


def test_partial_composition_without_declared_macros_is_not_invented_or_complete(app,user,enabled):
    payload=json.dumps({'records':[{'name':'QA partially linked dish','amount':'300','unit':'g','meal_type':'lunch'}]}).encode()
    row=imports.start(user,payload,'QA quantity only.json');data=copy.deepcopy(row.review_json);data['destination']='plan'
    data['rows'][0].update(confirmed=True,ingredients=[{'ref':enabled,'food_revision':'1','amount':'220','unit':'g'}]);row.review_json=data;db.session.commit()
    document,_=commit(row,user)
    assert document['data']['entries'][0]['declaration'] is None
    plan=db.session.query(NutritionPlan).one();snap=plan.snapshot_json['meals'][0]['snapshot']
    assert 'declared_nutrition' not in snap and snap['summary']['energy']['state']=='partial'
    assert Decimal(snap['summary']['energy']['value'])==363
    from app.services.nutrition_portability import export_bundle
    assert export_bundle(user)['plans'][0]['snapshot']['meals'][0]['snapshot']==snap


def test_web_private_product_create_and_edit_signed_confirmation(app,client,user,enabled):
    import re
    from html import unescape
    login(client)
    fields={'name':'QA web ml product','brand':'QA Demo','basis_amount':'100','basis_unit':'ml','energy':'45','protein':'1','carbohydrate_total':'7','fat':'1.5'}
    preview=client.post('/nutrition/my-food',data=fields);assert preview.status_code==200
    token=unescape(re.search(r'name="token" value="([^"]+)"',preview.text)[1])
    assert client.post('/nutrition/my-food',data={'token':token}).status_code==302
    product=db.session.query(FoodProduct).one();assert product.nutrition_json['basis_unit']=='ml'
    fields.update(energy='50',base_revision=product.revision)
    url='/nutrition/my-food/'+product.public_id
    preview=client.post(url,data=fields);assert preview.status_code==200
    token=unescape(re.search(r'name="token" value="([^"]+)"',preview.text)[1])
    assert client.post(url,data={'token':token}).status_code==302
    assert product.revision==2 and product.calories_per_100g is None
