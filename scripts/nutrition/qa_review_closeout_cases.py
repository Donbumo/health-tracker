"""Fictional PR33 review gates shared by SQLite and exact-image MariaDB QA."""
import copy
import json
import re
from collections import Counter
from decimal import Decimal
from html import unescape

from app.extensions import db
from app.models import User, MealLog, FoodProduct, NutritionItem, NutritionImportReceipt, FoodCatalogSource
from app.services import food_catalog as catalog, nutrition_import as imports, nutrition_import_review as review
from app.services import nutrition_intelligence as ni
from app.services.account_restore import AccountRestoreService
from app.services.exporters.user_data import build_user_data_document
from app.services.nutrition_math import NutritionError
from app.services.nutrition_portability import export_bundle, semantic_snapshot
from qa_preview_fixtures import source

SOURCE='qa_review33_identity'


def qa_catalog(uid):
    if not db.session.get(FoodCatalogSource,SOURCE):
        catalog.stage(dict(schema_version='2.0',source=SOURCE,revision='1',license='Fictional QA only',foods=[
            dict(source=SOURCE,source_food_id='one',revision='1',name='QA identidad verificable',preparation='QA cooked',
                 basis_amount='100',basis_unit='g',servings=[],density_g_ml=None,nutrients={
                     key:dict(state='known',value=value,unit=unit) for key,value,unit in [
                         ('energy','200','kcal'),('protein','10','g'),('carbohydrate_total','20','g'),
                         ('fat','8','g'),('iron','2','mg'),('vitamin_d','0','ug')]} )]))
        catalog.activate(SOURCE,'1',1);db.session.commit()
    if not catalog.search(uid,source=SOURCE):
        catalog.activate(SOURCE,'1',1);db.session.commit()
    hit=catalog.search(uid,source=SOURCE)[0]
    return catalog.detail(uid,hit['ref'])


def count(model,uid):
    return db.session.scalar(db.select(db.func.count(model.id)).where(model.user_id==uid))


def start(uid,document,name):
    payload=json.dumps(document,sort_keys=True).encode()
    row=imports.start(uid,payload,name);db.session.commit()
    return row,payload


def signed(client,row):
    response=client.get('/nutrition/import/'+row.public_id)
    assert response.status_code==200
    match=re.search(r'name="token" value="([^"]+)"',response.text)
    assert match,'QA review blocked'
    return unescape(match[1])


def save(client,row,csrf=None):
    fields=dict(revision=row.revision,token=signed(client,row),consent_consumed='yes')
    if csrf:fields['csrf_token']=csrf
    response=client.post('/nutrition/import/'+row.public_id+'/confirm',data=fields)
    assert response.status_code==200
    # HTTP uses its own session. End the observer's repeatable-read snapshot
    # before checking the committed result; expiring ORM objects is not enough.
    db.session.rollback()
    return fields


def roundtrip(uid,label):
    before=export_bundle(uid)
    target=User(username=label,role='user');target.set_password('fictional-review33-restore-password')
    db.session.add(target);db.session.commit()
    document=build_user_data_document(db.session.get(User,uid),uid)
    service=AccountRestoreService();preview=service.preview(document,user_id=target.id)
    assert service.commit(document,user_id=target.id,confirmation_token=preview['confirmation_token'])['committed']
    after=export_bundle(target.id)
    assert [semantic_snapshot(r['snapshot']) for r in before['logs']]==[semantic_snapshot(r['snapshot']) for r in after['logs']]
    return target.id


def identity_case(uid,client,case,csrf=None):
    food=qa_catalog(uid);document=source(1);raw=document['records'][0]
    raw.update(name=food['name'],revision='1',preparation='QA cooked')
    raw.pop('iron_mg')  # Identity must preserve micronutrients outside the declaration.
    if case=='source_ids':raw.update(source=SOURCE,source_food_id='one')
    else:raw['ref']=food['ref']
    if case=='missing_revision':raw.pop('revision')
    if case=='missing_preparation':raw.pop('preparation')
    if case=='wrong_revision':raw['revision']='not-the-pinned-revision'
    if case=='wrong_preparation':raw['preparation']='QA raw'
    if case=='name_only':
        for key in ('ref','revision','preparation'):raw.pop(key,None)
    row,payload=start(uid,document,'QA identity '+case+'.json')
    if case in {'manual','private'}:
        fields=dict(revision=row.revision,edit_index='0',r0_resolution='private' if case=='private' else 'catalog')
        if case=='manual':fields.update({'r0_p-1_ref':food['ref']+'|1','r0_p-1_amount':'100','r0_p-1_unit':'g'})
        if csrf:fields['csrf_token']=csrf
        assert client.post('/nutrition/import/'+row.public_id+'/decisions',data=fields).status_code==302
        db.session.rollback()
    before=copy.deepcopy(row.review_json)
    bound=case in {'ref','source_ids','manual'}
    for _ in range(3):
        state=review.overview(row);prepared=state['review']['rows'][0]
        assert state['counts']==dict(ready=1,decision=0,invalid=0,omitted=0)
        if bound:
            assert prepared['ingredients']==[dict(ref=food['ref'],food_revision='1',amount='100',unit='g')]
            assert prepared.get('resolution')!='declared'
        elif case=='private':assert prepared['ingredients'][0]['new_food']['name']==food['name']
        else:assert prepared['resolution']=='declared' and prepared['ingredients']==[]
        assert client.get('/nutrition/import/'+row.public_id).status_code==200
        assert row.review_json==before
    again=imports.start(uid,payload,'QA same identity reupload.json');db.session.commit()
    assert again.id==row.id and again.review_json==before
    canonical=review.document(row)['data']['entries'][0]
    assert bool(canonical['bindings'])==(bound or case=='private')
    fields=save(client,row,csrf)
    log=db.session.scalar(db.select(MealLog).where(MealLog.user_id==uid))
    snapshot=log.snapshot_json
    assert Decimal(snapshot['summary']['energy']['value'])==200
    if bound:
        selected=snapshot['ingredients'][0]['food']
        assert selected['ref']==food['ref'] and selected['revision']=='1' and selected['preparation']=='QA cooked'
        assert Decimal(snapshot['summary']['iron']['value'])==2
        assert Decimal(snapshot['summary']['vitamin_d']['value'])==0
    elif case!='private':assert snapshot['ingredients']==[] and snapshot['summary']['iron']['value'] is None
    assert count(FoodProduct,uid)==(1 if case=='private' else 0)
    assert client.post('/nutrition/import/'+row.public_id+'/confirm',data=fields).status_code==200
    assert count(MealLog,uid)==count(NutritionImportReceipt,uid)==1
    restored=roundtrip(uid,'QA identity restore '+str(uid))
    assert count(FoodProduct,restored)==(1 if case=='private' else 0)
    return dict(case=case,explicit_binding_preserved=bound,declared_fallback=not bound and case!='private',
                records=1,products=1 if case=='private' else 0,receipts=1,original_unchanged=True,roundtrip=True)


def grouping_case(uid,client,size,csrf=None):
    food=qa_catalog(uid)
    def document_for(count_,label):
        result=source(count_)
        for i,raw in enumerate(result['records']):
            raw.update(name=f'QA {label} individual {i+1}',ref=food['ref'],revision='1',preparation='QA cooked',
                       date='2026-02-02' if i%4==3 else '2026-02-01',
                       meal_type='dinner' if i%4==2 else 'breakfast')
            raw.pop('iron_mg')
        return result
    # Prior history of the same owner/date/type must remain a separate group.
    history,_=start(uid,document_for(1,'historial previo'),'QA prior history.json');save(client,history,csrf)
    oldlog=db.session.scalar(db.select(MealLog).where(MealLog.user_id==uid))
    old_snapshot=copy.deepcopy(oldlog.snapshot_json);old_projection=oldlog.projection_item_id
    prior_meal=db.session.get(NutritionItem,old_projection).nutrition_meal_id
    document=document_for(size,'lote nuevo');row,_=start(uid,document,'QA grouped '+str(size)+'.json')
    review.save_decisions(uid,row.public_id,row.revision,{'day_2026-02-01_conflict_action':'keep_and_add'});db.session.commit()
    fields=save(client,row,csrf)
    logs=db.session.scalars(db.select(MealLog).where(MealLog.user_id==uid).order_by(MealLog.id)).all()
    assert len(logs)==size+1 and logs[0].projection_item_id==old_projection and logs[0].snapshot_json==old_snapshot
    groups={};totals=Counter()
    for i,(log,raw) in enumerate(zip(logs[1:],document['records'])):
        item=db.session.get(NutritionItem,log.projection_item_id);meal=item.meal;key=(raw['date'],raw['meal_type'])
        assert log.snapshot_json['name']==raw['name']==item.name
        assert log.snapshot_json['local_date']==raw['date'] and log.snapshot_json['meal_type']==raw['meal_type']
        assert log.user_id==item.user_id==meal.user_id==uid
        assert meal.id!=prior_meal
        assert groups.setdefault(key,meal.id)==meal.id
        assert item.sort_order==1+sum(1 for previous in document['records'][:i] if (previous['date'],previous['meal_type'])==key)
        for nutrient,expected in [('energy',200),('protein',10),('carbohydrate_total',20),('fat',8),('iron',2),('vitamin_d',0)]:
            assert Decimal(log.snapshot_json['summary'][nutrient]['value'])==expected
        assert log.snapshot_json['summary']['vitamin_k1']['value'] is None
        totals[raw['date']]+=1
    assert len(set(groups.values()))==len(groups)
    assert db.session.get(NutritionItem,logs[1].projection_item_id).meal.name is None
    for target,count_ in totals.items():
        state=ni.daily_summary(uid,__import__('datetime').date.fromisoformat(target))['summary']
        count_+=1 if target=='2026-02-01' else 0
        assert Decimal(state['energy']['value'])==200*count_
        assert Decimal(state['protein']['value'])==10*count_ and Decimal(state['iron']['value'])==2*count_
        assert Decimal(state['carbohydrate_total']['value'])==20*count_ and Decimal(state['fat']['value'])==8*count_
        assert Decimal(state['vitamin_d']['value'])==0
    assert client.post('/nutrition/import/'+row.public_id+'/confirm',data=fields).status_code==200
    assert count(MealLog,uid)==size+1 and count(NutritionImportReceipt,uid)==2 and count(FoodProduct,uid)==0
    roundtrip(uid,'QA grouping restore '+str(uid))
    # A caller cannot redirect an otherwise valid consumption into a meal owned
    # by someone else or into another date/type. Every attempt rolls back.
    foreign=User(username='QA grouping foreign '+str(uid),role='user');foreign.set_password('fictional-review33-foreign')
    db.session.add(foreign);db.session.commit()
    foreign_row,_=start(foreign.id,document_for(1,'ajeno'),'QA foreign grouping.json')
    from app.services.importers.standard_import_executor import StandardImportExecutor
    result=StandardImportExecutor().commit_documents([review.document(foreign_row)],user_id=foreign.id,target_type='nutrition_import',confirmed=True)
    assert result['committed']
    foreign_log=db.session.scalar(db.select(MealLog).where(MealLog.user_id==foreign.id))
    foreign_snapshot=copy.deepcopy(foreign_log.snapshot_json)
    foreign_meal=db.session.get(NutritionItem,foreign_log.projection_item_id).meal
    own_first=db.session.get(NutritionItem,logs[1].projection_item_id).meal
    wrong_type=db.session.get(NutritionItem,logs[3].projection_item_id).meal
    wrong_date=db.session.get(NutritionItem,logs[4].projection_item_id).meal
    for invalid in [foreign_meal,wrong_type,wrong_date]:
        invalid_id=invalid.id
        draft=ni.create_draft(uid,target='2026-02-01',name='QA rejected grouping',meal_type='breakfast')
        draft.snapshot_json=copy.deepcopy(logs[1].snapshot_json);draft.accepted_json=[0];db.session.flush()
        try:ni.confirm(uid,ni.confirmation_token(draft),projection_meal=invalid)
        except NutritionError as error:assert error.status==404
        else:raise AssertionError('Grouping crossed owner/date/type')
        db.session.rollback()
        assert count(MealLog,uid)==size+1 and foreign_log.snapshot_json==foreign_snapshot
    assert own_first.id!=foreign_meal.id
    return dict(records=size,independent_snapshots=size,groups=len(groups),prior_history_unchanged=True,
                owner_date_meal_isolated=True,order_and_totals=True,products=0,batch_receipts=1,roundtrip=True)
