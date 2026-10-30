"""Representative fictional 21 consumptions; catalog IDs are optional."""
import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.extensions import db
from app.models import MealLog, FoodProduct, DailyNutrition, NutritionImportReceipt
from app.services import food_catalog as catalog, nutrition_import as imports, nutrition_import_review as compact
from app.services.nutrition_math import NutritionError
from tests.conftest import login
from tests.test_nutrition_import_summary import token

FIXTURES = Path(__file__).resolve().parents[2] / 'examples/qa/nutrition-import-ux'


@pytest.fixture
def consumed(app, user):
    app.config['NUTRITION_INTELLIGENCE_ENABLED'] = True
    catalog.stage(json.loads((FIXTURES/'consumed-catalog.json').read_text(encoding='utf-8')))
    catalog.activate('qa_import_consumed','1',1)
    db.session.commit()
    row=imports.start(user,(FIXTURES/'consumed-21.json').read_bytes(),'QA consumed-21.json')
    db.session.commit()
    return row


def resolve(row,user,private=False):
    values={'use_declarations':'yes'}
    for i in [4,5,6,7,8]:values[f'r{i}_equivalence_confirmed']='yes'
    if private:values['r6_resolution']='private'
    compact.save_decisions(user,row.public_id,row.revision,values)
    db.session.commit()


def test_21_save_correct_totals_no_products_replay(app,client,user,consumed):
    row=consumed
    assert compact.overview(row)['counts']==dict(ready=16,decision=5,invalid=0,omitted=0)
    resolve(row,user)
    view=compact.overview(row)
    assert view['counts']['ready']==21, [(r['index'],r['issues']) for r in view['records'] if r['issues']]
    document=compact.document(row)
    assert len(document['data']['entries'])==21
    expected=sum((Decimal(e['declaration']['nutrients']['energy']['value'])*Decimal(e['portion_amount'])/Decimal(e['declaration']['basis_amount']) for e in document['data']['entries']),Decimal(0))
    login(client)
    signed=token(client,row)
    assert signed
    data={'revision':row.revision,'token':signed,'consent_consumed':'yes'}
    response=client.post('/nutrition/import/'+row.public_id+'/confirm',data=data)
    assert response.status_code==200, response.text[-3000:]
    logs=db.session.query(MealLog).filter_by(user_id=user).all()
    assert len(logs)==21
    assert db.session.query(FoodProduct).count()==0
    assert sum(Decimal(l.snapshot_json['summary']['energy']['value']) for l in logs)==expected
    assert Decimal(db.session.query(DailyNutrition).one().calories)==expected.quantize(Decimal('.001'))
    byname={l.snapshot_json['name']:l.snapshot_json for l in logs}
    assert byname['QA cereal porciones sin masa']['summary']['energy']['value']=='163.5'
    assert byname['QA cereal porciones sin masa']['summary']['energy']['total_weight'] is None
    assert Decimal(byname['QA bebida en dos latas Marca Inventada']['summary']['energy']['value'])==Decimal('993.3')
    assert byname['QA queso panela']['declared_nutrition']['nutrients']['iron']['state']=='trace'
    assert byname['QA queso panela']['declared_nutrition']['nutrients']['sodium']['state']=='below_limit'
    assert byname['QA queso panela']['summary']['vitamin_d']['value']=='0'
    assert byname['QA salsa casera']['summary']['vitamin_c']['value'] is None
    assert client.post('/nutrition/import/'+row.public_id+'/confirm',data=data).status_code==200
    assert db.session.query(MealLog).count()==21 and db.session.query(NutritionImportReceipt).count()==1
    from sqlalchemy import event
    def no_writes(conn,cursor,stmt,params,context,many):
        assert stmt.lstrip().split()[0].upper() not in {'INSERT','UPDATE','DELETE','REPLACE','CREATE','ALTER','DROP','TRUNCATE'}
    event.listen(db.engine,'before_cursor_execute',no_writes)
    try:
        paths=['/nutrition/?date=2026-10-26','/nutrition/library','/dashboard?as_of=2026-10-26','/energy?date=2026-10-26']
        paths += ['/nutrition/micronutrients?date=2026-10-26&period='+str(p) for p in [7,30,90]]
        paths += ['/nutrition/logs/'+l.public_id for l in logs]
        for url in paths:
            response=client.get(url)
            assert response.status_code==200,(url,response.status_code)
    finally:event.remove(db.engine,'before_cursor_execute',no_writes)



def test_contextual_private_created_only_on_confirmation(app,client,user,consumed):
    resolve(consumed,user,private=True)
    assert db.session.query(FoodProduct).count()==0
    assert compact.overview(consumed)['counts']['ready']==21
    login(client)
    response=client.post('/nutrition/import/'+consumed.public_id+'/confirm',data=dict(revision=consumed.revision,token=token(client,consumed),consent_consumed='yes'))
    assert response.status_code==200
    product=db.session.query(FoodProduct).one()
    assert product.name=='QA barra Amaranto MX' and product.nutrition_json['barcode']=='7500000000042'
    log=db.session.query(MealLog).filter(MealLog.snapshot_json['name'].as_string()==product.name).one()
    assert Decimal(log.snapshot_json['summary']['energy']['value'])==Decimal('47.7')  # 106 per 100g, 45g; no double count


def test_missing_conversion_and_basis_block_without_fabrication(app,user,consumed):
    compact.save_decisions(user,consumed.public_id,consumed.revision,{'use_declarations':'yes'})
    db.session.commit()
    assert compact.overview(consumed)['counts']['decision']==5
    with pytest.raises(NutritionError):compact.document(consumed)
    before=copy.deepcopy(consumed.review_json)
    with pytest.raises(NutritionError):compact.save_decisions(user,consumed.public_id,consumed.revision,{'r4_resolution':'declared'})
    db.session.rollback()
    assert consumed.review_json==before


def test_independent_queries_preserve_other_decisions(app,client,user,consumed):
    login(client)
    data={'revision':consumed.revision,'r1_p-1_query':'pollo nombre comercial largo QA','r2_p-1_query':'frijoles','r3_resolution':'declared'}
    assert client.post('/nutrition/import/'+consumed.public_id+'/decisions',data=data).status_code==302
    page=client.get('/nutrition/import/'+consumed.public_id)
    assert consumed.review_json['rows'][1]['search_query']=='pollo nombre comercial largo QA'
    assert consumed.review_json['rows'][2]['search_query']=='frijoles'
    page=client.get('/nutrition/import/'+consumed.public_id+'?edit=1&panel=catalog')
    assert 'name="r1_p-1_query" value="pollo nombre comercial largo QA"' in page.text
    assert consumed.review_json['rows'][3]['resolution']=='declared'
    hits=catalog.search(user,'pollo nombre comercial largo QA',progressive=True)
    assert any(hit['source_food_id']=='2' for hit in hits)


def test_existing_day_requires_explicit_batch_decision(app,client,user,consumed):
    from datetime import date
    day=DailyNutrition(user_id=user,date=date(2026,10,26),source='manual',calories=200)
    db.session.add(day);db.session.commit()
    resolve(consumed,user)
    assert compact.overview(consumed)['counts']['decision']==21
    with pytest.raises(NutritionError):compact.document(consumed)
    compact.save_decisions(user,consumed.public_id,consumed.revision,{'day_2026-10-26_conflict_action':'keep_and_add','day_2026-10-26_authority':'disjoint_aggregate'})
    db.session.commit()
    assert compact.overview(consumed)['counts']['ready']==21

    login(client)
    response=client.post('/nutrition/import/'+consumed.public_id+'/confirm',data=dict(revision=consumed.revision,token=token(client,consumed),consent_consumed='yes'))
    assert response.status_code==200
    db.session.refresh(day)
    assert day.authority_baseline_json['original_totals']['calories']=='200.000'
    assert day.authority=='disjoint_aggregate' and db.session.query(MealLog).count()==21


def test_declared_consumption_export_restore(app,client,user,consumed):
    from app.models import User
    from app.services.exporters.user_data import build_user_data_document
    from app.services.account_restore import AccountRestoreService
    from app.services.nutrition_portability import export_bundle
    resolve(consumed,user,private=True)
    login(client)
    response=client.post('/nutrition/import/'+consumed.public_id+'/confirm',data=dict(revision=consumed.revision,token=token(client,consumed),consent_consumed='yes'))
    assert response.status_code==200
    original=export_bundle(user)
    target=User(username='QA-21-declared-restore',role='user')
    target.set_password('QA fictional password')
    db.session.add(target);db.session.commit()
    payload=build_user_data_document(db.session.get(User,user),user)
    service=AccountRestoreService();preview=service.preview(payload,user_id=target.id)
    result=service.commit(payload,user_id=target.id,confirmation_token=preview['confirmation_token'])
    assert result['committed'],result
    restored=export_bundle(target.id)
    assert len(restored['logs'])==21
    from app.services.nutrition_portability import semantic_snapshot
    assert [semantic_snapshot(l['snapshot']) for l in restored['logs']]==[semantic_snapshot(l['snapshot']) for l in original['logs']]


def test_atomic_rollback_after_product_and_consumption(app,client,user,consumed):
    from unittest.mock import patch
    from app.services import nutrition_intelligence as ni
    resolve(consumed,user,private=True)
    login(client);signed=token(client,consumed)
    actual=ni.confirm
    def fail_after_flush(*args,**kwargs):
        result=actual(*args,**kwargs)
        if db.session.query(FoodProduct).count():raise NutritionError('QA induced failure after flush')
        return result
    with patch.object(ni,'confirm',side_effect=fail_after_flush):
        response=client.post('/nutrition/import/'+consumed.public_id+'/confirm',data=dict(revision=consumed.revision,token=signed,consent_consumed='yes'))
    assert response.status_code==409
    assert db.session.query(MealLog).count()==db.session.query(FoodProduct).count()==db.session.query(DailyNutrition).count()==0
    assert db.session.query(NutritionImportReceipt).count()==0
    assert consumed.state=='pending'


def test_consumed_get_owner_csrf_and_binding(app,client,user,consumed):
    from sqlalchemy import event
    from app.models import User
    from app.services.mobile_health import create_food
    stranger=User(username='QA-private-other',role='user');stranger.set_password('QA fictional password')
    db.session.add(stranger);db.session.flush()
    private=create_food(stranger.id,{'name':'QA marca solo otro dueño','brand':'QA secreta'})
    db.session.commit()
    assert all(h['ref']!='user:'+private.public_id for h in catalog.search(user,'QA marca solo otro dueño',progressive=True))
    login(client)
    def guard(conn,cursor,stmt,params,context,many):
        assert stmt.lstrip().split()[0].upper() not in {'INSERT','UPDATE','DELETE','REPLACE','CREATE','ALTER','DROP','TRUNCATE'}
    event.listen(db.engine,'before_cursor_execute',guard)
    try:
        for url in ['/nutrition/import/'+consumed.public_id,'/nutrition/import/'+consumed.public_id+'?r1_p-1_query=pollo&r2_p-1_query=frijol']:
            response=client.get(url)
            assert response.status_code==200 and response.headers['Cache-Control']=='private, no-store'
    finally:event.remove(db.engine,'before_cursor_execute',guard)
    assert client.post('/nutrition/import/'+consumed.public_id+'/decisions',data={'revision':consumed.revision,'r1_p-1_ref':'user:'+private.public_id,'r1_p-1_amount':'100','r1_p-1_unit':'g'}).status_code==404
    app.config['WTF_CSRF_ENABLED']=True
    assert client.post('/nutrition/import/'+consumed.public_id+'/decisions',data={'revision':consumed.revision,'use_declarations':'yes'}).status_code==400
    app.config['WTF_CSRF_ENABLED']=False
    hits=catalog.search(user,'pollo',progressive=True)
    selected=next(h for h in hits if h['source_food_id']=='2')
    compact.save_decisions(user,consumed.public_id,consumed.revision,{'r1_p-1_ref':selected['ref'],'r1_p-1_amount':'100','r1_p-1_unit':'g'})
    db.session.commit()
    assert compact.overview(consumed)['counts']['ready']==16


@pytest.mark.parametrize('amount,unit,label',[('1 botella','portion','botella'),('2 latas','portion','lata'),('1 barra','portion','barra'),('5 sobres','portion','sobre'),('1.5 porciones','portion','porcion'),('1 porcion','portion','porcion'),('2 servings','portion','porcion')])
def test_explicit_named_quantity_text(amount,unit,label):
    from app.services.importers.nutrition_sources import normalized_row
    row=normalized_row(dict(name='QA texto de porción',amount=amount),{'file':'QA synthetic'})
    assert row['unit']==unit and row['unit_label']==label
    assert 'Cantidad ilegible o ambigua.' not in row['warnings']
    assert 'equivalence' not in row


def test_bulk_keeps_selected_identity_and_private_duplicates_block(app,user,consumed):
    from app.services.mobile_health import create_food
    hits=catalog.search(user,'pollo',progressive=True)
    match=next(h for h in hits if h['source_food_id']=='2')
    values={'use_declarations':'yes','r1_p-1_ref':match['ref']+'|1','r1_p-1_amount':'100','r1_p-1_unit':'g',
            'r6_resolution':'private',**{f'r{i}_equivalence_confirmed':'yes' for i in [4,5,6,7,8]}}
    compact.save_decisions(user,consumed.public_id,consumed.revision,values);db.session.commit()
    assert consumed.review_json['rows'][1]['ingredients'][0]['ref']==match['ref']
    assert compact.overview(consumed)['counts']['ready']==21
    before=create_food(user,{'name':'QA barra Amaranto MX','brand':'Marca QA inventada 6'})
    db.session.commit();original=copy.deepcopy(before.nutrition_json)
    assert compact.overview(consumed)['counts']['decision']==1
    with pytest.raises(NutritionError):compact.document(consumed)
    assert before.nutrition_json==original


def test_private_search_accent_brand_and_barcode(app,user,consumed):
    from app.services.mobile_health import create_food
    product=create_food(user,{'name':'QA bebida de limón','brand':'Marca Mexicana QA'})
    product.nutrition_json={'barcode':'7500000000042'};db.session.commit()
    assert isinstance(catalog.search(user,'crudo',progressive=True),list)
    assert isinstance(catalog.search(user,'',progressive=True),list)
    for query in ['limon nombre comercial muy largo','7500000000042',product.public_id,'Marca Mexicana QA']:
        assert any(h['ref']=='user:'+product.public_id for h in catalog.search(user,query,progressive=True))


def test_percentage_revision_and_same_day_conflicts_stay_blocked(app,user,consumed):
    review=copy.deepcopy(consumed.review_json)
    review['rows'][12]['declaration']['iron']={'state':'known','unit':'% DV','value':'10'}
    consumed.review_json=review;db.session.commit()
    with pytest.raises(NutritionError):
        compact.save_decisions(user,consumed.public_id,consumed.revision,{'r12_declared_iron':'11'})
    db.session.rollback()
    hit=next(h for h in catalog.search(user,'pollo',progressive=True) if h['source_food_id']=='2')
    with pytest.raises(NutritionError):
        compact.save_decisions(user,consumed.public_id,consumed.revision,{'r1_p-1_ref':hit['ref']+'|999','r1_p-1_amount':'100','r1_p-1_unit':'g'})
    db.session.rollback()
    compact.save_decisions(user,consumed.public_id,consumed.revision,{'r12_nutrient_iron_action':'unknown'});db.session.commit()
    resolve(consumed,user)
    document=compact.document(consumed)
    document['data']['entries'][1]['authority']='derive_items'
    with pytest.raises(NutritionError,match='misma fecha'):imports.validate_document(document,user)


def test_standard_json_review_preserves_bindingless_consumptions(app,user,consumed):
    resolve(consumed,user)
    document=compact.document(consumed)
    row=imports.start(user,json.dumps(document).encode(),'QA canonical consumed-21.json');db.session.commit()
    view=compact.overview(row)
    assert view['counts']['ready']==21
    again=compact.document(row)
    for left,right in zip(document['data']['entries'],again['data']['entries']):
        assert left['bindings']==right['bindings']
        assert left['portion_amount']==right['portion_amount'] and left['portion_unit']==right['portion_unit']
        a=imports.meal_snapshot(left,imports.resolved_entries(left,user),'UTC')
        b=imports.meal_snapshot(right,imports.resolved_entries(right,user),'UTC')
        assert a['summary']==b['summary']
