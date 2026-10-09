"""Synthetic identities; never read production accounts or data."""
import json
import re
import html

from app.extensions import db
from app.models import User
from app.services.exercise_identity import get_or_create_exercise, add_exercise_alias
from app.services.gym_programs import catalog, resolve_draft
from app.services.gym_media import media_catalog, media_projection
from app.services.importers.routine_draft import DeterministicParser
from tests.test_gym_training import program, start
from tests.conftest import login


def identity(user, name, aliases=()):
    item, _ = get_or_create_exercise(user, name)
    for alias in aliases:
        add_exercise_alias(user, item.id, alias)
    return item


def test_alias_id_precedence_ambiguity_and_owner_isolation(app, user):
    bench = identity(user, 'QA pecho personalizado', ['Press banca', 'QA banco alternativo'])
    squat = identity(user, 'Sentadilla')
    press = identity(user, 'prensa')
    unknown = identity(user, 'QA sin ilustración')
    other = User(username='media-other', role='user')
    other.set_password('fictional-media-only-password')
    db.session.add(other); db.session.commit()
    foreign = identity(other.id, 'Press banca')
    resolve = media_projection(catalog(user), media_catalog())
    expected = resolve({'exercise_id': bench.public_id, 'name': 'Nombre cambiado'})
    assert expected['media_asset_id'] == 'everkinetic:bench-press'
    assert resolve({'name': 'QA banco alternativo'}) == expected
    assert resolve({'exercise_id': bench.public_id, 'name': 'Sentadilla'}) == expected
    assert resolve({'exercise_id': foreign.public_id, 'name': 'Press banca'})['status'] == 'unresolved'
    assert resolve({'name': 'No importado'})['status'] == 'unresolved'
    assert resolve({'name': press.canonical_name})['status'] == 'ambiguous'
    assert resolve({'name': unknown.canonical_name})['status'] == 'no_media'
    # Conflicting existing aliases must never become first-match-wins artwork.
    add_exercise_alias(user, squat.id, 'Remo con barra supino')
    resolve = media_projection(catalog(user), media_catalog())
    assert resolve({'exercise_id': squat.public_id})['status'] == 'ambiguous'


def test_official_import_home_hero_session_and_modal_share_binding(app, client, user):
    item = identity(user, 'QA pecho personalizado', ['Press banca', 'QA banco alternativo'])
    draft = DeterministicParser().parse(b'Dia,Ejercicio,Series,Reps\nD1,QA banco alternativo,2,8', 'qa.csv', 'QA media')
    resolve_draft(draft, user)
    assert draft.days[0]['exercises'][0]['resolved_exercise_id'] == item.public_id
    plan = program(user, draft)
    login(client)
    def bindings(response):
        assert response.status_code == 200
        return [json.loads(html.unescape(s)) for s in re.findall("data-media-binding='([^']+)'", response.text)]
    home = bindings(client.get('/training-plans'))
    assert len(home) >= 4  # upcoming hero, card, thumbnail and dialog opener
    assert all(b['media_asset_id'] == 'everkinetic:bench-press' for b in home)
    row = start(user, plan)
    session = bindings(client.get(f'/gym/sessions/{row.public_id}'))
    assert all(b == home[0] for b in session)
    assert db.session.query(User).count() == 1


def test_catalog_asset_identity_and_local_files(app):
    from pathlib import Path
    entries = media_catalog()
    assert len({e['media_asset_id'] for e in entries}) == len(entries) == 3
    for entry in entries:
        assert entry['license'] == 'CC BY-SA 3.0'
        assert entry['author'] and entry['source_url'] and entry['license_url']
        assert entry['external_exercise_id'] == ''  # a Commons file is not an exercise ID
        for field in ('thumbnail_url', 'media_url'):
            assert entry[field].startswith('/static/images/gym/')
            assert (Path(app.static_folder) / entry[field].removeprefix('/static/')).is_file()


def test_missing_catalog_is_optional(app, user, monkeypatch, tmp_path):
    item = identity(user, 'Press banca')
    monkeypatch.setattr(app, 'static_folder', str(tmp_path))
    assert media_catalog() == []
    assert media_projection(catalog(user), media_catalog())({'exercise_id': item.public_id})['status'] == 'no_media'
