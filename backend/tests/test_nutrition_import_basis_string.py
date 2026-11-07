"""Issue #40: fictional 2.1 strings are evidence, not internal decisions."""
import copy
import io
import json
import sys
from pathlib import Path
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import FoodProduct, MealLog, NutritionImportDraft, NutritionImportReceipt, UploadedFile
from app.services import nutrition_import as imports, nutrition_import_review as review
from app.services.validation import validate_json_document
from app.services.nutrition_math import NUTRIENTS,NutritionError,snapshot_summary,validate_vector
from tests.conftest import login
from tests.test_nutrition_import_source_21 import app

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/nutrition'))
from qa_pending_basis_fixtures import source18

PHRASE='Los nutrientes corresponden a la porción consumida.'


def fictional_document(text=PHRASE, count=14):
    doc=source18()
    for entry in doc['data']['entries'][:count]:
        entry['declaration']['provenance']['basis_interpretation']=text
    validate_json_document(doc,'nutrition_import_2_1')
    return doc


def start(app,user,doc):
    app.config['NUTRITION_INTELLIGENCE_ENABLED']=True
    row=imports.start(user,json.dumps(doc).encode(),'QA fictional string basis.json')
    db.session.commit()
    return row


def domain_counts():
    return (db.session.query(MealLog).count(),db.session.query(FoodProduct).count(),
            db.session.query(NutritionImportReceipt).count())


def test_string_basis_14_plus_four_editorial_objects_one_group_after_owner_action(app,client,user):
    row=start(app,user,fictional_document());login(client)
    frozen=copy.deepcopy(row.review_json)
    view=review.overview(row)
    assert view['counts']==dict(ready=0,decision=18,invalid=0,omitted=0)
    assert view['declared_basis_count']==18
    assert all(r['preview'] is None for r in view['records'])
    assert all(r['item']['declaration'] for r in view['records'])
    assert all(r['item']['original']['declaration']['provenance']['basis_interpretation']==PHRASE
               for r in view['records'][:14])
    assert all(r['item']['basis_interpretation']['status']=='proposed'
               for r in view['records'][:14])
    page=client.get('/nutrition/import/'+row.public_id)
    assert page.status_code==200 and 'name="accept_declared_bases"' in page.text
    assert 'Nota editorial sobre la base:' in page.text and PHRASE in page.text
    assert 'Declarado:' in page.text and domain_counts()==(0,0,0)
    assert row.review_json==frozen
    posted=client.post('/nutrition/import/'+row.public_id+'/decisions',
                       data={'revision':row.revision,'accept_declared_bases':'yes'})
    assert posted.status_code==302
    db.session.rollback()
    current=imports.owned(user,row.public_id)
    state=review.overview(current)
    assert state['counts']==dict(ready=18,decision=0,invalid=0,omitted=0)
    assert state['declared_basis_count']==0
    assert all(a['declaration']==b['declaration'] and a['original']==b['original']
               for a,b in zip(frozen['rows'],current.review_json['rows']))
    assert all(current.review_json['rows'][i]['basis_interpretation']['confirmed_by']=='user'
               for i in range(14))
    assert 'name="consent_consumed" value="yes" required checked' not in client.get(
        '/nutrition/import/'+current.public_id).text
    assert domain_counts()==(0,0,0)


@pytest.mark.parametrize('text',[
    'Valores nutricionales por 100 g.', 'Los nutrientes no corresponden a la porción consumida.',
    'Bases distintas según alimento.', 'Referencia de laboratorio desconocida.',
])
def test_ambiguous_text_never_gains_group_authority(app,client,user,text):
    row=start(app,user,fictional_document(text,count=1));login(client)
    view=review.overview(row)
    assert view['declared_basis_count']==17
    assert view['counts']==dict(ready=0,decision=18,invalid=0,omitted=0)
    assert view['records'][0]['item']['original']['declaration']['provenance']['basis_interpretation']==text
    assert client.get('/nutrition/import/'+row.public_id).status_code==200
    assert client.post('/nutrition/import/'+row.public_id+'/decisions',
             data={'revision':row.revision,'accept_declared_bases':'yes'}).status_code==302
    db.session.rollback()
    row=imports.owned(user,row.public_id)
    assert review.overview(row)['counts']==dict(ready=17,decision=1,invalid=0,omitted=0)
    assert row.review_json['rows'][0]['basis_interpretation']['status']=='proposed'
    assert domain_counts()==(0,0,0)


@pytest.mark.parametrize('annotation',[12,0,True,False,[],None,' ',{'status':[]},{'source_basis':[]},
    {'accepted_inputs':[]},{'source_inputs':True},{'explicit_inputs':{'amount':[]}},
    {'measurement_verified':[]},{'source_annotation':False},{'basis_unit':[]}])
def test_unsupported_metadata_is_422_without_orphan_or_500(app,client,user,annotation):
    app.config['NUTRITION_INTELLIGENCE_ENABLED']=True;login(client)
    doc=fictional_document(count=0)
    doc['data']['entries'][0]['declaration']['provenance']['basis_interpretation']=annotation
    validate_json_document(doc,'nutrition_import_2_1')
    response=client.post('/nutrition/import',
        data={'file':(io.BytesIO(json.dumps(doc).encode()),'QA invalid basis.json')})
    assert response.status_code==422
    assert 'Traceback' not in response.text and 'AttributeError' not in response.text
    assert 'basis_interpretation' in response.text
    assert db.session.query(UploadedFile).count()==0
    assert db.session.query(NutritionImportDraft).count()==0
    assert domain_counts()==(0,0,0)
    assert not any(p.is_file() for p in Path(app.config['UPLOAD_ROOT']).rglob('*'))


def test_text_and_object_basis_are_not_preconsented_by_file(app,client,user):
    row=start(app,user,fictional_document(count=14));login(client)
    state=review.overview(row)
    assert not any(r['item']['confirmed'] for r in state['records'])
    assert all(r['item']['basis_interpretation']['status']=='proposed'
               for r in state['records'])
    assert client.post('/nutrition/import/'+row.public_id+'/confirm',
                       data={'revision':row.revision,'token':'','consent_consumed':'yes'}).status_code==409
    assert domain_counts()==(0,0,0)


def source14(text=PHRASE):
    doc=fictional_document(text,count=18)
    doc['data']['entries']=doc['data']['entries'][:14]
    return doc


def test_exactly_14_text_annotations_preserve_all_30_values_and_totals(app,client,user):
    doc=source14();row=start(app,user,doc);login(client)
    assert review.overview(row)['declared_basis_count']==14
    assert client.post('/nutrition/import/'+row.public_id+'/decisions',data=dict(
        revision=row.revision,accept_declared_bases='yes')).status_code==302
    view=review.overview(row);assert view['counts']==dict(ready=14,decision=0,invalid=0,omitted=0)
    canonical=review.document(row);validate_json_document(canonical,'nutrition_import_2_1')
    for original,entry in zip(doc['data']['entries'],canonical['data']['entries']):
        assert entry['declaration']['nutrients']==validate_vector(original['declaration']['nutrients'])
        assert entry['declaration']['original_values']==original
        assert entry['declaration']['provenance']['basis_interpretation']['source_annotation']==PHRASE
    for key in NUTRIENTS:
        assert Decimal(view['batch_summary'][key]['value'])==sum(
            Decimal(e['declaration']['nutrients'][key]['value']) for e in doc['data']['entries'])
    assert domain_counts()==(0,0,0)


@pytest.mark.parametrize('note',['Valores por 100 g.','Valores nutricionales por 100 g.',
    'Los nutrientes no corresponden a la cantidad consumida.',
    'Nutrients do not correspond to the consumed quantity.'])
def test_affirmative_text_cannot_override_conflicting_evidence(app,client,user,note):
    doc=source14();doc['data']['entries'][0]['declaration']['provenance']['notes']=note
    row=start(app,user,doc);login(client);before=copy.deepcopy(row.review_json['rows'][0])
    assert review.overview(row)['declared_basis_count']==13
    assert client.post('/nutrition/import/'+row.public_id+'/decisions',data=dict(
        revision=row.revision,accept_declared_bases='yes')).status_code==302
    assert review.overview(row)['counts']==dict(ready=13,decision=1,invalid=0,omitted=0)
    assert row.review_json['rows'][0]==before and domain_counts()==(0,0,0)


def test_long_unknown_editorial_text_and_html_are_preserved_without_authority(app,client,user):
    text='<script>throw new Error("QA only")</script>\n'+('Nota editorial ficticia. '*240)
    row=start(app,user,source14(text));login(client)
    view=review.overview(row);assert view['declared_basis_count']==0
    assert all(r['item']['basis_interpretation']['source_annotation']==text for r in view['records'])
    page=client.get('/nutrition/import/'+row.public_id)
    assert page.status_code==200 and '&lt;script&gt;' in page.text and '<script>throw' not in page.text
    assert all(r['preview'] is None for r in view['records']) and domain_counts()==(0,0,0)


def test_historical_snapshot_text_preserves_quality_zero_and_qualifiers(app,user):
    doc=source14()
    vector=doc['data']['entries'][0]['declaration']['nutrients']
    vector['energy']['value']='0';vector['vitamin_d'].update(state='unknown',value=None)
    vector['iron'].update(state='trace',value=None)
    vector['zinc'].update(state='below_limit',value=None,limit='0.1')
    doc['data']['entries'][0]['declaration']['provenance']['quality']='estimated'
    entry=doc['data']['entries'][0]
    snapshot=imports.meal_snapshot(entry,[],'UTC')
    result=snapshot_summary(snapshot)
    assert len(result)==30 and result['energy']['value']=='0'
    assert all(result[k]['value'] is None for k in ['vitamin_d','iron','zinc'])
    assert 'estimated_source_declaration' in result['energy']['sources']
    assert snapshot['declared_nutrition']['nutrients']==vector
    assert snapshot['declared_nutrition']['provenance']['basis_interpretation']==PHRASE
    assert domain_counts()==(0,0,0)


def test_existing_raw_text_draft_readers_do_not_accept_or_mutate_it(app,user):
    from app.services.importers.nutrition_legacy_semantics import current,semantic_inputs,grouped,invalidate_changed
    from app.services.nutrition_import_basis import grouped as declared_grouped
    from app.services.nutrition_import_portions import sufficient,consumption
    row=start(app,user,source14());item=copy.deepcopy(row.review_json['rows'][0])
    item['basis_interpretation']=PHRASE;frozen=copy.deepcopy(item)
    assert current(item) is False and grouped(item) is False and declared_grouped(item) is False
    assert semantic_inputs(item)['kind']=='explicit_basis'
    consumption(item)
    with pytest.raises(NutritionError):sufficient(item)
    invalidate_changed(item);assert item==frozen
    data=copy.deepcopy(row.review_json);data['rows'][0]=item;row.review_json=data;db.session.commit()
    assert review.overview(row)['declared_basis_count']==14
    assert row.review_json['rows'][0]==frozen and domain_counts()==(0,0,0)


def test_late_failure_rolls_back_the_whole_new_draft_and_file(app,client,user,monkeypatch):
    app.config['NUTRITION_INTELLIGENCE_ENABLED']=True;login(client)
    original=imports._review_from_source
    def fail(*args,**kwargs):
        original(*args,**kwargs)
        raise NutritionError('QA controlled failure after draft flush')
    monkeypatch.setattr(imports,'_review_from_source',fail)
    response=client.post('/nutrition/import',data={'file':(io.BytesIO(json.dumps(source14()).encode()),'QA late failure.json')})
    assert response.status_code==422
    assert db.session.query(NutritionImportDraft).count()==db.session.query(UploadedFile).count()==0
    assert not any(p.is_file() for p in Path(app.config['UPLOAD_ROOT']).rglob('*'))
    assert domain_counts()==(0,0,0)


def test_failed_duplicate_keeps_preexisting_original(app,client,user):
    from werkzeug.datastructures import FileStorage
    from app.services.files import store_uploaded_file
    doc=source14();doc['data']['entries'][-1]['declaration']['provenance']['basis_interpretation']=False
    payload=json.dumps(doc).encode();upload,_=store_uploaded_file(
        FileStorage(stream=io.BytesIO(payload),filename='QA retained invalid metadata.json'),user)
    db.session.commit();uid=upload.id
    files={str(p):p.read_bytes() for p in Path(app.config['UPLOAD_ROOT']).rglob('*') if p.is_file()}
    app.config['NUTRITION_INTELLIGENCE_ENABLED']=True;login(client)
    response=client.post('/nutrition/import',data={'file':(io.BytesIO(payload),'QA duplicate invalid.json')})
    assert response.status_code==422 and db.session.get(UploadedFile,uid)
    assert files=={str(p):p.read_bytes() for p in Path(app.config['UPLOAD_ROOT']).rglob('*') if p.is_file()}
    assert db.session.query(NutritionImportDraft).count()==0 and domain_counts()==(0,0,0)


@pytest.mark.parametrize('exception',[None,'quantity','negated'])
def test_declared_total_annotation_requires_matching_quantities_and_positive_evidence(app,client,user,exception):
    text='Nutrientes expresados por la porción total declarada, sin escalar en la importación.'
    doc=source14(text)
    if exception=='quantity':doc['data']['entries'][-1]['declaration']['basis_amount']='100'
    if exception=='negated':doc['data']['entries'][-1]['declaration']['provenance']['basis_interpretation']='No son '+text
    row=start(app,user,doc);login(client)
    assert review.overview(row)['declared_basis_count']==(14 if exception is None else 13)
    assert client.post('/nutrition/import/'+row.public_id+'/decisions',data=dict(
        revision=row.revision,accept_declared_bases='yes')).status_code==302
    view=review.overview(row)
    assert view['counts']['ready']==(14 if exception is None else 13)
    assert view['counts']['decision']==(0 if exception is None else 1)
    for key in NUTRIENTS:
        assert Decimal(view['batch_summary'][key]['value'])==sum(Decimal(
            e['declaration']['nutrients'][key]['value']) for e in doc['data']['entries'][:view['counts']['ready']])
    assert domain_counts()==(0,0,0)


def test_nested_editorial_control_chain_is_controlled_422(app,client,user):
    value=PHRASE
    for _ in range(12):value={'source_annotation':value}
    test_unsupported_metadata_is_422_without_orphan_or_500(app,client,user,value)
