"""Fictional QA fixtures only: programs, confirmed sets and isolation."""
import copy
import io
import json
import uuid
import zipfile

import pytest

from app.extensions import db
from app.models import Exercise, TrainingPlan, TrainingPlanVersion, TrainingSession, TrainingSet, User
from app.services.gym_programs import GymError, confirm_program, preview_token, preset_draft, resolve_draft, standard_document, activate_program
from app.services.gym_sessions import complete_set, finish_session, start_session, workout_context
from app.services.importers.routine_draft import DeterministicParser, RoutineParseError, draft_from_document
from app.services.training_plans import get_active_version
from app.services.validation import validate_json_document
from app.services.exporters.training_session import build_completed_workout_document
from tests.conftest import login


def program(user_id, draft=None, plan=None):
    draft = resolve_draft(draft or preset_draft('ppl-v1'), user_id)
    plan_id, revision = (plan.public_id, plan.revision) if plan else (None, None)
    token = preview_token(draft, user_id, plan_id, revision)
    result = confirm_program(draft, user_id, token, plan_id=plan_id, base_revision=revision)
    db.session.commit()
    return result[0]


def start(user_id, plan, submission=None):
    version = get_active_version(plan, user_id)
    row = start_session(user_id, plan.public_id, version.public_id, 1, 1, submission or str(uuid.uuid4()))
    db.session.commit()
    return row


def test_program_revision_preserves_history_and_no_pregeneration(app, user):
    plan = program(user)
    assert db.session.query(TrainingSession).count() == 0
    assert len(plan.workouts) == 3
    original = get_active_version(plan, user)
    original_content = copy.deepcopy(original.content)
    row = start(user, plan)
    draft = draft_from_document(original.content)
    draft.days.reverse()
    draft.days[0]['exercises'][0]['sets'][0]['rir'] = '2'
    program(user, draft, plan)
    assert get_active_version(plan, user).id != original.id
    assert row.training_plan_version_id == original.id
    assert original.content == original_content
    assert get_active_version(plan, user).content['data']['weeks'][0]['days'][0]['name'] == 'Legs'


def test_suggestion_not_performance_autosave_repeat_and_resume(app, user):
    draft = preset_draft('ppl-v1')
    draft.days[0]['exercises'][0]['sets'][0].update(load_value='80', load_unit='kg', rir='2', rest_seconds=60)
    plan = program(user, draft)
    row = start(user, plan)
    context = workout_context(row, user, 'kg')
    assert context['exercises'][0]['sets'][0]['suggestion']['load'] == '80.00'
    assert context['completed_sets'] == 0
    assert db.session.query(TrainingSet).count() == 0
    values = {'load': '82.5', 'unit': 'kg', 'reps': '8', 'rir': '2'}
    _, saved, duplicate = complete_set(user, row.public_id, 1, 1, values)
    db.session.commit()
    assert saved.weight_kg == 82.5 and not duplicate
    assert complete_set(user, row.public_id, 1, 1, values)[2]
    with pytest.raises(GymError, match='otros valores'):
        complete_set(user, row.public_id, 1, 1, values | {'load': '85'})
    db.session.rollback()
    assert start(user, plan).id == row.id
    assert workout_context(row, user, 'kg')['completed_sets'] == 1
    finish_session(user, row.public_id, 'completed')
    db.session.commit()
    next_row = start(user, plan)
    context = workout_context(next_row, user, 'kg')
    assert context['completed_sets'] == 0
    assert context['exercises'][0]['sets'][0]['suggestion']['load'] == '82.50'
    assert context['exercises'][0]['sets'][0]['actual'] is None
    assert context['exercises'][0]['previous']['sets'][0]['reps'] == 8
    assert db.session.query(TrainingSet).count() == 1


def test_start_idempotency_and_active_ownership(app, user):
    plan = program(user)
    submission = str(uuid.uuid4())
    row = start(user, plan, submission)
    assert start(user, plan, submission).id == row.id
    other = User(username='gym-other-qa', role='user')
    other.set_password('fictional-qa-password')
    db.session.add(other)
    db.session.commit()
    for action in [lambda: activate_program(other.id, plan.public_id), lambda: complete_set(other.id, row.public_id, 1, 1, {}), lambda: finish_session(other.id, row.public_id, 'completed')]:
        with pytest.raises(GymError) as error:
            action()
        assert error.value.status == 404
    second = program(user, preset_draft('full-body-v1'))
    activate_program(user, second.public_id)
    db.session.commit()
    assert second.gym_active and not plan.gym_active
    assert db.session.query(TrainingSession).count() == 1


def test_import_preview_readonly_mapping_idempotency(app, user):
    source = b'Day,Exercise,Sets,Reps,Weight,RIR,RPE,Rest\nD1,QA Bench,3,6-8,80kg,2,8,90\n'
    draft = DeterministicParser().parse(source, 'routine.csv', 'QA Routine')
    resolve_draft(draft, user)
    assert draft.unresolved == ['QA Bench']
    assert db.session.query(Exercise).count() == 0
    assert db.session.query(TrainingPlan).count() == 0
    token = preview_token(draft, user)
    with pytest.raises(GymError, match='Resuelve'):
        confirm_program(draft, user, token)
    draft.days[0]['exercises'][0]['create_new'] = True
    with pytest.raises(GymError, match='contenido cambió'):
        confirm_program(draft, user, token)
    plan = program(user, draft)
    again = DeterministicParser().parse(source, 'routine.csv', 'QA Routine')
    assert program(user, again).id == plan.id
    assert db.session.query(TrainingPlanVersion).count() == 1
    assert db.session.query(TrainingSession).count() == 0
    target = get_active_version(plan, user).content['data']['weeks'][0]['days'][0]['exercises'][0]['sets'][0]
    assert target['rir'] == '2' and target['rpe'] == '8' and target['weight_kg'] == '80'


def test_session_export_lifecycle_units_and_empty_abandon(app, user):
    plan = program(user)
    row = start(user, plan)
    document = build_completed_workout_document(row, user)
    validate_json_document(document, 'completed_workout')
    assert document['data']['status'] == 'in_progress'
    assert document['data']['exercises'] == []
    with pytest.raises(GymError):
        finish_session(user, row.public_id, 'completed')
    complete_set(user, row.public_id, 1, 1, {'load': '100', 'unit': 'lb', 'reps': '8', 'rpe': '8'})
    db.session.commit()
    assert float(db.session.query(TrainingSet).one().weight_kg) == 45.36
    finish_session(user, row.public_id, 'abandoned')
    db.session.commit()
    document = build_completed_workout_document(row, user)
    validate_json_document(document, 'completed_workout')
    assert document['data']['status'] == 'abandoned'
    assert document['data']['exercises'][0]['sets'][0]['load_details']['original_unit'] == 'lb'


@pytest.mark.parametrize('source', [b'Day,Exercise,Sets,Reps,Weight\nD1,QA,3,8,80', b'Day,Exercise,Sets,Reps\nD1,QA,99999999,8', b'Day,Exercise,Sets,Reps\n,QA,3,8'])
def test_import_invalid_rows(source):
    with pytest.raises(RoutineParseError):
        DeterministicParser().parse(source, 'routine.csv', 'QA')


def test_web_journey(app, client, user):
    login(client)
    plan = program(user)
    home = client.get('/training-plans')
    assert home.status_code == 200 and 'Mi programa' in home.text
    assert client.get('/gym/programs/new').status_code == 200
    row = start(user, plan)
    url = f'/gym/sessions/{row.public_id}'
    assert client.get(url).status_code == 200
    response = client.post(url + '/sets/1/1', json={'load':'80','unit':'kg','reps':'8','rir':'2'})
    assert response.status_code == 200, response.text
    assert client.get(url).status_code == 200
    assert client.post(url + '/finish', data={'status':'completed'}).status_code == 302
    assert client.get(url).status_code == 200


def test_preview_web_and_csrf(app, client, user):
    login(client)
    response = client.post('/gym/programs/new', data={'preset': 'ppl-v1'})
    assert response.status_code == 200, response.text
    assert 'Confirmar programa' in response.text
    assert db.session.query(TrainingPlan).count() == 0
    app.config['WTF_CSRF_ENABLED'] = True
    assert client.post('/gym/programs/confirm', data={}).status_code == 400


def test_four_file_formats_equivalent(app, user):
    from pathlib import Path
    root = Path(__file__).parent / 'fixtures/gym_qa'
    drafts = [DeterministicParser().parse((root / f'routine.{ext}').read_bytes(), f'routine.{ext}', 'QA Routine') for ext in ('csv','xlsx','json','txt')]
    assert all(draft.days == drafts[0].days for draft in drafts)
    assert len(drafts[0].days) == 3
    document = standard_document(drafts[0], user)
    validate_json_document(document, 'training_plan')
    assert 'weight_kg' not in document['data']['weeks'][0]['days'][0]['exercises'][1]['sets'][0]


def test_xlsx_empty_inline_cells_preserve_optional_blank_values():
    from pathlib import Path
    from xml.etree import ElementTree as ET
    raw = (Path(__file__).parent / 'fixtures/gym_qa/routine.xlsx').read_bytes()
    with zipfile.ZipFile(io.BytesIO(raw)) as original:
        entries = {name: original.read(name) for name in original.namelist()}
    sheet = 'xl/worksheets/sheet1.xml'
    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    root = ET.fromstring(entries[sheet])
    empty_cells = 0
    for cell in root.findall('s:sheetData/s:row/s:c', ns):
        inline = cell.find('s:is', ns)
        if inline is not None and not ''.join(inline.itertext()):
            cell.remove(inline)
            empty_cells += 1
    assert empty_cells > 0
    entries[sheet] = ET.tostring(root)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as output:
        for name, value in entries.items():
            output.writestr(name, value)
    parser = DeterministicParser()
    expected = parser.parse(raw, 'routine.xlsx', 'QA')
    actual = parser.parse(buffer.getvalue(), 'empty-cells.xlsx', 'QA')
    assert actual.days == expected.days


@pytest.mark.parametrize('attack', ['formula', 'macro', 'external', 'entity', 'oversize', 'columns', 'multiple_sheets'])
def test_xlsx_rejects_executable_or_unbounded_content(attack):
    from pathlib import Path
    raw = (Path(__file__).parent / 'fixtures/gym_qa/routine.xlsx').read_bytes()
    with zipfile.ZipFile(io.BytesIO(raw)) as original:
        entries = {name: original.read(name) for name in original.namelist()}
    key = 'xl/worksheets/sheet1.xml'
    if attack == 'formula': entries[key] = entries[key].replace(b'<is>', b'<f>WEBSERVICE("https://invalid.example")</f><is>', 1)
    if attack == 'macro': entries['xl/vbaProject.bin'] = b'QA'
    if attack == 'external': entries['xl/externalLinks/externalLink1.xml'] = b'QA'
    if attack == 'entity': entries[key] = b'<!DOCTYPE x [<!ENTITY a "QA">]>' + entries[key]
    if attack == 'oversize': entries['xl/large.xml'] = b' ' * (21 * 1024 * 1024)
    if attack == 'columns': entries[key] = entries[key].replace(b'r="A1"', b'r="ZZ1"', 1)
    if attack == 'multiple_sheets': entries['xl/worksheets/sheet2.xml'] = entries[key]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as output:
        for name, value in entries.items(): output.writestr(name, value)
    with pytest.raises(RoutineParseError):
        DeterministicParser().parse(buffer.getvalue(), 'routine.xlsx', 'QA')


def test_owner_mapping_is_saved_and_foreign_mapping_rejected(app, user):
    plan = program(user)
    identity = db.session.execute(db.select(Exercise).where(Exercise.user_id == user, Exercise.canonical_name == 'Press banca')).scalar_one()
    draft = DeterministicParser().parse(b'Day,Exercise,Sets,Reps\nD1,Bench Press,3,8', 'routine.csv', 'QA English')
    draft.days[0]['exercises'][0]['resolved_exercise_id'] = identity.public_id
    program(user, draft)
    again = DeterministicParser().parse(b'Day,Exercise,Sets,Reps\nD1,Bench Press,3,8', 'routine.csv', 'QA English')
    resolve_draft(again, user)
    assert again.days[0]['exercises'][0]['resolved_exercise_id'] == identity.public_id
    other = User(username='qa-foreign-mapping', role='user')
    other.set_password('fictional-only')
    db.session.add(other); db.session.commit()
    with pytest.raises(GymError) as error:
        resolve_draft(again, other.id)
    assert error.value.status == 404


def test_bounded_queries_and_failed_set_not_counted(app, user):
    from sqlalchemy import event
    plan = program(user)
    row = start(user, plan)
    calls = []
    def count(*args): calls.append(1)
    event.listen(db.engine, 'before_cursor_execute', count)
    try:
        workout_context(row, user, 'lb')
    finally:
        event.remove(db.engine, 'before_cursor_execute', count)
    assert len(calls) <= 8
    with pytest.raises(ValueError):
        complete_set(user, row.public_id, 1, 1, {'load': 'NaN', 'unit':'kg','reps':'8'})
    db.session.rollback()
    assert db.session.query(TrainingSet).count() == 0


def test_neutral_reads_and_future_actions_disabled(app, user):
    from app.services.ai.capabilities.registry import AICapabilityRegistry
    from app.services.gym_capabilities import FUTURE_ACTIONS, read_program, read_session
    plan = program(user)
    row = start(user, plan)
    assert read_program(user)['program_id'] == plan.public_id
    assert read_session(user, row.public_id)['exercises'] == []
    assert not set(FUTURE_ACTIONS) & set(AICapabilityRegistry().actions_by_id)


def test_upload_preview_does_not_write_domain_and_confirm_preserves_source(app, client, user):
    from pathlib import Path
    from html import unescape
    import re
    from app.models import UploadedFile, ImportRun
    login(client)
    raw = (Path(__file__).parent / 'fixtures/gym_qa/routine.csv').read_bytes()
    response = client.post('/gym/programs/new', data={'name':'QA Import', 'file':(io.BytesIO(raw), 'routine.csv')})
    assert response.status_code == 200
    assert db.session.query(TrainingPlan).count() == 0
    assert db.session.query(UploadedFile).count() == 0
    draft = json.loads(unescape(re.search(r'id="mapping-draft" value="([^"]+)"', response.text)[1]))
    for day in draft['days']:
        for exercise in day['exercises']: exercise['create_new'] = True
    response = client.post('/gym/programs/new', data={'draft':json.dumps(draft)})
    html = response.text.split('id="gym-confirm"')[1]
    fields = {name: unescape(value) for name,value in re.findall(r'name="([^"]+)" value="([^"]*)"', html.split('</form>')[0])}
    assert client.post('/gym/programs/confirm', data=fields).status_code == 302
    assert db.session.query(TrainingPlan).count() == 1
    assert db.session.query(UploadedFile).one().sha256 == draft['source_sha256']
    assert db.session.query(ImportRun).one().status == 'succeeded'
    assert client.post('/gym/programs/confirm', data=fields).status_code == 302
    assert db.session.query(TrainingPlan).count() == 1


def test_account_restore_retains_open_and_abandoned_sessions(app, client, user):
    from app.services.account_restore import AccountRestoreService
    from app.services.exporters.user_data import build_user_data_document
    plan = program(user)
    row = start(user, plan)
    complete_set(user, row.public_id, 1, 1, {'load':'80','unit':'kg','reps':'8','rir':'0'})
    db.session.commit()
    finish_session(user, row.public_id, 'abandoned'); db.session.commit()
    open_row = start(user, plan)
    payload = build_user_data_document(db.session.get(User, user), user)
    destination = User(username='qa-restored-gym', role='user')
    destination.set_password('fictional-restore-password')
    db.session.add(destination); db.session.commit()
    service = AccountRestoreService()
    preview = service.preview(payload, user_id=destination.id)
    assert preview['valid'], preview
    result = service.commit(payload, user_id=destination.id, confirmation_token=preview['confirmation_token'])
    assert result['committed'], result
    restored = db.session.execute(db.select(TrainingSession).where(TrainingSession.user_id == destination.id).order_by(TrainingSession.performed_at)).scalars().all()
    assert [item.status for item in restored] == ['abandoned', 'in_progress']
    assert restored[0].exercises[0].sets[0].rir == 0
    assert restored[1].started_at == open_row.started_at
    restored_plan = db.session.execute(db.select(TrainingPlan).where(TrainingPlan.user_id == destination.id)).scalar_one()
    assert restored_plan.gym_active
    login(client, 'qa-restored-gym', 'fictional-restore-password')
    assert client.get(f'/gym/programs/{restored_plan.public_id}/edit').status_code == 200


def test_prioritizes_same_program_then_global_history(app, user):
    from datetime import timedelta
    first = program(user)
    row = start(user, first)
    complete_set(user, row.public_id, 1, 1, {'load':'70','unit':'kg','reps':'7'})
    finish_session(user, row.public_id, 'completed'); db.session.commit()
    other = program(user, preset_draft('full-body-v1'))
    newer = start(user, other)
    complete_set(user, newer.public_id, 2, 1, {'load':'85','unit':'kg','reps':'8'})
    finish_session(user, newer.public_id, 'completed'); db.session.commit()
    current = start(user, first)
    assert workout_context(current, user, 'kg')['exercises'][0]['sets'][0]['suggestion']['load'] == '70.00'
    third_draft = preset_draft('ppl-v1'); third_draft.program['name'] = 'QA Third Program'
    third = program(user, third_draft)
    newest = start(user, third)
    assert workout_context(newest, user, 'kg')['exercises'][0]['sets'][0]['suggestion']['load'] == '85.00'


def test_noop_and_stale_revision_and_rest_day(app, user):
    plan = program(user)
    draft = draft_from_document(get_active_version(plan, user).content)
    original_version = plan.active_version_number
    assert program(user, draft, plan).active_version_number == original_version
    stale = copy.deepcopy(draft)
    stale.program['name'] = 'QA stale'
    resolve_draft(stale, user)
    revision = plan.revision
    token = preview_token(stale, user, plan.public_id, revision)
    draft.days.append({'name':'Descanso libre','exercises':[]})
    program(user, draft, plan)
    with pytest.raises(GymError) as error:
        confirm_program(stale, user, token, plan_id=plan.public_id, base_revision=revision)
    assert error.value.status == 409
    db.session.rollback()
    assert get_active_version(plan, user).content['data']['weeks'][0]['days'][-1]['name'] == 'Descanso libre'


def test_correcting_preview_preserves_revision_and_posts_to_editor(app, client, user):
    from html import unescape
    import re
    plan = program(user)
    login(client)
    draft = draft_from_document(get_active_version(plan, user).content)
    revision = plan.revision
    draft.program['name'] = 'QA corrected preview'
    fields = {'draft': json.dumps(draft.to_dict()), 'plan_id': plan.public_id, 'base_revision': str(revision)}
    newer = copy.deepcopy(draft)
    newer.program['name'] = 'QA concurrent change'
    program(user, newer, plan)
    response = client.post('/gym/programs/edit-draft', data=fields)
    assert response.status_code == 200
    assert f'action="/gym/programs/{plan.public_id}/edit"' in response.text
    assert f'name="base_revision" value="{revision}"' in response.text
    response = client.post(f'/gym/programs/{plan.public_id}/edit', data=fields)
    html = response.text.split('id="gym-confirm"')[1].split('</form>')[0]
    confirmation = {name: unescape(value) for name, value in re.findall(r'name="([^"]+)" value="([^"]*)"', html)}
    assert client.post('/gym/programs/confirm', data=confirmation).status_code == 409
    assert plan.name == 'QA concurrent change'


def test_csv_exports_prescriptions_and_escapes_formulas(app, user):
    import csv
    from app.services.exporters.training_plan import TrainingPlanCsvExporter
    draft = preset_draft('ppl-v1')
    draft.program['name'] = '=QA()'
    draft.days[0]['exercises'][0]['notes'] = '\t@QA'
    draft.days[0]['exercises'][0]['sets'][0].update(load_value='80', load_unit='kg', rir='0', rpe='8')
    plan = program(user, draft)
    artifact = TrainingPlanCsvExporter().export(plan, user)
    rows = list(csv.DictReader(io.StringIO(artifact.content.decode('utf-8-sig'))))
    assert rows[0]['plan_name'] == "'=QA()"
    assert rows[0]['exercise_notes'].startswith("'")
    assert float(rows[0]['load_value']) == 80
    assert rows[0]['load_unit'] == 'kg'
    assert float(rows[0]['rir']) == 0
    assert float(rows[0]['rpe']) == 8


def test_unowned_gym_routes_are_not_found(app, client, user):
    login(client)
    missing = str(uuid.uuid4())
    assert client.get(f'/gym/programs/{missing}/edit').status_code == 404
    assert client.post(f'/gym/programs/{missing}/archive').status_code == 404
    assert client.get(f'/gym/sessions/{missing}').status_code == 404
    assert client.get(f'/gym/exercises/{missing}/progress').status_code == 404
