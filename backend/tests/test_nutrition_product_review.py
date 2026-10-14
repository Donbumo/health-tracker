"""Final product corrections, using exclusively fictional owner-isolated data."""
import copy
import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
import pytest
from app.extensions import db
from app.models import User, DailyNutrition, DailyEnergy, FoodProduct, Recipe, MealLog, UploadedFile
from app.services import food_catalog as catalog, nutrition_import as imports
from app.services.nutrition_history import history
from app.services.nutrition_math import NutritionError
from app.services.nutrition_sources import off_food, public_lookup
from tests.conftest import login
from tests.test_nutrition_intelligence import enabled, food
from tests.test_nutrition_experience_21 import reviewed, commit, FIXTURES


def test_energy_charts_real_legacy_new_partial_gaps_zero_and_signed_balance(app,user,enabled):
    records=[DailyNutrition(user_id=user,date=date(2026,10,7),source='qa',calories=2000),
             DailyNutrition(user_id=user,date=date(2026,10,8),source='qa',calories=2000,
                 nutrition_summary_json={'energy':{'state':'partial','value':'2000'}}),
             DailyNutrition(user_id=user,date=date(2026,10,10),source='qa',calories=0)]
    db.session.add_all(records+[DailyEnergy(user_id=user,date=date(2026,10,7),source='qa',total_calories=1500),
        DailyEnergy(user_id=user,date=date(2026,10,8),source='qa',total_calories=1500),
        DailyEnergy(user_id=user,date=date(2026,10,9),source='qa',total_calories=1600),
        DailyEnergy(user_id=user,date=date(2026,10,10),source='qa',total_calories=1400)])
    db.session.commit();result=history(user,date(2026,10,10),7)
    charts={c['key']:c for c in result['charts']}
    intake=charts['intake'];expense=charts['expended'];balance=charts['balance']
    assert intake['average']==1000 and intake['known_days']==2 and intake['partial_days']==1
    assert intake['samples'][-3]['state']=='partial' and intake['samples'][-3]['value']==2000
    assert intake['samples'][-2]['y'] is None and intake['samples'][-1]['value']==0
    assert len(intake['paths']['daily'])==2 # no straight interpolation across partial or gap
    assert expense['samples'][-2]['value']==1600
    assert balance['samples'][-3]['value'] is None and balance['samples'][-2]['value'] is None
    assert balance['samples'][-4]['value']==500 and balance['samples'][-1]['value']==-1400
    assert balance['low']<0 and 20<balance['zero_y']<180
    assert result['points'][-1]['rolling_energy_days']=={'intake':2,'expended':4,'balance':2}
    assert result['points'][-1]['rolling_energy']['balance']==-450


def test_rank_reviewed_words_never_equates_tortilla_chips_or_raw_cooked(app,user,enabled):
    specs=[('A QA tortilla chips','mixed'),('Tortilla maíz QA','cooked'),('White rice, cooked QA','cooked'),
           ('White rice mixture with wild rice QA','mixed'),('Chicken, raw QA','raw'),('Chicken, roasted QA','cooked'),
           ('Beans, black QA','cooked'),('Oats QA','raw'),('Fish pollock cooked QA','cooked'),
           ('Corned beef in tortilla QA','mixed'),('Chicken breast, baked, from raw QA','raw'),('Green beans QA','cooked'),
           ('Corn chips, Fritos QA','mixed')]
    foods=[]
    for i,(name,state) in enumerate(specs):
        f=food();f.update(source_food_id='rank-'+str(i),name=name,metadata={'preparation_state':state})
        foods.append(f)
    catalog.stage({'schema_version':'2.0','source':'qa_fictional','revision':'rank-v2','license':'QA synthetic','foods':foods})
    catalog.activate('qa_fictional','rank-v2',2);db.session.commit()
    assert catalog.search(user,'tortilla de maíz')[0]['name']=='Tortilla maíz QA'
    assert 'chips' in catalog.search(user,'totopos')[0]['name']
    assert all('Fritos' not in item['name'] for item in catalog.search(user,'totopos'))
    rice=catalog.search(user,'arroz blanco cocido');assert rice[0]['name']=='White rice, cooked QA'
    assert all('raw' in item['name'] for item in catalog.search(user,'pollo crudo'))
    assert all(item['state']=='cooked' for item in catalog.search(user,'pollo cocido'))
    assert all('pollock' not in item['name'] for item in catalog.search(user,'pollo'))
    assert all('baked' not in item['name'] for item in catalog.search(user,'pollo crudo'))
    assert all('Corned beef' not in item['name'] for item in catalog.search(user,'tortilla maiz'))
    assert catalog.search(user,'frijoles negros')[0]['name']=='Beans, black QA'
    assert all('Green beans' not in item['name'] for item in catalog.search(user,'frijoles'))
    assert catalog.search(user,'avena')[0]['name']=='Oats QA'
    assert not catalog.search(user,'THIS_IDENTITY_DOES_NOT_EXIST_QA')


def test_moving_window_uses_previous_days_without_adding_them_to_period_totals(app,user,enabled):
    db.session.add_all([DailyNutrition(user_id=user,date=date(2026,10,2),source='qa',calories=1000),
                        DailyNutrition(user_id=user,date=date(2026,10,4),source='qa',calories=2000)])
    db.session.commit()
    week=history(user,date(2026,10,10),7);month=history(user,date(2026,10,10),30)
    assert len(week['points'])==7 and week['points'][0]['date']==date(2026,10,4)
    assert week['points'][0]['rolling_energy']['intake']==1500
    assert week['points'][0]['rolling_energy_days']['intake']==2
    same=next(p for p in month['points'] if p['date']==date(2026,10,4))
    assert same['rolling_energy']==week['points'][0]['rolling_energy']
    assert week['metrics'][0]['known_subtotal']==2000 and week['metrics'][0]['complete_days']==1


def test_plain_brown_rice_precedes_derivatives_without_reidentifying_or_rewriting(app,user,enabled):
    names=['Rice flour, brown QA','Brown rice pasta QA','Rice, brown, long-grain, cooked QA',
           'Harina de arroz integral QA','Rice, white, cooked QA','Rice, brown, raw QA']
    foods=[]
    for i,name in enumerate(names):
        row=food();row.update(source_food_id='rice-qa-'+str(i),name=name,
            metadata={'preparation_state':'raw' if 'raw' in name else 'cooked'})
        row['nutrients']['energy']['value']=str(100+i)
        foods.append(row)
    catalog.stage({'schema_version':'2.0','source':'qa_fictional','revision':'rice-v2','license':'QA synthetic','foods':foods})
    catalog.activate('qa_fictional','rice-v2',2);db.session.commit()
    before={hit['ref']:catalog.detail(user,hit['ref']) for hit in catalog.search(user)}
    for query in ['arroz integral','brown rice','arroz integral cocido']:
        hits=catalog.search(user,query)
        assert hits[0]['source_food_id']=='rice-qa-2'
        assert all('white' not in hit['name'] for hit in hits)
        assert hits.index(next(hit for hit in hits if hit['source_food_id']=='rice-qa-2')) < hits.index(
            next(hit for hit in hits if hit['source_food_id']=='rice-qa-0'))
    assert catalog.search(user,'harina de arroz integral')[0]['source_food_id']=='rice-qa-3'
    assert catalog.search(user,'brown rice pasta')[0]['source_food_id']=='rice-qa-1'
    assert catalog.search(user,'arroz blanco cocido')[0]['source_food_id']=='rice-qa-4'
    assert all(hit['state']=='raw' for hit in catalog.search(user,'arroz integral crudo'))
    assert before=={hit['ref']:catalog.detail(user,hit['ref']) for hit in catalog.search(user)}


@pytest.mark.parametrize('value,state,empty',[(1250,'complete',False),(640,'partial',False),
                                           (0,'complete',False),(None,'unknown',False),(640,'partial',True)])
def test_first_summary_precedes_navigation_date_and_trends_and_preserves_quality(app,client,user,enabled,value,state,empty):
    row=DailyNutrition(user_id=user,date=date(2026,10,12),source='QA fictional first viewport',calories=value,
        nutrition_summary_json={'energy':{'state':state,'value':str(value) if value is not None else None}})
    db.session.add(row);db.session.commit();login(client)
    response=client.get('/nutrition/?date='+('2026-10-14' if empty else '2026-10-12'))
    assert response.status_code==200
    html=response.get_data(as_text=True)
    first=html.index('aria-label="Resumen nutricional inicial"')
    assert first<html.index('aria-label="Nutrición"')<html.index('id="ni-date-history"')<html.index('TENDENCIAS')
    summary=html[first:html.index('</section>',first)]
    assert {'complete':'energía completa','partial':'Subtotal conocido · energía parcial','unknown':'Ingesta desconocida'}[state] in summary
    if empty:
        assert 'Último registro · 2026-10-12' in summary and 'Sin registro el 2026-10-14' in summary
        assert 'Ver último registro' in summary
    else:assert 'Día seleccionado' in summary
    if value==0:assert '<strong>0</strong> kcal' in summary
    assert 'Añadir comida' in summary and 'name="date"' in html and 'Historial reciente' in html


def test_private_library_search_paginates_more_than_100_each_and_is_owner_only(app,client,user,enabled):
    other=User(username='QA-other-library',role='user');other.set_password('fictional-qa-only');db.session.add(other);db.session.flush()
    for i in range(125):
        db.session.add(FoodProduct(user_id=user,name=f'QA producto {i:03}',brand='QA marca',source='manual'))
        db.session.add(Recipe(user_id=user,name=f'QA receta {i:03}',servings=1))
    db.session.add(FoodProduct(user_id=other.id,name='QA producto PRIVADO OTRO',source='manual'))
    db.session.add(Recipe(user_id=other.id,name='QA receta PRIVADA OTRA',servings=1))
    db.session.commit();login(client)
    for kind,word in [('products','producto'),('recipes','receta')]:
        first=client.get('/nutrition/library?kind='+kind).get_data(as_text=True)
        assert '125 resultados' in first and 'página 1/6' in first and 'Página siguiente' in first
        last=client.get(f'/nutrition/library?kind={kind}&{kind}_page=6').get_data(as_text=True)
        assert f'QA {word} 124' in last and 'PRIVADO OTRO' not in last and 'PRIVADA OTRA' not in last
        found=client.get(f'/nutrition/library?kind={kind}&q={word}+124').get_data(as_text=True)
        assert '1 resultados' in found and f'QA {word} 124' in found
    assert '0 resultados' in client.get('/nutrition/library?q=%25').get_data(as_text=True) # literal %, not a wildcard


def test_OFF_selection_prefill_is_pending_owner_bound_and_only_signed_confirmation_writes(app,client,user,enabled,monkeypatch):
    app.config['NUTRITION_EXTERNAL_LOOKUP_ENABLED']=True
    proposal=off_food({'code':'0000000000001','product_name':'QA OFF bebida ficticia','brands':'QA comercial',
        'nutrition_data_per':'100ml','quantity':'500 ml','last_modified_t':123,
        'nutriments':{'energy-kcal_100g':45,'proteins_100g':0,'carbohydrates_100g':7,'sodium_100g':.03}})
    monkeypatch.setattr(public_lookup,'lookup',lambda text,consent: [proposal] if consent else [])
    login(client);response=client.post('/nutrition/external',data={'q':'0000000000001','consent':'yes'})
    from html import unescape
    token=unescape(re.search(r'name="proposal" value="([^"]+)"',response.get_data(as_text=True)).group(1))
    selected=client.post('/nutrition/external/proposal',data={'proposal':token})
    assert db.session.query(FoodProduct).count()==0
    url=selected.headers['Location'];form=client.get(url).get_data(as_text=True)
    assert 'Revisar propuesta externa' in form and 'base_revision' not in form
    assert 'value="QA comercial"' in form and 'value="0000000000001"' in form and 'value="45"' in form
    assert 'value="0"' in form and 'sin clasificación confirmada' in form
    preview=client.post(url,data={'name':'QA OFF bebida revisada','brand':'QA comercial','barcode':'0000000000001',
        'basis_amount':'100','basis_unit':'ml','energy':'50','protein':'0','sodium':'30'})
    assert db.session.query(FoodProduct).count()==0
    confirmed_token=unescape(re.search(r'name="token" value="([^"]+)"',preview.get_data(as_text=True)).group(1))
    saved=client.post(url,data={'token':confirmed_token});assert saved.status_code==302
    product=db.session.query(FoodProduct).one()
    assert product.nutrition_json['basis_unit']=='ml' and product.calories_per_100g is None
    assert product.nutrition_json['nutrients']['energy']['value']=='50'
    assert 'carbohydrate_total' not in product.nutrition_json['nutrients']
    assert product.nutrition_json['provenance']['source']=='open_food_facts'
    other=User(username='QA-other-off',role='user');other.set_password('fictional-qa-only');db.session.add(other);db.session.commit()
    client.post('/logout');login(client,username=other.username,password='fictional-qa-only')
    assert client.get(url).status_code==404
    assert client.get('/nutrition/my-food?proposal=tampered').status_code==409


def test_wizard_scoped_edits_preserve_other_stages_invalidate_confirmation_and_still_validate(app,client,user,enabled):
    row=reviewed(user,enabled);before=copy.deepcopy(row.review_json['rows'][0]);login(client)
    row=imports.update(user,row.public_id,row.revision,'fields',{'index':0,'_section':'identity','name':'QA identidad corregida','meal_type':'lunch','planned_for':'2026-10-05'})
    item=row.review_json['rows'][0]
    assert item['declaration']==before['declaration'] and item['amount']==before['amount']
    assert item['ingredients']==before['ingredients'] and item['confirmed'] is False
    row=imports.update(user,row.public_id,row.revision,'fields',{'index':0,'_section':'composition','amount':'300','unit':'g','total_mass_g':'300'})
    assert row.review_json['rows'][0]['name']=='QA identidad corregida'
    assert row.review_json['rows'][0]['declaration']==before['declaration']
    db.session.commit()
    for step in range(1,5):
        response=client.get(f'/nutrition/import/{row.public_id}?step={step}')
        assert response.status_code==200 and f'PASO {step} DE 4'.encode() in response.data
    early=client.get(f'/nutrition/import/{row.public_id}?step=1').get_data(as_text=True)
    assert 'name="nutrient_energy"' not in early and 'name="ref"' not in early
    with pytest.raises(NutritionError):imports.update(user,row.public_id,row.revision,'fields',{'index':0,'_section':'invented'})
    assert db.session.query(MealLog).count()==0


def test_original_deletion_explicit_owner_revision_csrf_and_physical_file(app,client,user,enabled):
    row=imports.start(user,(FIXTURES/'external.json').read_bytes(),'QA-private.json');db.session.commit();key=row.public_id
    source=db.session.get(UploadedFile,row.source_json['upload_id']);path=Path(app.config['DATA_ROOT'])/source.storage_path
    assert path.is_file() and imports.original_policy(row)['can_delete'];login(client)
    assert client.post(f'/nutrition/import/{key}/delete-original',data={'revision':row.revision}).status_code==422
    assert client.post(f'/nutrition/import/{key}/delete-original',data={'revision':row.revision+1,'confirmed':'yes'}).status_code==409
    other=User(username='QA-other-delete',role='user');other.set_password('fictional-qa-only');db.session.add(other);db.session.commit()
    with pytest.raises(NutritionError) as wrong:imports.delete_original(other.id,key,row.revision,confirmed=True)
    assert wrong.value.status==404
    app.config['WTF_CSRF_ENABLED']=True
    assert client.post(f'/nutrition/import/{key}/delete-original',data={'revision':row.revision,'confirmed':'yes'}).status_code==400
    app.config['WTF_CSRF_ENABLED']=False
    result=client.post(f'/nutrition/import/{key}/delete-original',data={'revision':row.revision,'confirmed':'yes'})
    assert result.status_code==302 and not path.exists() and db.session.query(UploadedFile).count()==0
    row=imports.owned(user,key);assert row.state=='cancelled' and row.source_json['upload_id'] is None
    assert row.review_json['rows'][0]['original'] and imports.original_policy(row)['available'] is False
    assert db.session.query(MealLog).count()==0


def test_confirmed_original_retained_and_history_immutable_even_duplicate_upload(app,client,user,enabled):
    row=reviewed(user,enabled,destination='consumed');commit(row,user)
    snapshot=copy.deepcopy(db.session.query(MealLog).one().snapshot_json)
    source=db.session.get(UploadedFile,row.source_json['upload_id']);path=Path(app.config['DATA_ROOT'])/source.storage_path
    assert imports.original_policy(row)['can_delete'] is False
    again=imports.start(user,(FIXTURES/'compound-macros.json').read_bytes(),'QA-renamed.json');db.session.commit()
    # Duplicate status must not conceal the prior confirmed reference.
    assert imports.original_policy(again)['can_delete'] is False
    with pytest.raises(NutritionError):imports.delete_original(user,again.public_id,again.revision,confirmed=True)
    assert path.is_file() and db.session.query(MealLog).one().snapshot_json==snapshot


def test_shared_pending_original_and_foreign_domain_references_block_deletion(app,user,enabled):
    payload=(FIXTURES/'external.json').read_bytes()
    row=imports.start(user,payload,'QA-first.json');db.session.commit()
    second=imports.start(user,payload,'QA-second.json');db.session.commit()
    assert not imports.original_policy(row)['can_delete']
    imports.update(user,second.public_id,second.revision,'cancel',{});db.session.commit()
    assert imports.original_policy(row)['can_delete']
    linked=DailyEnergy(user_id=user,date=date(2026,10,11),source='qa',source_file_id=row.source_json['upload_id'])
    db.session.add(linked)
    db.session.commit();assert not imports.original_policy(row)['can_delete']
    db.session.delete(linked)
    source=db.session.get(UploadedFile,row.source_json['upload_id']);source.detected_type='recipe';source.import_status='duplicate'
    db.session.commit();assert not imports.original_policy(row)['can_delete']


def test_rejected_delete_transaction_does_not_remove_physical_original(app,client,user,enabled,monkeypatch):
    row=imports.start(user,(FIXTURES/'external.json').read_bytes(),'QA-rollback.json');db.session.commit()
    key=row.public_id;revision=row.revision;upload_id=row.source_json['upload_id']
    source=db.session.get(UploadedFile,upload_id);path=Path(app.config['DATA_ROOT'])/source.storage_path
    login(client)
    def reject():raise RuntimeError('QA synthetic commit failure')
    with monkeypatch.context() as patch:
        patch.setattr(db.session,'commit',reject)
        with pytest.raises(RuntimeError):client.post(f'/nutrition/import/{key}/delete-original',data={'revision':revision,'confirmed':'yes'})
    db.session.rollback()
    assert path.is_file() and db.session.get(UploadedFile,upload_id) is not None
    assert imports.owned(user,key).state=='pending'


def test_detached_original_cannot_confirm_a_pending_file_review(app,user,enabled):
    row=imports.start(user,(FIXTURES/'external.json').read_bytes(),'QA-detached.json');db.session.commit()
    db.session.delete(db.session.get(UploadedFile,row.source_json['upload_id']));db.session.commit()
    with pytest.raises(NutritionError) as missing:imports.update(user,row.public_id,row.revision,'confirm',{'index':0})
    assert missing.value.status==409 and db.session.query(MealLog).count()==0
