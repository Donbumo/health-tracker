"""Two PR30 review gates, genuine #29 QA drafts and text portion inputs."""
import copy
import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import sys

import pytest
from sqlalchemy import event
from app.extensions import db
from app.models import MealLog, FoodProduct, NutritionImportDraft, NutritionImportReceipt, UploadedFile, User
from app.services import nutrition_import as imports,nutrition_import_review as compact,food_catalog as catalog
from app.services.nutrition_import_reprocess import reprocess
from app.services.nutrition_import_portions import sufficient
from app.services.importers.nutrition_sources import normalized_row
from app.services.nutrition_math import NutritionError
from tests.conftest import login
from tests.test_nutrition_import_summary import token

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/nutrition'))
from qa_legacy_import_29 import legacy_review


@pytest.fixture
def predecessor(app,user):
    app.config['NUTRITION_INTELLIGENCE_ENABLED']=True
    fixture=ROOT/'examples/qa/nutrition-import-ux'
    catalog.stage(json.loads((fixture/'consumed-catalog.json').read_text(encoding='utf-8')))
    catalog.activate('qa_import_consumed','1',1);db.session.commit()
    ref=next(h['ref'] for h in catalog.search(user,source='qa_import_consumed') if h['source_food_id']=='1')
    payload=(fixture/'consumed-text-portions-21.json').read_bytes()
    return legacy_review(user,payload,ref),payload


def accept_fields(user,row):
    data={'accept_previous':'yes','use_declarations':'yes','r9_portion_label_confirmed':'yes',
          **{f'r{i}_equivalence_confirmed':'yes' for i in [4,5,6,7,8,10,11]}}
    compact.save_decisions(user,row.public_id,row.revision,data);db.session.commit()


@pytest.mark.parametrize('expired',[False,True])
def test_actual_29_reopen_reupload_reprocess_and_confirm(app,client,user,predecessor,expired):
    old,payload=predecessor
    if expired:old.created_at-=timedelta(days=2);db.session.commit()
    old_content=copy.deepcopy(old.review_json);old_source=copy.deepcopy(old.source_json)
    old_created=old.created_at;login(client)
    def guard(conn,cursor,stmt,params,context,many):
        assert stmt.lstrip().split()[0].upper() not in {'INSERT','UPDATE','DELETE','REPLACE','CREATE','ALTER','DROP','TRUNCATE'}
    event.listen(db.engine,'before_cursor_execute',guard)
    try:
        page=client.get('/nutrition/import/'+old.public_id)
        assert page.status_code==200 and 'Reprocesar original con importador actualizado' in page.text
    finally:event.remove(db.engine,'before_cursor_execute',guard)
    assert compact.overview(old)['counts']['ready']==1
    assert imports.start(user,payload,'QA same SHA.json').id==old.id
    db.session.commit()
    path='/nutrition/import/'+old.public_id+('/recover' if expired else '/reprocess')
    response=client.post(path,data={'revision':old.revision})
    assert response.status_code==302
    fresh=imports.owned(user,response.location.rsplit('/',1)[1])
    assert fresh.id!=old.id and fresh.source_json['upload_id']==old.source_json['upload_id']
    assert fresh.source_sha256==old.source_sha256 and fresh.source_json['reprocessed_revision']==5
    assert fresh.review_json['rows'][1]['name']=='QA nombre corregido por usuario'
    assert fresh.review_json['rows'][1]['brand']=='QA marca conservada'
    assert fresh.review_json['rows'][2]['amount']=='150' and fresh.review_json['rows'][2]['unit']=='g'
    assert fresh.review_json['rows'][0]['ingredients']==old.review_json['rows'][0]['ingredients']
    assert fresh.review_json['rows'][5]['equivalence']['amount']=='473'
    with pytest.raises(NutritionError,match='campos conservados'):compact.document(fresh)
    from app.nutrition.routes import _import_serializer
    previous_token=_import_serializer().dumps({'owner':user,'draft':old.public_id,'revision':5,'document':'QA old claim'})
    assert client.post('/nutrition/import/'+fresh.public_id+'/confirm',data={'revision':fresh.revision,'token':previous_token,'consent_consumed':'yes'}).status_code==409
    # A replay must never reset an independently edited new review.
    compact.save_decisions(user,fresh.public_id,fresh.revision,{'r3_name':'QA cambio posterior de revisión nueva'})
    db.session.commit();changed=copy.deepcopy(fresh.review_json)
    assert client.post(path,data={'revision':5}).location==response.location
    assert fresh.review_json==changed
    assert imports.start(user,payload,'QA repeated SHA.json').id==fresh.id;db.session.commit()
    accept_fields(user,fresh)
    view=compact.overview(fresh)
    assert view['counts']['ready']==21,[(r['index'],r['issues']) for r in view['records'] if r['issues']]
    signed=token(client,fresh)
    response=client.post('/nutrition/import/'+fresh.public_id+'/confirm',data={'revision':fresh.revision,'token':signed,'consent_consumed':'yes'})
    assert response.status_code==200
    assert db.session.query(MealLog).count()==21 and db.session.query(FoodProduct).count()==0
    assert db.session.query(NutritionImportReceipt).count()==1
    assert sum(Decimal(l.snapshot_json['summary']['energy']['value']) for l in db.session.query(MealLog))==Decimal('4042.79')
    assert old.review_json==old_content and old.source_json==old_source and old.revision==5 and old.created_at==old_created


def test_reprocess_owner_csrf_revision_integrity_and_rollback(app,client,user,predecessor):
    from unittest.mock import patch
    old,_=predecessor;login(client);path='/nutrition/import/'+old.public_id+'/reprocess'
    assert client.post(path,data={'revision':6}).status_code==409
    app.config['WTF_CSRF_ENABLED']=True
    assert client.post(path,data={'revision':5}).status_code==400
    app.config['WTF_CSRF_ENABLED']=False
    other=User(username='QA gates other',role='user');other.set_password('QA fictional')
    db.session.add(other);db.session.commit()
    with pytest.raises(NutritionError) as denied:reprocess(other.id,old.public_id,5)
    assert denied.value.status==404
    upload=db.session.get(UploadedFile,old.source_json['upload_id'])
    original=Path(app.config['DATA_ROOT'])/upload.storage_path
    data=original.read_bytes();original.write_bytes(data+b' QA tampering')
    assert client.post(path,data={'revision':5}).status_code==409
    assert db.session.query(NutritionImportDraft).count()==1
    original.write_bytes(data)
    with patch('app.services.nutrition_import_reprocess.carry_decisions',side_effect=NutritionError('QA induced fork failure')):
        assert client.post(path,data={'revision':5}).status_code==422
    assert db.session.query(NutritionImportDraft).count()==1
    assert db.session.query(MealLog).count()==0


@pytest.mark.parametrize('amount,unit,count,label,equiv,base',[
    ('1 pieza (21 g)',None,'1','pieza',('21','g'),'g'),
    ('2 latas de 473 ml',None,'2','lata',('473','ml'),'ml'),
    ('2','latas de 473 ml','2','lata',('473','ml'),'ml'),
    ('5 sobres de 8 g (~40 g)',None,'5','sobre',('8','g'),'g'),
    ('7 piezas (~25 g c/u)',None,'7','pieza',('25','g'),'g'),
    ('1.5 porciones grandes',None,'1.5','porcion grande',None,'portion'),
])
def test_real_portion_text_evidence_and_verification(amount,unit,count,label,equiv,base):
    raw={'name':'QA porción textual','amount':amount,'basis_amount':'1' if base=='portion' else '100',
         'basis_unit':base,'kcal':'100'}
    if unit:raw['unit']=unit
    frozen=copy.deepcopy(raw);item=normalized_row(raw,{'file':'QA fictional text.json'})
    assert item['amount']==count and item['unit']=='portion' and item['unit_label']==label
    assert raw==frozen and item['original']==frozen
    with pytest.raises(NutritionError):sufficient(item)
    if equiv:
        assert (item['equivalence']['amount'],item['equivalence']['unit'])==equiv
        assert item['equivalence_confirmed'] is False
        item['equivalence_confirmed']=True
        quantity,unit,_=sufficient(item)
        assert Decimal(quantity)==Decimal(count)*Decimal(equiv[0]) and unit==equiv[1]
    else:
        assert 'equivalence' not in item
        item['portion_label_confirmed']=True
        assert sufficient(item)[:2]==('1.5','portion')
        assert sufficient(item)[2]['same_portion_confirmed'] is True


def test_unparseable_or_conflicting_notes_need_contextual_verification():
    item=normalized_row({'name':'QA variable','amount':'1 pieza de peso variable','basis_amount':'100','basis_unit':'g','kcal':'100'},{'file':'QA'})
    assert item['amount']=='1' and item['portion_note_pending'] and 'equivalence' not in item
    with pytest.raises(NutritionError):sufficient(item)
    item.update(equivalence={'amount':'31','unit':'g'},equivalence_confirmed=True)
    assert sufficient(item)[:2]==('31','g')
    conflict=normalized_row({'name':'QA total diferente','amount':'5 sobres de 8 g (~50 g)','basis_amount':'100','basis_unit':'g','kcal':'100'},{'file':'QA'})
    assert conflict['portion_conflict']
    with pytest.raises(NutritionError):sufficient(conflict)
    conflict['equivalence_confirmed']=True
    with pytest.raises(NutritionError):sufficient(conflict)
    conflict['portion_text_reviewed']=True
    assert sufficient(conflict)[:2]==('40','g')


def test_predecessor_nutrient_corrections_and_zero_remain_proposals(app,user,predecessor):
    from qa_legacy_import_29 import legacy_modules
    old,_=predecessor;_,service=legacy_modules()
    service.update(user,old.public_id,old.revision,'fields',{'index':'1','_section':'declaration',
        'basis_amount':'100','basis_unit':'g','nutrient_energy':'222','nutrient_protein':'0','nutrient_fat':'3'})
    db.session.commit();before=copy.deepcopy(old.review_json)
    fresh=reprocess(user,old.public_id,old.revision);db.session.commit()
    assert fresh.review_json['rows'][1]['declaration']==old.review_json['rows'][1]['declaration']
    assert fresh.review_json['rows'][1]['declaration']['protein']['value']=='0'
    assert 'vitamin_c' not in fresh.review_json['rows'][1]['declaration']
    assert fresh.source_json['reprocess_pending'] and old.review_json==before


def test_contextual_fallback_does_not_require_reentering_nutrients(app,client,user):
    app.config['NUTRITION_INTELLIGENCE_ENABLED']=True
    raw={'name':'QA pieza variable','amount':'1 pieza de peso variable','basis_amount':'100','basis_unit':'g',
         'kcal':'100','protein_g':'5','date':'2026-10-26','meal_type':'lunch'}
    row=imports.start(user,json.dumps({'destination':'consumed','records':[raw]}).encode(),'QA variable.json');db.session.commit()
    assert compact.overview(row)['counts']['decision']==1
    login(client)
    page=client.get('/nutrition/import/'+row.public_id)
    assert '1 pieza de peso variable' in page.text and 'r0_equivalence_amount' in page.text
    response=client.post('/nutrition/import/'+row.public_id+'/decisions',data={'revision':row.revision,'r0_resolution':'declared',
        'r0_equivalence_amount':'31','r0_equivalence_unit':'g','r0_equivalence_confirmed':'yes','r0_portion_text_reviewed':'yes'})
    assert response.status_code==302 and compact.overview(row)['counts']['ready']==1
    response=client.post('/nutrition/import/'+row.public_id+'/confirm',data={'revision':row.revision,'token':token(client,row),'consent_consumed':'yes'})
    assert response.status_code==200
    snapshot=db.session.query(MealLog).one().snapshot_json
    assert Decimal(snapshot['summary']['energy']['value'])==31
    assert snapshot['declared_nutrition']['original_values']==raw
    assert db.session.query(FoodProduct).count()==0
