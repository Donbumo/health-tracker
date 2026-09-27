"""Fictional QA fixtures; downloads mocked, no production accounts/storage."""
import copy
import io
import json
import os
from pathlib import Path
import tarfile
from urllib.error import URLError

from PIL import Image
import pytest
from sqlalchemy import event

from app.extensions import db
from app.models import Exercise, ExerciseAlias, ExerciseCatalogSource, ExternalExercise, User
from app.services.exercise_catalog import cleanup_catalog, external_catalog, resolve_external, sync_catalog
from app.services.exercise_catalog_source import CatalogError, FreeExerciseDBSource, download
from app.services.exercise_identity import get_or_create_exercise, add_exercise_alias
from app.services.gym_programs import catalog, resolve_draft, confirm_program, preview_token
from app.services.gym_media import media_catalog, media_projection
from app.services.importers.routine_draft import DeterministicParser
from tests.conftest import login


@pytest.fixture
def app(tmp_path):
    if not os.environ.get("CATALOG_TEST_MARIADB"):
        from tests.conftest import app as sqlite_app
        yield from sqlite_app.__wrapped__(tmp_path)
        return
    from app import create_app
    from tests.conftest import _schema_root
    # Opt-in is restricted to this disposable schema and loopback port.
    assert os.environ["CATALOG_TEST_MARIADB"] == "exercise_catalog_unit_qa"
    application = create_app({"TESTING": True, "SECRET_KEY": "fictional-catalog-unit-qa-secret-only",
        "SQLALCHEMY_DATABASE_URI": "mysql+pymysql://catalog_qa:fictional-qa-password@127.0.0.1:33379/exercise_catalog_unit_qa?charset=utf8mb4",
        "DATA_ROOT": tmp_path, "EXERCISE_CATALOG_ROOT": tmp_path / "catalog", "UPLOAD_ROOT": tmp_path / "raw", "GENERATED_UPLOAD_ROOT": tmp_path / "generated",
        "SCHEMA_ROOT": _schema_root(), "WTF_CSRF_ENABLED": False})
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


def sample(identifier="QA_Press", name="QA Press"):
    return {"id": identifier, "name": name, "force": "push", "level": "beginner", "mechanic": "compound", "equipment": "machine", "primaryMuscles": ["quadriceps"], "secondaryMuscles": [], "instructions": ["Fictional QA instruction."], "category": "strength", "images": [identifier + "/0.jpg", identifier + "/1.jpg"]}


class FixtureSource(FreeExerciseDBSource):
    def __init__(self, revision="a", entries=None):
        self.source_revision = revision * 40
        self.entries = entries if entries is not None else [sample()]

    def fetch(self, staging, ref, metadata_only=False):
        folder = staging / "snapshot"
        folder.mkdir()
        (folder / "exercises.json").write_text(json.dumps(self.entries), encoding="utf-8")
        (folder / "LICENSE.md").write_text("Fictional QA license fixture", encoding="utf-8")
        if not metadata_only:
            for entry in self.entries:
                for relative in entry.get("images", []):
                    path = folder / "exercises" / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    Image.new("RGB", (24, 24), "blue").save(path)
        return folder


def test_sync_revisions_idempotence_removed_and_mappings_preserved(app, user):
    first = sync_catalog(source=FixtureSource())
    assert first["exercise_count"] == 1 and first["media_count"] == 2 and first["added_rows"] == 1
    row = external_catalog()[0]
    identity, _ = get_or_create_exercise(user, "QA personal name")
    identity.external_catalog_id = row.id
    add_exercise_alias(user, identity.id, "QA alias")
    original = identity.public_id, identity.canonical_name, row.public_id
    assert sync_catalog(source=FixtureSource())["added_rows"] == 0
    updated = sample(name="QA Updated metadata")
    sync_catalog(source=FixtureSource("b", [updated, sample("QA_Other", "QA Other")]))
    assert (identity.public_id, identity.canonical_name, row.public_id) == original
    assert identity.external_catalog_id == row.id and len(identity.aliases) == 1
    sync_catalog(source=FixtureSource("c", [sample("QA_Other", "QA Other")]))
    assert not row.available and row.media == []
    assert db.session.query(ExternalExercise).count() == 2
    from app.services.exercise_catalog import storage_root
    root = storage_root() / "free-exercise-db"
    assert not (root / ("a"*40)).exists()
    assert (root / ("b"*40)).is_dir() and (root / ("c"*40)).is_dir()


def test_dry_run_metadata_only_and_status(app):
    report = sync_catalog(source=FixtureSource(), dry_run=True)
    assert report["dry_run"] and db.session.query(ExternalExercise).count() == 0
    report = sync_catalog(source=FixtureSource(), metadata_only=True)
    assert report["media_count"] == 0
    report = sync_catalog(source=FixtureSource())
    assert report["media_count"] == 2 and report["added_rows"] == 0
    status = app.test_cli_runner().invoke(args=["exercise-catalog", "status"])
    assert status.exit_code == 0 and json.loads(status.output)["exercise_count"] == 1


def test_failed_validation_and_commit_leave_previous_active(app, monkeypatch):
    sync_catalog(source=FixtureSource())
    with pytest.raises(CatalogError):
        sync_catalog(source=FixtureSource("b", [{"id": "QA_bad"}]))
    commit = db.session.commit
    def fail():
        db.session.flush()
        raise RuntimeError("QA simulated commit failure")
    monkeypatch.setattr(db.session, "commit", fail)
    with pytest.raises(RuntimeError):
        sync_catalog(source=FixtureSource("c", [sample("QA_New", "QA New")]))
    monkeypatch.setattr(db.session, "commit", commit)
    state = db.session.get(ExerciseCatalogSource, "free-exercise-db")
    assert state.active_snapshot == "a"*40
    assert external_catalog()[0].external_id == "QA_Press"
    assert cleanup_catalog() == 1


@pytest.mark.parametrize("payload", [b"not JSON", b"{}", b"[]", json.dumps([sample() | {"level": "invalid"}]).encode(), json.dumps([sample(), sample()]).encode(), json.dumps([sample() | {"images": ["../../escape.jpg"]}]).encode()])
def test_invalid_source_json(payload):
    with pytest.raises(CatalogError):
        FreeExerciseDBSource().validate(payload)


def archive_at(tmp_path, members):
    archive = tmp_path / "input.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        for name, data, kind in members:
            member = tarfile.TarInfo(name)
            member.size = len(data)
            member.type = kind
            if kind == tarfile.SYMTYPE:
                member.linkname = "../../escape"
            bundle.addfile(member, io.BytesIO(data))
    return archive


@pytest.mark.parametrize("name,kind", [("root/../../escape.jpg", tarfile.REGTYPE), ("/absolute.jpg", tarfile.REGTYPE), ("root/exercises/link.jpg", tarfile.SYMTYPE), ("root/exercises/link.jpg", tarfile.LNKTYPE), ("root/C:/escape.jpg", tarfile.REGTYPE), ("root/..\\escape.jpg", tarfile.REGTYPE)])
def test_archive_traversal_and_links_rejected(tmp_path, name, kind):
    with pytest.raises(CatalogError):
        FreeExerciseDBSource().extract(archive_at(tmp_path, [(name, b"x", kind)]), tmp_path / "out")


def test_valid_archive_and_malformed_archive(tmp_path):
    archive = archive_at(tmp_path, [("root/dist/exercises.json", json.dumps([sample()]).encode(), tarfile.REGTYPE), ("root/LICENSE.md", b"public domain https://unlicense.org", tarfile.REGTYPE), ("root/site/evil.py", b"raise Exception('never execute')", tarfile.REGTYPE)])
    source = FreeExerciseDBSource()
    source.extract(archive, tmp_path / "out", metadata_only=True)
    assert len(source.validate((tmp_path / "out/exercises.json").read_bytes())) == 1
    assert not (tmp_path / "out/site").exists()
    archive.write_bytes(b"not gzip")
    with pytest.raises(CatalogError):
        source.extract(archive, tmp_path / "bad")


def test_archive_limits(tmp_path, monkeypatch):
    from app.services import exercise_catalog_source as adapter
    monkeypatch.setattr(adapter, "MAX_FILE", 2)
    with pytest.raises(CatalogError):
        adapter.FreeExerciseDBSource().extract(archive_at(tmp_path, [("root/large", b"123", tarfile.REGTYPE)]), tmp_path / "out")


@pytest.mark.parametrize("failure", [TimeoutError(), URLError("QA offline")])
def test_download_timeout(tmp_path, monkeypatch, failure):
    from app.services import exercise_catalog_source as adapter
    class Opener:
        def open(self, *args, **kwargs):
            raise failure
    monkeypatch.setattr(adapter, "build_opener", lambda *args: Opener())
    with pytest.raises(CatalogError, match="timed out"):
        download("https://api.github.com/qa", tmp_path / "download", 2, {"application/json"})


@pytest.mark.parametrize("mime,length,body", [("text/html", "1", b"a"), ("application/json", "5", b"12345"), ("application/json", None, b"12345")])
def test_download_type_and_size(tmp_path, monkeypatch, mime, length, body):
    from email.message import Message
    from app.services import exercise_catalog_source as adapter
    class Response(io.BytesIO):
        headers = Message()
    response = Response(body)
    response.headers["Content-Type"] = mime
    if length:
        response.headers["Content-Length"] = length
    class Opener:
        def open(self, *args, **kwargs):
            return response
    monkeypatch.setattr(adapter, "build_opener", lambda *args: Opener())
    with pytest.raises(CatalogError):
        download("https://api.github.com/qa", tmp_path / "download", 2, {"application/json"})


def test_images_decode_mime_missing(tmp_path):
    source = FixtureSource()
    folder = source.fetch(tmp_path, "main")
    assert source.media(folder, source.entries)["QA_Press"][0]["width"] == 24
    path = folder / "exercises/QA_Press/0.jpg"
    Image.new("RGB", (10, 10)).save(path, format="PNG")
    with pytest.raises(CatalogError):
        source.media(folder, source.entries)
    path.unlink()
    with pytest.raises(CatalogError):
        source.media(folder, source.entries)


def test_resolution_mapping_alias_ambiguity_ownership(app, user):
    sync_catalog(source=FixtureSource(entries=[sample(), sample("QA_Variant", "QA press")]))
    entries = external_catalog()
    assert len(resolve_external("QA PRESS", [], entries)) == 2
    assert len(resolve_external("QA Press", [], entries)) == 1
    assert resolve_external("prensa", [], entries) == []
    personal, _ = get_or_create_exercise(user, "My QA exercise")
    add_exercise_alias(user, personal.id, "QA Press")
    assert len(resolve_external("My QA exercise", catalog(user), entries)) == 1
    personal.external_catalog_id = entries[1].id
    db.session.commit()
    assert resolve_external("QA Press", catalog(user), entries) == [entries[1]]
    assert resolve_external("anything", [], entries, source="free-exercise-db", external_id="QA_Press")[0].external_id == "QA_Press"
    foreign = User(username="catalog-other-qa", role="user")
    foreign.set_password("fictional-qa-password")
    db.session.add(foreign); db.session.commit()
    assert resolve_external("My QA exercise", catalog(foreign.id), entries) == []


def test_offline_import_history_local_media_and_owner_mapping(app, client, user, monkeypatch):
    from app.services import exercise_catalog_source as adapter
    sync_catalog(source=FixtureSource())
    def offline(*args, **kwargs):
        raise AssertionError("Runtime must not use network")
    monkeypatch.setattr(adapter, "download", offline)
    draft = DeterministicParser().parse(b"Day,Exercise,Sets,Reps\nQA Day,QA Press,2,8", "qa.csv", "QA Catalog Program")
    resolve_draft(draft, user)
    assert not draft.unresolved
    assert db.session.query(Exercise).count() == 0  # Preview read-only.
    plan, _ = confirm_program(draft, user, preview_token(draft, user))
    db.session.commit()
    identity = catalog(user)[0]
    assert identity.external_catalog_id == external_catalog()[0].id
    from tests.test_gym_training import start
    session = start(user, plan)
    history = copy.deepcopy(plan.versions[0].content)
    login(client)
    for route in ("/exercise-catalog", "/exercise-catalog?q=quadriceps", "/training-plans", f"/gym/sessions/{session.public_id}"):
        response = client.get(route)
        assert response.status_code == 200 and "raw.githubusercontent.com" not in response.text
    row = external_catalog()[0]
    assert client.get("/exercise-catalog/" + row.public_id).status_code == 200
    entries = client.get("/exercise-catalog/media.json").json["entries"]
    entry = next(item for item in entries if item["source"] == "free-exercise-db")
    response = client.get(entry["thumbnail_url"])
    assert response.status_code == 200 and response.mimetype == "image/jpeg"
    assert response.headers["ETag"] and "max-age=" in response.headers["Cache-Control"]
    assert client.get(entry["thumbnail_url"], headers={"If-None-Match": response.headers["ETag"]}).status_code == 304
    assert client.get("/exercise-media/free-exercise-db/QA_Press/99?revision=" + "a"*40).status_code == 404
    assert client.get("/exercise-media/free-exercise-db/%2e%2e/0?revision=" + "a"*40).status_code == 404
    other = User(username="other-catalog-media", role="user"); other.set_password("fictional-only-password")
    db.session.add(other); db.session.commit()
    foreign, _ = get_or_create_exercise(other.id, "QA foreign")
    assert client.post(f"/exercise-catalog/{row.public_id}/map", data={"exercise_id": foreign.public_id}).status_code == 404
    assert foreign.external_catalog_id is None
    assert client.post(f"/exercise-catalog/{row.public_id}/map", data={"exercise_id": identity.public_id}).status_code == 302
    assert plan.versions[0].content == history


def test_projection_constant_queries(app, user):
    sync_catalog(source=FixtureSource())
    for index in range(12):
        identity, _ = get_or_create_exercise(user, f"QA identity {index}")
        identity.external_catalog_id = external_catalog()[0].id
    db.session.commit()
    statements = []
    def count(*args):
        statements.append(args[2])
    event.listen(db.engine, "before_cursor_execute", count)
    try:
        identities = catalog(user)
        resolve = media_projection(identities, media_catalog(), external_catalog())
        before = len(statements)
        for identity in identities:
            assert resolve({"exercise_id": identity.public_id})["status"] == "available"
        assert len(statements) == before <= 3
    finally:
        event.remove(db.engine, "before_cursor_execute", count)


def test_ambiguous_preview_explicit_reference_and_user_defined(app, client, user):
    from app.services.exercise_catalog import candidate_report
    sync_catalog(source=FixtureSource(entries=[sample("QA_Leg", "QA Leg Press"), sample("QA_Narrow", "QA Narrow Leg Press")]))
    draft = DeterministicParser().parse(b"Day,Exercise,Sets,Reps\nQA day,prensa,1,8", "qa.csv", "QA ambiguity")
    resolve_draft(draft, user)
    assert draft.unresolved == ["prensa"]
    suggestions = candidate_report("prensa", catalog(user), external_catalog())
    assert len(suggestions) == 2 and all(item["confidence"] == "manual_review" for item in suggestions)
    with pytest.raises(ValueError):
        confirm_program(draft, user, preview_token(draft, user))
    selected = external_catalog()[0]
    draft.days[0]["exercises"][0]["resolved_catalog_id"] = selected.public_id
    resolve_draft(draft, user)
    assert not draft.unresolved
    plan, _ = confirm_program(draft, user, preview_token(draft, user)); db.session.commit()
    identity = catalog(user)[0]
    assert identity.external_catalog_id == selected.id
    assert [a.alias_name for a in identity.aliases] == ["prensa"]
    login(client)
    assert selected.name in client.get("/exercise-catalog?q=prensa").text
    app.config["WTF_CSRF_ENABLED"] = True
    assert client.post(f"/exercise-catalog/{selected.public_id}/map", data={"exercise_id": identity.public_id}).status_code == 400


def test_invalid_media_paths_and_cleanup_preserves_active(app, client, user):
    sync_catalog(source=FixtureSource())
    row = external_catalog()[0]
    original = copy.deepcopy(row.media)
    for values in ({"relative_path": "../../escape.jpg"}, {"mime_type": "text/html"}):
        row.media = [original[0] | values]; db.session.commit()
        assert client.get("/exercise-media/free-exercise-db/QA_Press/0?revision="+"a"*40).status_code == 404
    row.media = original; db.session.commit()
    assert cleanup_catalog() == 0
    assert client.get("/exercise-media/free-exercise-db/QA_Press/0?revision="+"a"*40).status_code == 200


def test_source_lock_rejects_parallel_sync(tmp_path):
    from app.services.exercise_catalog import source_lock
    with source_lock(tmp_path):
        with pytest.raises(CatalogError, match="Another catalog"):
            with source_lock(tmp_path):
                pass


def test_archive_case_collisions_and_site_link(tmp_path):
    members = [("root/dist/exercises.json", json.dumps([sample()]).encode(), tarfile.REGTYPE), ("root/LICENSE.md", b"public domain https://unlicense.org", tarfile.REGTYPE), ("root/site/public/exercises", b"", tarfile.SYMTYPE)]
    source = FreeExerciseDBSource()
    source.extract(archive_at(tmp_path, members), tmp_path / "valid", True)
    members.extend([("root/exercises/QA/0.jpg", b"a", tarfile.REGTYPE), ("root/exercises/qa/0.jpg", b"b", tarfile.REGTYPE)])
    with pytest.raises(CatalogError):
        source.extract(archive_at(tmp_path, members), tmp_path / "invalid")


def test_metadata_fetch_pins_revision_and_avoids_archive(tmp_path, monkeypatch):
    from app.services import exercise_catalog_source as adapter
    urls = []
    def fixture(url, destination, limit, content_types):
        urls.append(url)
        value = json.dumps({"sha": "a"*40}) if destination.name == "commit.json" else json.dumps([sample()]) if destination.name == "exercises.json" else "public domain https://unlicense.org"
        destination.write_text(value, encoding="utf-8")
    monkeypatch.setattr(adapter, "download", fixture)
    source = adapter.FreeExerciseDBSource()
    folder = source.fetch(tmp_path, "main", True)
    assert source.source_revision == "a"*40 and source.validate((folder / "exercises.json").read_bytes())
    assert len(urls) == 3 and all("a"*40 in url for url in urls[1:])
    assert not any("codeload" in url for url in urls)


def test_sync_does_not_rename_or_bind_personal_exercise(app, user):
    personal, _ = get_or_create_exercise(user, "QA Press")
    original = personal.public_id
    sync_catalog(source=FixtureSource())
    assert personal.external_catalog_id is None and personal.public_id == original and personal.canonical_name == "QA Press"


def test_preview_revision_change_requires_review(app, user):
    sync_catalog(source=FixtureSource())
    draft = DeterministicParser().parse(b"Day,Exercise,Sets,Reps\nQA day,QA Press,1,8", "qa.csv", "QA preview")
    resolve_draft(draft, user)
    token = preview_token(draft, user)
    sync_catalog(source=FixtureSource("b", [sample(name="QA Updated")]))
    with pytest.raises(ValueError, match="catálogo cambió"):
        confirm_program(draft, user, token)
    assert db.session.query(Exercise).count() == 0
