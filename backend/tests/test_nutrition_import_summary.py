"""Fictional 10 ready + 3 exceptions: batch consent, ownership and receipts."""
import copy
import io
import json
import re
from pathlib import Path
from html import unescape
from datetime import timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import event
from itsdangerous import TimestampSigner
from app.extensions import db
from app.models import User, FoodProduct, MealLog, NutritionPlan, NutritionImportReceipt, NutritionImportDraft
from app.services import food_catalog as catalog, nutrition_import as imports, nutrition_import_review as compact
from app.services.nutrition_math import NutritionError
from tests.conftest import login

FIXTURES = Path(__file__).resolve().parents[2] / 'examples/qa/nutrition-import-ux'


@pytest.fixture
def batch(app, user):
    app.config['NUTRITION_INTELLIGENCE_ENABLED'] = True
    catalog.stage(json.loads((FIXTURES / 'catalog.json').read_text(encoding='utf-8')))
    catalog.activate('qa_import_ux', '1', 1)
    db.session.commit()
    payload = (FIXTURES / 'mixed-13.json').read_bytes()
    row = imports.start(user, payload, 'QA mixed-13.json')
    db.session.commit()
    refs = {h['source_food_id']: h['ref'] for h in catalog.search(user, source='qa_import_ux')}
    return row, refs, payload


def decisions(refs):
    return {'r10_p0_amount': '100', 'r10_p0_unit': 'g', 'r11_p1_ref': refs['2'],
            'r11_p1_amount': '100', 'r11_p1_unit': 'g', 'r12_carbohydrate': 'unknown'}


def ready(batch, user):
    row, refs, _ = batch
    compact.save_decisions(user, row.public_id, row.revision, decisions(refs))
    db.session.commit()
    return row


def token(client, row):
    page = client.get('/nutrition/import/' + row.public_id)
    assert page.status_code == 200
    return unescape(re.search(r'name="token" value="([^"]+)"', page.text)[1])


def test_classification_exact_values_and_exceptions_only(app, user, batch):
    row, _, _ = batch
    before = copy.deepcopy(row.review_json)
    view = compact.overview(row)
    assert view['counts'] == {'ready': 10, 'decision': 3, 'invalid': 0, 'omitted': 0}
    assert all(not item['confirmed'] for item in row.review_json['rows'])
    assert len(view['review']['rows'][0]['ingredients']) == 2
    assert view['review']['rows'][0]['declaration']['energy']['value'] == '200'
    assert row.review_json == before
    assert db.session.query(FoodProduct).count() == db.session.query(MealLog).count() == 0
    with pytest.raises(NutritionError):
        compact.document(row, view)


def test_three_screens_global_confirm_replay_and_resume(app, client, user, batch):
    row, refs, payload = batch
    login(client)
    page = client.get('/nutrition/import/' + row.public_id)
    assert 'PASO 2 DE 3' in page.text and 'Guardar identificación' not in page.text
    assert page.text.count('class="ni-import-exception"') == 3
    assert 'Confirmar identidad, cantidad y datos' not in page.text
    assert 'Revisiones vigentes' in client.get('/nutrition/import').text
    response = client.post('/nutrition/import', data={'file': (io.BytesIO(payload), 'QA renamed.json')})
    assert response.location.endswith(row.public_id) and db.session.query(NutritionImportDraft).count() == 1
    response = client.post('/nutrition/import/' + row.public_id + '/decisions', data=dict(decisions(refs), revision=row.revision))
    assert response.status_code == 302 and compact.overview(row)['counts']['ready'] == 13
    signed = token(client, row)
    data = {'revision': row.revision, 'token': signed, 'user_id': user + 999}
    response = client.post('/nutrition/import/' + row.public_id + '/confirm', data=data)
    assert response.status_code == 200 and '13 registros del archivo guardados' in response.text
    assert len(db.session.query(NutritionPlan).one().snapshot_json['meals']) == 13
    assert db.session.query(NutritionImportReceipt).count() == 1
    assert db.session.query(MealLog).count() == 0
    assert client.post('/nutrition/import/' + row.public_id + '/confirm', data=data).status_code == 200
    assert db.session.query(NutritionPlan).count() == 1
    response = client.post('/nutrition/import', data={'file': (io.BytesIO(payload), 'QA duplicate.json')})
    assert client.get(response.location).status_code == 200 and db.session.query(NutritionPlan).count() == 1


def test_get_no_dml_owner_csrf_signature(app, client, user, batch):
    row, _, _ = batch
    login(client)
    def guard(conn, cursor, stmt, params, context, many):
        assert stmt.lstrip().split()[0].upper() not in {'INSERT', 'UPDATE', 'DELETE', 'REPLACE', 'CREATE', 'ALTER', 'DROP', 'TRUNCATE'}
    event.listen(db.engine, 'before_cursor_execute', guard)
    try:
        for path in ['/nutrition/import', '/nutrition/import/' + row.public_id, '/nutrition/import/' + row.public_id + '?step=4&q=QA']:
            response = client.get(path)
            assert response.status_code == 200 and response.headers['Cache-Control'] == 'private, no-store'
    finally:
        event.remove(db.engine, 'before_cursor_execute', guard)
    ready(batch, user)
    signed = token(client, row)
    assert client.post('/nutrition/import/' + row.public_id + '/confirm', data={'revision': row.revision, 'token': signed + 'bad'}).status_code == 409
    app.config['WTF_CSRF_ENABLED'] = True
    assert client.post('/nutrition/import/' + row.public_id + '/decisions', data={'revision': row.revision}).status_code == 400
    app.config['WTF_CSRF_ENABLED'] = False
    other = User(username='QA import other owner', role='user')
    other.set_password('QA fictional')
    db.session.add(other)
    db.session.commit()
    with client.session_transaction() as session:
        session['_user_id'] = str(other.id)
    from flask import g
    g.pop('_login_user', None)
    assert client.get('/nutrition/import/' + row.public_id).status_code == 404
    assert client.post('/nutrition/import/' + row.public_id + '/decisions', data={'revision': row.revision}).status_code == 404
    assert client.post('/nutrition/import/' + row.public_id + '/confirm', data={'revision': row.revision, 'token': signed}).status_code == 404
    assert db.session.query(NutritionPlan).count() == 0


def test_stale_expired_reviews(app, client, user, batch):
    row = ready(batch, user)
    login(client)
    signed = token(client, row)
    revision = row.revision
    compact.save_decisions(user, row.public_id, row.revision, {})
    db.session.commit()
    assert client.post('/nutrition/import/' + row.public_id + '/confirm', data={'revision': revision, 'token': signed}).status_code == 409
    moment = TimestampSigner.get_timestamp(None)
    with patch.object(TimestampSigner, 'get_timestamp', lambda self: moment - 901):
        expired = token(client, row)
    assert client.post('/nutrition/import/' + row.public_id + '/confirm', data={'revision': row.revision, 'token': expired}).status_code == 409
    row.created_at -= timedelta(days=2)
    db.session.commit()
    assert client.post('/nutrition/import/' + row.public_id + '/decisions', data={'revision': row.revision}).status_code == 409
    assert db.session.query(NutritionPlan).count() == 0


def test_changed_identity_and_percent_never_promoted(app, user, batch):
    row, _, _ = batch
    review = copy.deepcopy(row.review_json)
    review['rows'][0]['ingredient_proposals'][0]['original']['preparation'] = 'QA raw'
    review['rows'][1]['ingredient_proposals'][0]['original']['revision'] = '999'
    review['rows'][2]['ingredient_proposals'][0]['original']['source'] = {'malformed': True}
    review['rows'][3]['declaration']['iron'] = {'state': 'known', 'value': '10', 'unit': '% DV'}
    row.review_json = review
    db.session.commit()
    assert compact.overview(row)['counts']['decision'] == 7
    compact.save_decisions(user, row.public_id, row.revision, {'r3_nutrient_iron_action': 'unknown'})
    db.session.commit()
    assert 'iron' not in row.review_json['rows'][3]['declaration']
    assert compact.overview(row)['records'][3]['state'] == 'ready'


def test_atomic_rollback_and_audit_gap(app, client, user, batch, monkeypatch):
    row = ready(batch, user)
    login(client)
    signed = token(client, row)
    original = imports.apply_document
    def fail_after_write(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('QA fictional forced failure')
    monkeypatch.setattr(imports, 'apply_document', fail_after_write)
    response = client.post('/nutrition/import/' + row.public_id + '/confirm', data={'revision': row.revision, 'token': signed})
    assert response.status_code == 409 and row.state == 'pending'
    assert db.session.query(NutritionPlan).count() == db.session.query(NutritionImportReceipt).count() == 0
    monkeypatch.undo()
    from app.services.import_audit import ImportAuditService
    original_pending = ImportAuditService.record_pending
    def change_after_pending(self, *args, **kwargs):
        result = original_pending(self, *args, **kwargs)
        row.revision += 1
        db.session.commit()
        return result
    monkeypatch.setattr(ImportAuditService, 'record_pending', change_after_pending)
    signed = token(client, row)
    response = client.post('/nutrition/import/' + row.public_id + '/confirm', data={'revision': row.revision, 'token': signed})
    assert response.status_code == 409 and db.session.query(NutritionPlan).count() == 0


def test_explicit_product_basis_zero_trace_and_limit(app, client, user, batch):
    data = {'products': [{'name': 'QA explicit ml definition', 'basis_amount': '100', 'basis_unit': 'ml',
        'nutrients': {'vitamin_d': {'state': 'known', 'value': '0', 'unit': 'ug'},
                      'iron': {'state': 'trace', 'value': None, 'unit': 'mg'},
                      'zinc': {'state': 'below_limit', 'value': None, 'limit': '0.1', 'unit': 'mg'}}}]}
    row = imports.start(user, json.dumps(data).encode(), 'QA explicit product.json')
    db.session.commit()
    assert compact.overview(row)['counts']['ready'] == 1
    login(client)
    response = client.post('/nutrition/import/' + row.public_id + '/confirm', data={'revision': row.revision, 'token': token(client, row)})
    assert response.status_code == 200
    food = db.session.query(FoodProduct).one()
    assert food.nutrition_json['basis_unit'] == 'ml'
    assert food.nutrition_json['nutrients']['vitamin_d']['value'] == '0'
    assert food.nutrition_json['nutrients']['iron']['state'] == 'trace'
    assert food.nutrition_json['nutrients']['zinc']['limit'] == '0.1'
    assert food.calories_per_100g is None


def test_consumption_consent_conflicts_and_frozen_history(app, client, user, batch):
    row = ready(batch, user)
    compact.save_decisions(user, row.public_id, row.revision, {'destination': 'consumed'})
    db.session.commit()
    login(client)
    signed = token(client, row)
    data = {'revision': row.revision, 'token': signed}
    assert client.post('/nutrition/import/' + row.public_id + '/confirm', data=data).status_code == 422
    assert db.session.query(MealLog).count() == 0
    response = client.post('/nutrition/import/' + row.public_id + '/confirm', data=dict(data, consent_consumed='yes'))
    assert response.status_code == 200 and row.state == 'completed'
    assert db.session.query(MealLog).count() == 13
    frozen = [copy.deepcopy(log.snapshot_json) for log in db.session.query(MealLog).order_by(MealLog.id)]
    # A different file on dates that already contain data must remain blocked.
    source = json.loads(batch[2]);source['plan'][0]['name'] = 'QA distinct file'
    another = imports.start(user, json.dumps(source).encode(), 'QA different file.json')
    db.session.commit()
    compact.save_decisions(user, another.public_id, another.revision, dict(decisions(batch[1]), destination='consumed'))
    db.session.commit()
    assert compact.overview(another)['counts']['decision'] == 13
    assert frozen == [log.snapshot_json for log in db.session.query(MealLog).order_by(MealLog.id)]


def test_unsupported_and_missing_original_stay_blocked(app, client, user, batch):
    row, _, _ = batch
    data = copy.deepcopy(row.review_json)
    data['rows'][0]['unsupported_vector'] = True
    row.review_json = data
    db.session.commit()
    assert compact.overview(row)['counts']['invalid'] == 1
    from app.models import UploadedFile
    db.session.delete(db.session.get(UploadedFile, row.source_json['upload_id']))
    db.session.commit()
    with pytest.raises(NutritionError, match='original'):
        imports.assert_pending(row, row.revision)
    empty = imports.start(user, b'QA texto ficticio sin tabla ni ingredientes.', 'QA no records.txt')
    db.session.commit()
    login(client)
    assert 'No se detectaron registros importables' in client.get('/nutrition/import/' + empty.public_id).text


def test_partial_review_decisions_resume_without_any_domain_import(app, user, batch):
    row, _, payload = batch
    compact.save_decisions(user, row.public_id, row.revision, {'r12_carbohydrate': 'unknown',
        'r10_p0_amount': '', 'r10_p0_unit': 'g', 'r11_p1_ref': '', 'r11_p1_amount': '100', 'r11_p1_unit': 'g'})
    db.session.commit()
    assert compact.overview(row)['counts']['ready'] == 11
    assert compact.overview(row)['counts']['decision'] == 2
    assert imports.start(user, payload, 'QA resume.json').id == row.id
    assert row.review_json['rows'][12]['carbohydrate_reviewed'] is True
    assert db.session.query(NutritionImportReceipt).count() == db.session.query(NutritionPlan).count() == 0


def test_ambiguous_parent_quantity_cannot_silently_disappear(app, user, batch):
    source=json.loads(batch[2]);source['plan']=source['plan'][:1];source['plan'][0]['amount']='1,000'
    row=imports.start(user,json.dumps(source).encode(),'QA ambiguous parent.json');db.session.commit()
    assert compact.overview(row)['counts']['decision']==1
    compact.save_decisions(user,row.public_id,row.revision,{'r0_amount':'200'});db.session.commit()
    assert compact.overview(row)['counts']['ready']==1
