"""Synthetic HTNX data through the existing review, writer, export and restore."""

import copy
import io
import json
from decimal import Decimal
from pathlib import Path

from app.extensions import db
from app.models import FoodProduct, MealLog, NutritionImportDraft, NutritionImportReceipt, UploadedFile, User
from app.services import nutrition_import as imports
from app.services import nutrition_import_review as compact
from app.services.account_restore import AccountRestoreService
from app.services.backups import AccountBackupService, BackupRestoreCoordinator, resolve_uploaded_download
from app.services.exporters.user_data import build_user_data_document
from app.services.importers.nutrition_exchange.intake import parse
from app.services.importers.nutrition_exchange.normalize import Equivalence, FoodDecision
from app.services.importers.nutrition_exchange.projection import project
from app.services.nutrition_portability import export_bundle
from app.services.validation import validate_json_document
from tests.conftest import login
from tests.test_full_backup import _stage
from tests.test_nutrition_import_source_21 import app  # SQLite or guarded MariaDB 0046
from tests.test_nutrition_import_summary import token


FIXTURES = Path(__file__).resolve().parents[2] / 'examples/qa/nutrition-exchange'


def _enable(app):
    app.config.update(NUTRITION_INTELLIGENCE_ENABLED=True, NUTRITION_EXCHANGE_QA_ENABLED=True)


def _upload(client, user, payload):
    response = client.post('/nutrition/import',
        data={'file': (io.BytesIO(payload), 'QA ficticia HTNX.json')})
    assert response.status_code == 302
    return imports.owned(user, response.location.rsplit('/', 1)[-1])


def _counts(user):
    return tuple(db.session.query(model).filter_by(user_id=user).count()
                 for model in (MealLog, FoodProduct, NutritionImportReceipt))


def test_exchange_sparse_vector_source_evidence_and_original_survive_zip_round_trip(app, client, user):
    _enable(app)
    login(client)
    document = json.loads((FIXTURES / 'valid-explicit.json').read_bytes())
    document['meals'][3].update(type='breakfast', name='Segunda comida ficticia')
    food = document['meals'][3]['foods'][0]
    # These are the same label under NFC/trim, with different original bytes.
    food['quantity']['label'] = '  galleta de cafe\u0301  '
    food['nutrition']['basis']['label'] = 'galleta de café'
    food['nutrition']['values'].update({
        'protein': {'state': 'unknown'},
        'sodium': {'state': 'trace', 'unit': 'mg'},
        'zinc': {'state': 'below_limit', 'limit': '0.25', 'unit': 'mg'},
        'vitamin_c': {'value': 0.125, 'unit': 'mg', 'quality': 'estimated', 'source': 'Referencia QA'},
    })
    payload = json.dumps(document, ensure_ascii=False).encode()
    parsed = parse(payload)
    parsed_food = parsed.batch.meals[3].foods[0]
    original_keys = set(food['nutrition']['values'])
    assert set(parsed_food.nutrition.values) == original_keys
    assert parsed_food.nutrition.values['protein'].evidence.raw == {'state': 'unknown'}
    assert parsed_food.nutrition.values['fiber'].value == Decimal(0)
    assert parsed_food.nutrition.values['vitamin_c'].value == Decimal('0.125')
    assert 'carbohydrate_total' not in original_keys

    row = _upload(client, user, payload)
    draft_state = copy.deepcopy(row.review_json)
    view = compact.overview(row)
    assert view['counts'] == {'ready': 4, 'decision': 0, 'invalid': 0, 'omitted': 0}
    assert len(view['groups']) == 4
    assert view['groups'][3]['meal'] == 'Segunda comida ficticia'
    assert Decimal(view['batch_summary']['energy']['value']) == Decimal('570.125')
    assert all(not item['confirmed'] for item in row.review_json['rows'])
    assert row.review_json == draft_state
    assert _counts(user) == (0, 0, 0)

    canonical = project(row)
    validate_json_document(canonical, 'nutrition_import_2_1')
    entries = canonical['data']['entries']
    assert [entry['name'] for entry in entries] == [meal.foods[0].name for meal in parsed.batch.meals]
    assert len(entries[0]['declaration']['nutrients']) == 30
    assert entries[3]['bindings'] == []
    assert entries[3]['portion_unit'] == 'portion'
    declaration = entries[3]['declaration']
    assert declaration['basis_amount'] == '1'
    assert declaration['basis_unit'] == 'portion'
    assert set(declaration['nutrients']) == original_keys
    evidence = declaration['provenance']['source_provenance']
    assert evidence['authority'] == 'dish'
    assert evidence['meal']['path'] == '/meals/3'
    assert evidence['food']['quantity']['unit'] == 'piece'
    assert evidence['food']['quantity']['evidence']['raw']['label'] == food['quantity']['label']
    assert evidence['food']['nutrition']['basis']['unit'] == 'piece'
    assert evidence['food']['nutrition']['basis']['evidence']['raw']['label'] == food['nutrition']['basis']['label']
    observations = evidence['food']['nutrition']['observations']
    assert set(observations) == original_keys
    assert observations['protein']['evidence']['raw'] == {'state': 'unknown'}
    assert observations['vitamin_c']['evidence']['path'] == '/meals/3/foods/0/nutrition/values/vitamin_c'
    assert observations['vitamin_c']['evidence']['source'] == 'Referencia QA'
    assert observations['vitamin_c']['evidence']['raw']['value'] == '0.125'
    assert observations['vitamin_c']['evidence']['decimal_paths'] == ['/value']

    confirm = '/nutrition/import/' + row.public_id + '/confirm'
    fields = {'revision': row.revision, 'token': token(client, row)}
    assert client.post(confirm, data=fields).status_code == 422
    assert _counts(user) == (0, 0, 0)
    fields['consent_consumed'] = 'yes'
    assert client.post(confirm, data=fields).status_code == 200
    assert client.post(confirm, data=fields).status_code == 200
    assert _counts(user) == (4, 0, 1)

    log = db.session.query(MealLog).filter_by(user_id=user).order_by(MealLog.id.desc()).first()
    snapshot = log.snapshot_json
    declared = snapshot['declared_nutrition']
    assert declared['provenance']['source_provenance'] == evidence
    assert declared['provenance']['original_basis']['nutrients'] == declaration['nutrients']
    assert set(declared['nutrients']) == original_keys
    assert declared['nutrients']['protein']['state'] == 'unknown'
    assert declared['nutrients']['sodium']['state'] == 'trace'
    assert Decimal(declared['nutrients']['zinc']['limit']) == Decimal('0.5')
    assert declared['nutrients']['zinc']['state'] == 'below_limit'
    assert declared['nutrients']['fiber']['state'] == 'known'
    assert Decimal(declared['nutrients']['fiber']['value']) == 0
    assert Decimal(declared['nutrients']['vitamin_c']['value']) == Decimal('0.25')
    assert declared['provenance']['nutrient_quality']['vitamin_c'] == 'estimated'
    assert Decimal(snapshot['summary']['energy']['value']) == 60
    assert snapshot['summary']['carbohydrate_total']['value'] is None

    account = db.session.get(User, user)
    bundle = build_user_data_document(account, user)['data']['nutrition_intelligence'][0]
    assert bundle['logs'][3]['snapshot'] == snapshot
    assert bundle['receipts'][0]['document'] == canonical
    soup = bundle['logs'][1]['snapshot']['declared_nutrition']['provenance']['source_provenance']['food']
    assert soup['nutrition']['additional_nutrients'][0]['name'] == 'Cromo'
    assert [ingredient['name'] for ingredient in soup['ingredients']] == ['Agua de QA', 'Vegetal de QA']
    assert bundle['logs'][1]['snapshot']['ingredients'] == []

    backups = AccountBackupService()
    archive = backups.resolve_download(backups.create(account, user_id=user), user_id=user)
    target = User(username='qa-htnx-restored', role='user')
    target.set_password('synthetic-password')
    db.session.add(target)
    db.session.commit()
    coordinator = BackupRestoreCoordinator()
    staging_id = _stage(archive, coordinator, target.id)
    preview = coordinator.preview(staging_id=staging_id, user_id=target.id)
    assert _counts(target.id) == (0, 0, 0)
    assert coordinator.confirm(staging_id=staging_id, user_id=target.id,
                               confirmation_token=preview['confirmation_token'])['committed']
    restored = export_bundle(target.id)
    assert [row['snapshot'] for row in restored['logs']] == [row['snapshot'] for row in bundle['logs']]
    assert restored['receipts'][0]['document'] == dict(canonical, user_id=target.id)
    assert _counts(target.id) == (4, 0, 1)
    assert db.session.query(NutritionImportDraft).filter_by(user_id=target.id).count() == 0
    restored_original = db.session.query(UploadedFile).filter_by(user_id=target.id).one()
    assert resolve_uploaded_download(restored_original, user_id=target.id).read_bytes() == payload


def test_exchange_ingredient_authority_projects_one_sparse_plate(app, client, user):
    _enable(app)
    login(client)
    document = json.loads((FIXTURES / 'valid-needs-review.json').read_bytes())
    document['destination'] = 'consumed'
    document['meals'] = document['meals'][1:]
    payload = json.dumps(document, ensure_ascii=False).encode()
    parsed = parse(payload)
    plate = parsed.batch.meals[0].foods[0]

    row = _upload(client, user, payload)
    record, = compact.overview(row)['records']
    assert not record['preview']
    assert record['issues'][0]['code'] == 'conflicting_authority'
    assert Decimal(record['declared_values']['energy']['value']) == 120
    assert _counts(user) == (0, 0, 0)

    row = imports.apply_exchange_decision(user, row.public_id, row.revision,
                                          FoodDecision(original=plate, authority='ingredients'))
    db.session.commit()
    entry, = project(row)['data']['entries']
    assert not entry['bindings']
    declaration = entry['declaration']
    assert Decimal(declaration['nutrients']['energy']['value']) == 110
    evidence = declaration['provenance']['source_provenance']
    assert evidence['authority'] == 'ingredients'
    assert evidence['food']['nutrition']['observations']['energy']['value'] == '120'
    assert len(evidence['food']['ingredients']) == 2
    assert len(evidence['selected_observations']['energy']['evidence']['raw']) == 2
    assert _counts(user) == (0, 0, 0)

    confirm = '/nutrition/import/' + row.public_id + '/confirm'
    fields = {'revision': row.revision, 'token': token(client, row), 'consent_consumed': 'yes'}
    assert client.post(confirm, data=fields).status_code == 200
    assert _counts(user) == (1, 0, 1)
    snapshot = export_bundle(user)['logs'][0]['snapshot']
    assert Decimal(snapshot['summary']['energy']['value']) == 110
    assert snapshot['declared_nutrition']['provenance']['source_provenance'] == evidence

    target = User(username='qa-ingredient-authority-restored', role='user')
    target.set_password('synthetic-password')
    db.session.add(target)
    db.session.commit()
    exported = build_user_data_document(db.session.get(User, user), user)
    restore = AccountRestoreService()
    preview = restore.preview(exported, user_id=target.id)
    assert _counts(target.id) == (0, 0, 0)
    assert restore.commit(exported, user_id=target.id,
                          confirmation_token=preview['confirmation_token'])['committed']
    assert export_bundle(target.id)['logs'][0]['snapshot'] == snapshot
    assert _counts(target.id) == (1, 0, 1)


def test_exchange_verified_piece_equivalence_retains_original_unit_and_provenance(app, client, user):
    _enable(app)
    login(client)
    document = json.loads((FIXTURES / 'valid-explicit.json').read_bytes())
    document['meals'] = [document['meals'][3]]
    document['meals'][0]['foods'][0]['nutrition']['basis'] = {'amount': 100, 'unit': 'g'}
    payload = json.dumps(document).encode()
    original = parse(payload).batch.meals[0].foods[0]
    row = _upload(client, user, payload)
    record, = compact.overview(row)['records']
    assert not record['preview']
    assert record['issues'][0]['code'] == 'missing_equivalence'

    decision = FoodDecision(original=original, equivalence=Equivalence(Decimal(20), 'Etiqueta ficticia QA'))
    row = imports.apply_exchange_decision(user, row.public_id, row.revision, decision)
    db.session.commit()
    entry, = project(row)['data']['entries']
    assert entry['portion_unit'] == 'g'
    assert Decimal(entry['portion_amount']) == 40
    evidence = entry['declaration']['provenance']['source_provenance']
    assert evidence['food']['path'] == original.path
    assert evidence['food']['quantity']['unit'] == 'piece'
    assert evidence['food']['quantity']['evidence']['raw']['label'] == original.quantity.label
    assert evidence['equivalence'] == {'factor': '20', 'source': 'Etiqueta ficticia QA'}
    assert evidence['reviewed_quantity']['unit'] == 'g'

    confirm = '/nutrition/import/' + row.public_id + '/confirm'
    fields = {'revision': row.revision, 'token': token(client, row), 'consent_consumed': 'yes'}
    assert _counts(user) == (0, 0, 0)
    assert client.post(confirm, data=fields).status_code == 200
    snapshot = export_bundle(user)['logs'][0]['snapshot']
    assert Decimal(snapshot['summary']['energy']['value']) == 12
    assert snapshot['declared_nutrition']['provenance']['source_provenance'] == evidence
