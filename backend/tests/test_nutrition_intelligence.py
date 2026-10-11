"""All users/meals/values in these tests are fictional QA fixtures."""
import copy
from datetime import date
from decimal import Decimal
import pytest
from app.extensions import db
from app.models import User, DailyNutrition, FoodProduct, Recipe, NutritionItem
from app.models.nutrition_intelligence import MealLog, MealDraft
from app.services import food_catalog as catalog, nutrition_intelligence as ni
from app.services.nutrition_math import NutritionError, ingredient, summarize, normalize, validate_vector


def food():
    return {'source':'qa_fictional','source_food_id':'QA_ONLY','revision':'1','name':'QA fictitious food',
        'preparation':'Fictitious cooked QA','basis_amount':'100','basis_unit':'g','density_g_ml':None,
        'nutrients':{'energy':{'state':'known','value':'165','unit':'kcal'},
                    'protein':{'state':'known','value':'31','unit':'g'},
                    'vitamin_d':{'state':'known','value':'0','unit':'ug'}},
        'servings':[{'id':'qa-cup','label':'QA cup only','amount':'158','unit':'g'}]}


@pytest.fixture
def enabled(app,user):
    app.config['NUTRITION_INTELLIGENCE_ENABLED']=True
    record=catalog.stage({'schema_version':'2.0','source':'qa_fictional','revision':'1','license':'QA synthetic', 'foods':[food()]})
    catalog.activate('qa_fictional','1',1)
    db.session.commit()
    return catalog.search(user)[0]['ref']


def ready(user,ref,target='2026-10-09'):
    draft=ni.create_draft(user,target=target,entries=[{'ref':ref,'amount':'180','unit':'g'}])
    draft=ni.mutate_draft(user,draft.public_id,draft.revision,'accept',{'index':0})
    return draft


@pytest.mark.parametrize('amount',['0','-1','NaN','Infinity',True,'bad','100000001','0.0000000000001'])
def test_invalid_quantities(amount):
    with pytest.raises(NutritionError): ingredient(food(),amount,'g')


def test_decimal_unknown_zero_trace_and_limits():
    a=ingredient(food(),'180','g')
    assert Decimal(a['contribution']['energy']['value'])==Decimal('297')
    b=food(); b['nutrients']['vitamin_d']={'state':'trace','value':None,'unit':'ug'}
    b['nutrients']['iron']={'state':'below_limit','value':None,'limit':'0.1','unit':'mg'}
    result=summarize([a,ingredient(b,'120','g')])
    assert result['vitamin_d']['value']=='0.0'
    assert result['vitamin_d']['state']=='partial' and Decimal(result['vitamin_d']['coverage'])==60
    assert result['iron']['state']=='unknown' and result['iron']['value'] is None
    assert a['contribution']['vitamin_c']['value'] is None
    assert ingredient(b,'120','g')['contribution']['iron']['limit']=='0.12'


def test_servings_density_and_coverage_denominator():
    assert normalize(food(),1,'serving','qa-cup')['mass_g']=='158'
    with pytest.raises(NutritionError): normalize(food(),1,'serving','missing')
    with pytest.raises(NutritionError): normalize(food(),200,'ml')
    volume=food();volume['basis_unit']='ml'
    result=summarize([ingredient(volume,200,'ml')])
    assert result['energy']['coverage'] is None and result['energy']['total_weight'] is None
    volume['density_g_ml']='1.03'
    assert normalize(volume,200,'ml')['mass_g']=='206.00'


def test_chemical_forms_not_equivalent():
    f=food();f['nutrients']['folate_food']={'state':'known','value':'12','unit':'ug'}
    result=summarize([ingredient(f,100,'g')])
    assert result['folate_food']['value']=='12' and result['folate_dfe']['value'] is None
    with pytest.raises(NutritionError): validate_vector({'vitamin_a_rae':{'state':'known','value':'1','unit':'IU'}})


def test_confirmation_pending_csrf_independent_and_revision(app,user,enabled):
    draft=ni.create_draft(user,entries=[{'ref':enabled,'amount':100,'unit':'g'}])
    stale=ni.confirmation_token(draft)
    with pytest.raises(NutritionError): ni.confirm(user,stale)
    draft=ni.mutate_draft(user,draft.public_id,1,'accept',{'index':0})
    with pytest.raises(NutritionError): ni.confirm(user,stale)
    draft=ni.mutate_draft(user,draft.public_id,2,'amount',{'index':0,'amount':120,'unit':'g'})
    assert ni.pending(draft)==1
    with pytest.raises(NutritionError): ni.mutate_draft(user,draft.public_id,2,'accept',{'index':0})
    assert db.session.query(MealLog).count()==0


def test_event_idempotency_projection_double_count_and_repeat(app,user,enabled):
    draft=ready(user,enabled)
    token=ni.confirmation_token(draft)
    log,replay=ni.confirm(user,token);db.session.commit()
    assert not replay and ni.confirm(user,token)[1]
    assert db.session.query(MealLog).count()==1 and db.session.query(NutritionItem).count()==1
    result=ni.daily_summary(user,date(2026,10,9))
    assert Decimal(result['day'].calories)==297
    assert Decimal(result['summary']['energy']['value'])==297
    assert result['summary']['energy']['state']=='complete'
    again=ni.repeat(user,log.public_id,'2026-10-10')
    assert again.snapshot_json['ingredients']==log.snapshot_json['ingredients'] and ni.pending(again)==1


def test_snapshot_survives_catalog_and_template_changes(app,user,enabled):
    draft=ready(user,enabled)
    recipe=ni.save_template(user,draft.public_id,draft.revision)
    historical=copy.deepcopy(draft.snapshot_json)
    log,_=ni.confirm(user,ni.confirmation_token(draft));db.session.commit()
    newfood=food();newfood['revision']='2';newfood['nutrients']['energy']['value']='999'
    catalog.stage({'schema_version':'2.0','source':'qa_fictional','revision':'2','license':'QA synthetic','foods':[newfood]})
    catalog.activate('qa_fictional','2',2);db.session.commit()
    recipe.nutrition_snapshot_json=None;recipe.revision+=1;db.session.commit()
    assert log.snapshot_json==historical
    again=ni.repeat(user,log.public_id)
    assert Decimal(again.snapshot_json['summary']['energy']['value'])==297
    catalog.rollback('qa_fictional',3);db.session.commit()
    assert catalog.detail(user,enabled)['revision']=='1'


def test_legacy_aggregate_needs_explicit_resolution(app,user,enabled):
    day=DailyNutrition(user_id=user,date=date(2026,10,9),source='uploaded',calories=1500,protein_g=50)
    db.session.add(day);db.session.commit()
    draft=ready(user,enabled);token=ni.confirmation_token(draft);db.session.commit()
    with pytest.raises(NutritionError) as error: ni.confirm(user,token)
    assert error.value.status==409 and day.calories==1500
    db.session.rollback()
    ni.confirm(user,token,authority='disjoint_aggregate');db.session.commit()
    assert day.calories==1797 and day.authority_baseline_json['original_totals']['calories']=='1500.000'
    result=ni.daily_summary(user,date(2026,10,9))
    assert Decimal(result['summary']['energy']['value'])==1797
    assert result['summary']['energy']['coverage'] is None
    assert result['summary']['vitamin_d']['state']=='partial'


def test_owner_only_every_resource(app,user,enabled):
    other=User(username='qa-other',role='user');other.set_password('QA fictitious password')
    db.session.add(other);db.session.flush()
    product=FoodProduct(user_id=user,name='QA private',source='manual',is_active=True)
    db.session.add(product);db.session.flush()
    ref='user:'+product.public_id
    assert not any(r['ref']==ref for r in catalog.search(other.id))
    with pytest.raises(NutritionError): catalog.detail(other.id,ref)
    draft=ready(user,enabled)
    with pytest.raises(NutritionError): ni.owned_draft(other.id,draft.public_id)
    with pytest.raises(NutritionError): ni.confirm(other.id,ni.confirmation_token(draft))
    log,_=ni.confirm(user,ni.confirmation_token(draft));db.session.flush()
    with pytest.raises(NutritionError): ni.owned_log(other.id,log.public_id)
    assert not ni.daily_summary(other.id,date(2026,10,9))['logs']


def test_feature_flag_stops_new_writes_preserves_reads(app,user,enabled):
    draft=ready(user,enabled);log,_=ni.confirm(user,ni.confirmation_token(draft));db.session.commit()
    app.config['NUTRITION_INTELLIGENCE_ENABLED']=False
    with pytest.raises(NutritionError): ni.repeat(user,log.public_id)
    assert ni.daily_summary(user,date(2026,10,9))['logs'][0].public_id==log.public_id


def test_legacy_api_cannot_destroy_canonical_snapshot(app,user,enabled):
    from app.services.mobile_health import patch_nutrition_item,delete_nutrition_item,duplicate_nutrition_item
    draft=ready(user,enabled);log,_=ni.confirm(user,ni.confirmation_token(draft));db.session.commit()
    item=db.session.get(NutritionItem,log.projection_item_id)
    for operation,payload in [(patch_nutrition_item,{'base_revision':1,'name':'bad'}),
                              (delete_nutrition_item,{'base_revision':1}),
                              (duplicate_nutrition_item,{})]:
        with pytest.raises(Exception) as error: operation(user,item.public_id,payload)
        assert getattr(error.value,'status',getattr(error.value,'status_code',None))==409
    assert db.session.query(MealLog).count()==1


def test_official_account_export_restore_roundtrip(app,user,enabled):
    from app.services.exporters.user_data import build_user_data_document
    from app.services.account_restore import AccountRestoreService
    from app.services.nutrition_portability import export_bundle,semantic_snapshot
    draft=ready(user,enabled)
    recipe=ni.save_template(user,draft.public_id,draft.revision)
    log,_=ni.confirm(user,ni.confirmation_token(draft));db.session.commit()
    payload=build_user_data_document(db.session.get(User,user),user)
    assert payload['data']['nutrition_intelligence'][0]['schema_version']=='2.0'
    target=User(username='qa-restore-target',role='user');target.set_password('QA password')
    db.session.add(target);db.session.commit();target_id=target.id
    service=AccountRestoreService()
    preview=service.preview(payload,user_id=target_id)
    assert not [o for o in preview['plan']['operations'] if o['operation'] in {'invalid','conflict'}],preview
    result=service.commit(payload,user_id=target_id,confirmation_token=preview['confirmation_token'])
    assert result['committed'],result
    restored=export_bundle(target_id)
    assert semantic_snapshot(restored['logs'][0]['snapshot'])==semantic_snapshot(log.snapshot_json)
    assert restored['logs'][0]['snapshot']['ingredients'][0]['food']['revision']=='1'
    assert Decimal(ni.daily_summary(target_id,date(2026,10,9))['summary']['energy']['value'])==297
    again=service.preview(payload,user_id=target_id)
    assert next(o for o in again['plan']['operations'] if o['section']=='nutrition_intelligence')['operation']=='skip'
    service.commit(payload,user_id=target_id,confirmation_token=again['confirmation_token'])
    assert db.session.query(MealLog).filter_by(user_id=target_id).count()==1


def test_web_pages_no_fixtures_photo_or_text_ai(app,client,user,enabled):
    from tests.conftest import login
    login(client)
    for path in ['/nutrition/','/nutrition/add','/nutrition/foods','/nutrition/foods/'+enabled,
                 '/nutrition/saved','/nutrition/micronutrients','/nutrition/my-food']:
        response=client.get(path)
        assert response.status_code==200,(path,response.text)
    assert 'No disponible' in client.get('/nutrition/add').text
    assert 'upload' not in client.get('/nutrition/add').text
    draft=ready(user,enabled);db.session.commit()
    response=client.get('/nutrition/drafts/'+draft.public_id)
    assert response.status_code==200 and '0 pendientes' in response.text
    assert 'Confirmar y registrar consumo' in response.text
    response=client.get('/nutrition/foods/'+enabled+'?draft='+draft.public_id)
    assert response.status_code==200 and 'name="revision" value="2"' in response.text


def test_web_csrf_missing_token_blocked(app,client,user,enabled):
    from tests.conftest import login
    login(client);app.config['WTF_CSRF_ENABLED']=True
    assert client.post('/nutrition/drafts').status_code==400
    assert db.session.query(MealDraft).count()==0


def test_full_backup_preserves_versioned_snapshots(app,user,enabled):
    from app.services.backups import AccountBackupService,BackupRestoreCoordinator
    from tests.test_full_backup import _stage
    from app.services.nutrition_portability import export_bundle,semantic_snapshot
    draft=ready(user,enabled);log,_=ni.confirm(user,ni.confirmation_token(draft));db.session.commit()
    service=AccountBackupService();record=service.create(db.session.get(User,user),user_id=user)
    path=service.resolve_download(record,user_id=user)
    target=User(username='qa-backup-target',role='user');target.set_password('QA password')
    db.session.add(target);db.session.commit()
    coordinator=BackupRestoreCoordinator();staging=_stage(path,coordinator,target.id)
    preview=coordinator.preview(staging_id=staging,user_id=target.id)
    result=coordinator.confirm(staging_id=staging,user_id=target.id,confirmation_token=preview['confirmation_token'])
    assert result['committed'],result
    restored=export_bundle(target.id)
    assert semantic_snapshot(restored['logs'][0]['snapshot'])==semantic_snapshot(log.snapshot_json)


def test_personal_nutrients_restore_owner_remap_and_macro_edit(app,user,enabled):
    from app.services.mobile_health import create_food,patch_food
    from app.services.nutrition_portability import export_bundle
    product=create_food(user,{'name':'QA private micro','calories_per_100g':'10','protein_g_per_100g':'2'})
    product.nutrition_json={'nutrients':{'iron':{'state':'known','value':'0','unit':'mg'}},'servings':[],'density_g_ml':None}
    db.session.commit()
    ref='user:'+product.public_id
    draft=ready(user,ref)
    before=copy.deepcopy(draft.snapshot_json)
    patch_food(user,product.public_id,{'base_revision':1,'calories_per_100g':'20'});db.session.commit()
    assert Decimal(catalog.detail(user,ref)['nutrients']['energy']['value'])==Decimal('20')
    assert draft.snapshot_json==before
    assert export_bundle(user)['foods'][0]['nutrition']['nutrients']['iron']['value']=='0'


def test_partial_day_not_compared_by_dashboard_or_coach(app,user,enabled):
    from app.services.nutrition_intelligence import comparison_value
    draft=ready(user,enabled)
    ni.confirm(user,ni.confirmation_token(draft));db.session.commit()
    day=ni.daily_summary(user,date(2026,10,9))['day']
    assert comparison_value(day,'protein_g')==Decimal('55.8')
    assert comparison_value(day,'fiber_g') is None


def test_foreign_product_import_reference_is_rejected(app,user):
    from app.services.importers.daily_nutrition import _validate_recipe_references,DailyNutritionImportError
    other=User(username='qa-foreign-product',role='user');other.set_password('QA synthetic password')
    db.session.add(other);db.session.flush()
    product=FoodProduct(user_id=other.id,name='QA foreign private',source='manual')
    db.session.add(product);db.session.flush()
    with pytest.raises(DailyNutritionImportError):
        _validate_recipe_references({'meals':[{'items':[{'food_product_id':product.id}]}]},user)


def test_legacy_aggregate_android_create_is_protected(app,user,enabled):
    from app.services.mobile_health import create_nutrition_item,MobileSyncError
    day=DailyNutrition(user_id=user,date=date(2026,10,9),source='qa',calories=1000)
    db.session.add(day);db.session.commit()
    with pytest.raises(MobileSyncError) as error:
        create_nutrition_item(user,{'date':'2026-10-09','meal_type':'lunch','name':'QA new','calories_kcal':100})
    assert error.value.status==409 and day.calories==1000


def test_template_concurrent_edit_and_catalog_revision_conflict(app,user,enabled):
    draft=ready(user,enabled);recipe=ni.save_template(user,draft.public_id,draft.revision);db.session.commit()
    first=ni.template_draft(user,recipe.public_id);second=ni.template_draft(user,recipe.public_id)
    first=ni.mutate_draft(user,first.public_id,first.revision,'accept',{'index':0})
    second=ni.mutate_draft(user,second.public_id,second.revision,'accept',{'index':0})
    db.session.commit()
    ni.save_template(user,first.public_id,first.revision,recipe_key=recipe.public_id,base_revision=1);db.session.commit()
    with pytest.raises(NutritionError) as error:
        ni.save_template(user,second.public_id,second.revision,recipe_key=recipe.public_id,base_revision=1)
    assert error.value.status==409
    changed=food();changed['nutrients']['energy']['value']='999'
    with pytest.raises(NutritionError): catalog.stage({'schema_version':'2.0','source':'qa_fictional','revision':'1','license':'QA synthetic','foods':[changed]})


def test_confirm_caller_rollback_leaves_no_consumption(app,user,enabled):
    draft=ready(user,enabled);token=ni.confirmation_token(draft);db.session.commit()
    ni.confirm(user,token);db.session.rollback()
    assert db.session.query(MealLog).count()==0 and db.session.query(NutritionItem).count()==0
    assert ni.owned_draft(user,draft.public_id).state=='pending'


def test_source_sample_passes_registry_without_live_apis(app):
    import json
    from pathlib import Path
    sample=json.loads((Path(__file__).resolve().parents[2]/'examples/qa/nutrition-intelligence/catalog-sample.json').read_text(encoding='utf-8'))
    assert len(catalog.LocalSnapshotSource().validate(sample)['foods'])==37


def test_template_metadata_preserves_edit_target_and_save_replay(app,user,enabled):
    draft=ready(user,enabled)
    recipe=ni.save_template(user,draft.public_id,draft.revision)
    db.session.commit()
    draft=ni.mutate_draft(user,draft.public_id,draft.revision,'metadata',{'name':'QA renamed template','date':'2026-10-10','meal_type':'dinner'})
    assert draft.snapshot_json['save_target']==recipe.public_id
    old_revision=recipe.revision
    ni.save_template(user,draft.public_id,draft.revision,recipe_key=recipe.public_id,base_revision=old_revision)
    db.session.commit()
    assert recipe.revision==old_revision+1
    replay=ni.save_template(user,draft.public_id,draft.revision,recipe_key=recipe.public_id,base_revision=old_revision)
    assert replay.id==recipe.id and replay.revision==old_revision+1
    assert len(recipe.ingredients)==1


def test_versioned_restore_rejects_contradictory_dates_and_missing_personal_refs(app,user,enabled):
    from app.services.nutrition_portability import export_bundle,validate_bundle
    draft=ready(user,enabled)
    ni.confirm(user,ni.confirmation_token(draft));db.session.commit()
    bundle=export_bundle(user)
    changed=copy.deepcopy(bundle);changed['logs'][0]['local_date']='2026-10-11'
    with pytest.raises(NutritionError):validate_bundle(changed)
    changed=copy.deepcopy(bundle);changed['authorities'][0]['authority']='disjoint_aggregate'
    with pytest.raises(NutritionError):validate_bundle(changed)


def test_catalog_traceability_and_legacy_recipe_export_guard(app,client,user,enabled):
    from tests.conftest import login
    draft=ready(user,enabled)
    assert len(draft.snapshot_json['ingredients'][0]['food']['catalog_sha256'])==64
    recipe=ni.save_template(user,draft.public_id,draft.revision);db.session.commit()
    login(client)
    assert client.get(f'/recipes/{recipe.id}/export').status_code==409
    assert client.get('/recipes/export-all').status_code==409


def test_partial_energy_never_becomes_daily_balance_deficit(app,user,enabled):
    from app.models import DailyEnergy
    from app.services.daily_balance import daily_balance
    from app.services.exporters.user_data import _daily_balances
    missing=FoodProduct(user_id=user,name='QA missing energy',source='manual')
    db.session.add(missing);db.session.commit()
    draft=ni.create_draft(user,target='2026-10-09',entries=[{'ref':enabled,'amount':'100','unit':'g'},
        {'ref':'user:'+missing.public_id,'amount':'100','unit':'g'}])
    for i in range(2):draft=ni.mutate_draft(user,draft.public_id,draft.revision,'accept',{'index':i})
    ni.confirm(user,ni.confirmation_token(draft))
    energy=DailyEnergy(user_id=user,date=date(2026,10,9),source='manual',total_calories=2000)
    db.session.add(energy);db.session.commit()
    result=daily_balance(user,date(2026,10,9))
    assert result['calories_consumed']==165
    assert result['balance'] is None and not result['complete']
    assert result['nutrient_details']['energy']['state']=='partial'
    assert _daily_balances([result['nutrition']],[energy])[0]['balance'] is None
    from app.services.coach import CoachBriefService
    brief=CoachBriefService().build(db.session.get(User,user),today=date(2026,10,9))['today']
    signal=next(s for s in brief['signals'] if s['metric']=='energy_intake')
    assert signal['type']=='insufficient_data' and signal['current']=='165.00'
    assert 'datos incompletos' in signal['title']
    assert any(e['source']=='mass_weighted_v1' for e in signal['evidence'])


def test_new_draft_uses_effective_owner_local_date(app,user,enabled,monkeypatch):
    from datetime import datetime,timezone
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):
            return datetime(2026,10,10,2,tzinfo=timezone.utc).astimezone(tz)
    account=db.session.get(User,user);account.timezone='America/Los_Angeles';db.session.commit()
    monkeypatch.setattr(ni,'datetime',Clock)
    draft=ni.create_draft(user,entries=[{'ref':enabled,'amount':'1','unit':'g'}])
    assert draft.snapshot_json['local_date']=='2026-10-09'
    assert draft.snapshot_json['timezone']=='America/Los_Angeles'


def test_snapshot_precision_projection_rounding_and_recipe_capacity(app,user):
    from app.services.mobile_health import create_food
    app.config['NUTRITION_INTELLIGENCE_ENABLED']=True
    product=create_food(user,{'name':'QA fractional energy','calories_per_100g':'0.0005'})
    product.nutrition_json={'nutrients':{'energy':{'state':'known','value':'0.0005','unit':'kcal'}},'servings':[],'density_g_ml':None}
    db.session.commit()
    draft=ready(user,'user:'+product.public_id)
    draft=ni.mutate_draft(user,draft.public_id,draft.revision,'amount',{'index':0,'amount':'100','unit':'g'})
    draft=ni.mutate_draft(user,draft.public_id,draft.revision,'accept',{'index':0})
    log,_=ni.confirm(user,ni.confirmation_token(draft));db.session.commit()
    item=db.session.get(NutritionItem,log.projection_item_id)
    assert item.calories==Decimal('0.001')
    assert Decimal(log.snapshot_json['summary']['energy']['value'])==Decimal('0.0005')
    tiny=ni.create_draft(user,entries=[{'ref':'user:'+product.public_id,'amount':'0.0001','unit':'g'}])
    tiny=ni.mutate_draft(user,tiny.public_id,tiny.revision,'accept',{'index':0})
    with pytest.raises(NutritionError):ni.save_template(user,tiny.public_id,tiny.revision)


def test_versioned_history_budget_and_immutable_metadata(app,user,enabled):
    from app.services.nutrition_portability import export_bundle,plan_bundle
    from app.services.account_restore import _validate_json_limits,AccountRestoreError
    from datetime import datetime,timezone
    draft=ready(user,enabled);log,_=ni.confirm(user,ni.confirmation_token(draft))
    log.consumed_at=datetime(2026,10,9,12,tzinfo=timezone.utc);db.session.commit();db.session.expire_all()
    bundle=export_bundle(user)
    assert bundle['logs'][0]['consumed_at'].endswith('+00:00')
    changed=copy.deepcopy(bundle);changed['logs'][0]['revision']=2
    with pytest.raises(NutritionError):plan_bundle(changed,user)
    # New full snapshots are verbose; their budget is separate and bounded.
    values=list(range(900))
    _validate_json_limits({'data':{'nutrition_intelligence':[{'values':values} for _ in range(70)]}})
    with pytest.raises(AccountRestoreError):_validate_json_limits({'data':{'legacy':[{'values':values} for _ in range(70)]}})
    with pytest.raises(AccountRestoreError):_validate_json_limits({'data':{'nutrition_intelligence':[{'values':values} for _ in range(600)]}})
