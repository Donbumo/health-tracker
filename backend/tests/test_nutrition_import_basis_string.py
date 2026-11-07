"""Issue #40: fictional 2.1 strings are evidence, not internal decisions."""
import copy
import io
import json
import sys
from pathlib import Path

import pytest

from app.extensions import db
from app.models import FoodProduct, MealLog, NutritionImportDraft, NutritionImportReceipt, UploadedFile
from app.services import nutrition_import as imports, nutrition_import_review as review
from app.services.validation import validate_json_document
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


@pytest.mark.parametrize('annotation',[12,True,[],None,' ',{'status':[]},{'source_basis':[]}])
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
    assert not list(Path(app.config['UPLOAD_ROOT']).rglob('*'))


def test_text_and_object_basis_are_not_preconsented_by_file(app,client,user):
    row=start(app,user,fictional_document(count=14));login(client)
    state=review.overview(row)
    assert not any(r['item']['confirmed'] for r in state['records'])
    assert all(r['item']['basis_interpretation']['status']=='proposed'
               for r in state['records'])
    assert client.post('/nutrition/import/'+row.public_id+'/confirm',
                       data={'revision':row.revision,'token':'','consent_consumed':'yes'}).status_code==409
    assert domain_counts()==(0,0,0)
