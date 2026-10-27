"""Review closeout: invented files only, expired recovery and no catalog IDs."""
import copy
import json
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import event
from app.extensions import db
from app.models import User, UploadedFile, NutritionImportDraft, NutritionPlan, NutritionImportReceipt, MealLog
from app.services import nutrition_import as imports, nutrition_import_review as compact, food_catalog as catalog
from app.services.nutrition_math import NutritionError
from tests.conftest import login
from tests.test_nutrition_import_summary import batch, token, FIXTURES


def test_expiry_listing_direct_get_recovery_and_idempotence(app, client, user, batch):
    row, _, payload = batch
    compact.save_decisions(user, row.public_id, row.revision, {'r12_carbohydrate': 'unknown'})
    row.created_at -= timedelta(days=2)
    db.session.commit()
    before = copy.deepcopy(row.review_json); created = row.created_at
    login(client)
    def read_guard(conn,cursor,stmt,params,context,many):
        assert stmt.lstrip().split()[0].upper() not in {'INSERT','UPDATE','DELETE','REPLACE','CREATE','ALTER','DROP','TRUNCATE'}
    event.listen(db.engine,'before_cursor_execute',read_guard)
    try:
        listing = client.get('/nutrition/import').text
        assert 'Revisiones vencidas o sin original' in listing and 'retomar revisión vigente' not in listing
        page = client.get('/nutrition/import/' + row.public_id)
    finally:event.remove(db.engine,'before_cursor_execute',read_guard)
    assert page.status_code == 200 and 'REVISIÓN VENCIDA' in page.text
    assert 'Crear revisión nueva desde el original' in page.text and 'Confirmar y guardar' not in page.text
    assert row.review_json == before and row.created_at == created
    path = '/nutrition/import/' + row.public_id + '/recover'
    response = client.post(path, data={'revision': row.revision})
    assert response.status_code == 302
    fresh = imports.owned(user, response.location.rsplit('/', 1)[1])
    assert fresh.id != row.id and fresh.source_sha256 == row.source_sha256
    assert fresh.source_json['upload_id'] == row.source_json['upload_id']
    assert fresh.source_json['recovered_from'] == row.public_id
    assert not fresh.review_json['rows'][12].get('carbohydrate_reviewed')
    assert imports.review_status(fresh)['can_resume'] and imports.review_status(row)['expired']
    assert row.created_at == created and row.review_json == before
    assert client.post(path, data={'revision': row.revision}).location == response.location
    assert imports.start(user, payload, 'QA reupload original.json').id == fresh.id
    assert db.session.query(NutritionImportDraft).count() == 2
    assert db.session.query(NutritionPlan).count() == db.session.query(NutritionImportReceipt).count() == 0


def test_recovery_csrf_owner_integrity_and_fresh_rejection(app, client, user, batch):
    row, _, _ = batch; login(client)
    path = '/nutrition/import/' + row.public_id + '/recover'
    assert client.post(path, data={'revision': row.revision}).status_code == 409
    row.created_at -= timedelta(days=2); db.session.commit()
    app.config['WTF_CSRF_ENABLED'] = True
    assert client.post(path, data={'revision': row.revision}).status_code == 400
    app.config['WTF_CSRF_ENABLED'] = False
    other = User(username='QA recovery other', role='user'); other.set_password('QA fictional')
    db.session.add(other); db.session.commit()
    with pytest.raises(NutritionError) as denied: imports.recover(other.id, row.public_id, row.revision)
    assert denied.value.status == 404
    original = db.session.get(UploadedFile, row.source_json['upload_id'])
    file = Path(app.config['DATA_ROOT']) / original.storage_path
    saved = file.read_bytes(); file.write_bytes(saved + b' QA tampered')
    assert client.post(path, data={'revision': row.revision}).status_code == 409
    assert db.session.query(NutritionImportDraft).count() == 1
    file.write_bytes(saved)
    with pytest.raises(NutritionError): imports.recover(user, row.public_id, row.revision + 1)


@pytest.fixture
def representative(app, user):
    app.config['NUTRITION_INTELLIGENCE_ENABLED'] = True
    catalog.stage(json.loads((FIXTURES / 'representative-catalog.json').read_text(encoding='utf-8')))
    catalog.activate('qa_diet_closeout', '1', 1); db.session.commit()
    row = imports.start(user, (FIXTURES / 'representative-plan.csv').read_bytes(), 'QA plan sin referencias.csv')
    db.session.commit()
    refs = {h['source_food_id']: h['ref'] for h in catalog.search(user, source='qa_diet_closeout')}
    return row, refs


def test_representative_no_ids_partial_decisions_resume_global_save(app, client, user, representative):
    row, refs = representative; login(client)
    assert row.review_json['destination'] == 'plan'
    assert compact.overview(row)['counts'] == dict(ready=0, decision=6, invalid=0, omitted=0)
    first = {f'r{i}_p-1_ref': refs[str(i % 3 + 1)] for i in range(3)}
    assert client.post('/nutrition/import/' + row.public_id + '/decisions', data=dict(first, revision=row.revision)).status_code == 302
    assert compact.overview(row)['counts']['ready'] == 3
    assert db.session.query(NutritionPlan).count() == db.session.query(MealLog).count() == 0
    assert imports.start(user, (FIXTURES / 'representative-plan.csv').read_bytes(), 'QA resume.csv').id == row.id
    second = {f'r{i}_p-1_ref': refs[str(i % 3 + 1)] for i in range(3, 6)}
    assert client.post('/nutrition/import/' + row.public_id + '/decisions', data=dict(second, revision=row.revision)).status_code == 302
    assert compact.overview(row)['counts']['ready'] == 6
    response = client.post('/nutrition/import/' + row.public_id + '/confirm', data={'revision': row.revision, 'token': token(client, row)})
    assert response.status_code == 200 and len(db.session.query(NutritionPlan).one().snapshot_json['meals']) == 6
    assert db.session.query(MealLog).count() == 0


def test_representative_insufficient_quantity_preserves_block(app, user, representative):
    _, refs = representative
    row = imports.start(user, (FIXTURES / 'representative-insufficient.csv').read_bytes(), 'QA missing quantity.csv')
    db.session.commit()
    fields = {f'r{i}_p-1_ref': refs[str(i % 3 + 1)] for i in range(5)}
    compact.save_decisions(user, row.public_id, row.revision, fields); db.session.commit()
    assert compact.overview(row)['counts']['ready'] == 5 and compact.overview(row)['counts']['decision'] == 1
    with pytest.raises(NutritionError): compact.document(row)
    assert db.session.query(NutritionPlan).count() == db.session.query(MealLog).count() == db.session.query(NutritionImportReceipt).count() == 0
