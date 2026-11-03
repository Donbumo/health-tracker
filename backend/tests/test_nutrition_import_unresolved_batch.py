"""Issue #38: fictional unresolved 1.0 imports; never use owner nutrition data."""
import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

from app.extensions import db
from app.models import FoodProduct, MealLog, NutritionImportReceipt
from app.services import nutrition_import as imports, nutrition_import_review as review
from app.services.importers.nutrition_legacy_semantics import manual_total_candidate
from app.services.nutrition_math import NutritionError
from app.services.validation import validate_json_document
from tests.conftest import login

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/nutrition'))
from qa_note_semantics_fixtures import source


def fictional_18():
    doc=source(1999)
    for meal, count in zip(doc['data']['meals'], (5, 5, 4, 4)):
        meal['items']=meal['items'][:count]
        for food in meal['items']:
            # Unsupported editorial field means no 1.0 schema inference. The
            # values still exist, but must not silently become consumed totals.
            food['synthetic_extension_for_qa']='unrecognized 1.0'
    assert sum(len(meal['items']) for meal in doc['data']['meals'])==18
    return doc


def begin(app,user,doc=None):
    app.config['NUTRITION_INTELLIGENCE_ENABLED']=True
    payload=json.dumps(doc or fictional_18(),sort_keys=True).encode()
    row=imports.start(user,payload,'QA entirely fictional 18.json')
    db.session.commit()
    assert row.source_sha256==hashlib.sha256(payload).hexdigest()
    return row


def domain_counts():
    return (db.session.query(MealLog).count(),
            db.session.query(FoodProduct).count(),
            db.session.query(NutritionImportReceipt).count())


def test_18_show_declared_values_but_no_unconfirmed_intake(app,client,user):
    row=begin(app,user);login(client)
    frozen=copy.deepcopy(row.review_json)
    view=review.overview(row)
    assert view['counts']==dict(ready=0,decision=18,invalid=0,omitted=0)
    assert view['legacy_total_count']==0
    assert view['manual_total_count']==18
    assert all(record['preview'] is None for record in view['records'])
    assert all(record['declared_pending'] for record in view['records'])
    assert all(record['item']['declaration']['energy']['value']=='200' for record in view['records'])
    assert view['batch_summary']['energy']['value'] is None
    page=client.get('/nutrition/import/'+row.public_id)
    assert page.status_code==200
    assert page.text.count('Declarado:')>=72
    assert 'sin contabilizar' in page.text
    assert 'name="accept_unresolved_totals"' in page.text
    assert 'name="consent_consumed" value="yes" required checked' not in page.text
    assert row.review_json==frozen and domain_counts()==(0,0,0)


def test_one_explicit_batch_attestation_recovers_18_without_writing_consumptions(app,client,user):
    row=begin(app,user);login(client)
    frozen=copy.deepcopy(row.review_json)
    original_sha=row.source_sha256
    before_revision=row.revision
    result=client.post('/nutrition/import/'+row.public_id+'/decisions',
        data=dict(revision=before_revision,accept_unresolved_totals='yes'))
    assert result.status_code==302
    db.session.rollback()
    row=imports.owned(user,row.public_id)
    view=review.overview(row)
    assert row.revision==before_revision+1
    assert view['counts']==dict(ready=18,decision=0,invalid=0,omitted=0)
    assert view['manual_total_count']==0
    assert view['batch_summary']['energy']['value']=='3600'
    assert view['batch_summary']['protein']['value']=='180'
    assert all(record['preview']['energy']['value']=='200' for record in view['records'])
    assert all(original['original']==updated['original']
        for original,updated in zip(frozen['rows'],row.review_json['rows']))
    assert row.source_sha256==original_sha
    canonical=review.document(row)
    validate_json_document(canonical,'nutrition_import_2_1')
    page=client.get('/nutrition/import/'+row.public_id)
    assert '>Guardar todo</button>' in page.text
    assert 'name="consent_consumed" value="yes" required checked' not in page.text
    assert domain_counts()==(0,0,0)
    replay=client.post('/nutrition/import/'+row.public_id+'/decisions',
        data=dict(revision=before_revision,accept_unresolved_totals='yes'))
    assert replay.status_code==409
    assert domain_counts()==(0,0,0)


def test_true_exception_is_not_approved_by_batch_checkbox(app,client,user):
    doc=fictional_18()
    # A specific source row says its values are per 100 g. The checkbox must
    # not overwrite that conflicting evidence with the consumed quantity.
    doc['data']['meals'][0]['items'][0]['notes']='Valores por 100 g; QA conflicto.'
    row=begin(app,user,doc);login(client)
    before=copy.deepcopy(row.review_json['rows'][0])
    assert review.overview(row)['manual_total_count']==17
    response=client.post('/nutrition/import/'+row.public_id+'/decisions',
        data=dict(revision=row.revision,accept_unresolved_totals='yes'))
    assert response.status_code==302
    db.session.rollback()
    row=imports.owned(user,row.public_id);state=review.overview(row)
    assert state['counts']==dict(ready=17,decision=1,invalid=0,omitted=0)
    assert state['batch_summary']['energy']['state']=='partial'
    assert state['batch_summary']['energy']['value']=='3400'
    assert row.review_json['rows'][0]==before
    assert domain_counts()==(0,0,0)
    assert 'disabled' in client.get('/nutrition/import/'+row.public_id).text


def test_file_level_conflict_never_offers_group_attestation(app,client,user):
    doc=fictional_18()
    doc['data']['notes']='Los valores no son aportes consumidos.'
    row=begin(app,user,doc);login(client)
    state=review.overview(row)
    assert state['file_issues'] and state['manual_total_count']==0
    page=client.get('/nutrition/import/'+row.public_id)
    assert 'name="accept_unresolved_totals"' not in page.text
    result=client.post('/nutrition/import/'+row.public_id+'/decisions',
        data=dict(revision=row.revision,accept_unresolved_totals='yes'))
    assert result.status_code==422
    assert domain_counts()==(0,0,0)


def test_only_unresolved_owner_attestable_without_pretending_schema_validity(app,user):
    row=begin(app,user)
    item=review.prepared(row)['rows'][0]
    assert item['basis_interpretation']['origin']=='unrecognized_daily_nutrition'
    assert manual_total_candidate(item)
    assert not manual_total_candidate(dict(item,basis_unit='g'))
    assert not manual_total_candidate(dict(item,resolution='catalog'))
    assert not manual_total_candidate(dict(item,portion_conflict='QA contradiction'))
    assert not manual_total_candidate(dict(item,carbohydrate_proposal={'value':'1'}))
    assert not manual_total_candidate(dict(item,amount='not a number'))
    # Correct schema inference was deliberately not enabled by this change.
    assert not any(review.prepared(row)['rows'][0].get(k) for k in ('basis_amount','resolution'))


def test_legacy_strict_group_does_not_regress(app,user):
    doc=source(5000)
    row=begin(app,user,doc)
    view=review.overview(row)
    assert view['legacy_total_count']==23
    assert view['manual_total_count']==0
    assert view['counts']['decision']==23
