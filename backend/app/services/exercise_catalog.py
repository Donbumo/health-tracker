"""Official snapshot sync and read-only reference resolution.

Immutable files are published before a single DB commit activates metadata and
the snapshot pointer together. A crash can leave an unreferenced directory, but
can never point the active catalog at incomplete files.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time

from flask import current_app, url_for

from app.extensions import db
from app.models import ExerciseCatalogSource, ExternalExercise
from app.services.exercise_catalog_source import CatalogError, FreeExerciseDBSource
from app.services.exercise_identity import normalize_exercise_name


def storage_root():
    return Path(current_app.config.get("EXERCISE_CATALOG_ROOT") or Path(current_app.config["DATA_ROOT"]) / "exercise-catalog").resolve()


@contextmanager
def source_lock(root):
    root.mkdir(parents=True, exist_ok=True)
    # OS locks release after process death, unlike persistent mkdir locks.
    with (root / ".sync.lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
        handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise CatalogError("Another catalog operation is running.") from error
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def _remove_snapshot(root, path):
    if path.is_symlink() or path.resolve().parent != root.resolve():
        raise CatalogError("Unsafe cleanup target.")
    shutil.rmtree(path)


def _cleanup(root, source):
    keep = {source.active_snapshot, source.previous_snapshot} if source else set()
    removed = 0
    for path in root.iterdir():
        if path.name not in keep and path.is_dir() and (re.fullmatch(r"[a-f0-9]{40}(?:-metadata)?", path.name) or path.name.startswith("staging-")):
            _remove_snapshot(root, path)
            removed += 1
    return removed


def cleanup_catalog():
    root = storage_root() / FreeExerciseDBSource.source_id
    with source_lock(root):
        return _cleanup(root, db.session.get(ExerciseCatalogSource, FreeExerciseDBSource.source_id))


def sync_catalog(*, source=None, ref="main", dry_run=False, metadata_only=False):
    source = source or FreeExerciseDBSource()
    if source.source_id != FreeExerciseDBSource.source_id:
        raise CatalogError("Unsupported source.")
    started = time.monotonic()
    root = storage_root() / source.source_id
    with source_lock(root):
        with tempfile.TemporaryDirectory(prefix="staging-", dir=root) as temp:
            snapshot = source.fetch(Path(temp), ref, metadata_only)
            if not re.fullmatch(r"[a-f0-9]{40}", source.source_revision):
                raise CatalogError("Invalid snapshot revision.")
            content = (snapshot / "exercises.json").read_bytes()
            entries = source.validate(content)
            normalized = source.normalize(entries)
            media = {} if metadata_only else source.media(snapshot, entries)
            manifest = {"source": source.source_id, "source_name": source.source_name, "repository": source.repository,
                "commit_sha": source.source_revision, "license": source.license,
                "downloaded_at": datetime.now(timezone.utc).isoformat(), "exercise_count": len(entries),
                "media_count": sum(len(items) for items in media.values()), "metadata_sha256": hashlib.sha256(content).hexdigest(),
                "metadata_only": metadata_only, "snapshot_bytes": sum(p.stat().st_size for p in snapshot.rglob("*") if p.is_file())}
            payload_bytes = manifest["snapshot_bytes"]
            archive = Path(temp) / "download.tar.gz"
            manifest["archive_bytes"] = archive.stat().st_size if archive.exists() else None
            # Include the manifest itself in the storage measurement.
            while True:
                encoded = json.dumps(manifest, indent=2).encode("utf-8")
                size = payload_bytes + len(encoded)
                if size == manifest["snapshot_bytes"]:
                    break
                manifest["snapshot_bytes"] = size
            (snapshot / "manifest.json").write_bytes(encoded)
            key = source.source_revision + ("-metadata" if metadata_only else "")
            state = db.session.get(ExerciseCatalogSource, source.source_id)
            report = manifest | {"dry_run": dry_run, "added_rows": 0, "elapsed_seconds": round(time.monotonic() - started, 3)}
            if dry_run:
                return report
            target = root / key
            # A retained or crash-orphan snapshot is reusable only if every file
            # has exactly the content just validated. Never replace active files.
            if target.exists():
                if target.is_symlink() or target.resolve().parent != root.resolve():
                    raise CatalogError("Unsafe snapshot target.")
                for path in snapshot.rglob("*"):
                    if path.is_file() and path.name != "manifest.json":
                        old = target / path.relative_to(snapshot)
                        if not old.resolve().is_relative_to(target.resolve()) or old.is_symlink() or not old.is_file() or hashlib.sha256(old.read_bytes()).digest() != hashlib.sha256(path.read_bytes()).digest():
                            raise CatalogError("Stored snapshot differs; inspect storage before retrying.")
                manifest = json.loads((target / "manifest.json").read_bytes())
            else:
                snapshot.rename(target)
            if state and state.active_snapshot == key:
                return state.manifest | {"dry_run": False, "added_rows": 0, "unchanged": True, "elapsed_seconds": round(time.monotonic() - started, 3)}
            try:
                if state is None:
                    state = ExerciseCatalogSource(source_id=source.source_id, manifest={})
                    db.session.add(state)
                    db.session.flush()
                rows = db.session.execute(db.select(ExternalExercise).where(ExternalExercise.source == source.source_id)).scalars().all()
                by_id = {row.external_id: row for row in rows}
                for row in rows:
                    row.available = False
                    row.media = []  # Removed entries keep identity, never stale files.
                for values in normalized:
                    row = by_id.get(values["external_id"])
                    if row is None:
                        row = ExternalExercise(source=source.source_id, external_id=values["external_id"])
                        db.session.add(row)
                        report["added_rows"] += 1
                    row.name = values["name"]
                    row.normalized_name = values["normalized_name"]
                    row.details = values["details"]
                    row.media = media.get(row.external_id, [])
                    row.available = True
                state.previous_snapshot = state.active_snapshot
                state.active_snapshot = key
                state.manifest = manifest
                db.session.commit()
            except Exception:
                db.session.rollback()
                # Leave an immutable orphan for explicit cleanup/retry. The
                # former DB pointer and all former files remain intact.
                raise
        try:
            _cleanup(root, state)
        except (CatalogError, OSError):
            report["cleanup_pending"] = True
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        return report


def catalog_status():
    state = db.session.get(ExerciseCatalogSource, FreeExerciseDBSource.source_id)
    path = storage_root()
    while not path.exists():
        path = path.parent
    return {"source": FreeExerciseDBSource.source_id, "active_revision": state.manifest.get("commit_sha") if state else None,
        "exercise_count": state.manifest.get("exercise_count", 0) if state else 0,
        "media_count": state.manifest.get("media_count", 0) if state else 0,
        "last_sync": state.manifest.get("downloaded_at") if state else None,
        "available_storage_bytes": shutil.disk_usage(path).free}


def external_catalog():
    return db.session.execute(db.select(ExternalExercise).where(ExternalExercise.available.is_(True)).order_by(ExternalExercise.name)).scalars().all()


def resolve_external(name, identities, entries, *, source=None, external_id=None, public_id=None):
    """Exact matches only. All owner identities must be prefetched by the caller."""
    if public_id or (source and external_id):
        return [row for row in entries if (row.public_id == public_id if public_id else row.source == source and row.external_id == external_id)]
    normalized = normalize_exercise_name(name)
    personal = [item for item in identities if normalized in {item.normalized_name, *(a.normalized_name for a in item.aliases if a.user_id == item.user_id)}]
    mapped = {item.external_catalog_id for item in personal if item.external_catalog_id}
    if mapped:
        return [row for row in entries if row.id in mapped]
    exact = [row for row in entries if row.name == name]
    if exact:
        return exact
    # Existing owner aliases supply names; no shared translated aliases are invented.
    aliases = {a.alias_name for item in personal for a in item.aliases if a.user_id == item.user_id}
    aliases.update(item.canonical_name for item in personal)
    exact = [row for row in entries if row.name in aliases]
    if exact:
        return exact
    names = {normalized, *(normalize_exercise_name(n) for n in aliases)}
    return [row for row in entries if row.normalized_name in names]


def media_entry(row, state):
    urls = [url_for("exercise_catalog.media", source=row.source, external_id=row.external_id, position=m["position"], revision=state.active_snapshot) for m in row.media]
    return {"media_asset_id": "catalog:" + row.public_id, "source": row.source, "external_exercise_id": row.external_id,
        "name": row.name, "aliases": [], **row.details, "equipment": [row.details["equipment"]] if row.details.get("equipment") else [],
        "tags": [row.details["category"]], "thumbnail_url": urls[0] if urls else "", "media_url": urls[0] if urls else "", "gallery": urls,
        "media_type": "image", "author": state.manifest.get("source_name"), "license": state.manifest.get("license"),
        "source_url": state.manifest.get("repository"), "license_url": "https://unlicense.org/", "changes": "Snapshot local · " + state.manifest.get("commit_sha", "")[:12]}


def candidate_report(name, identities, entries):
    """Suggestions are read-only, never fed back into automatic resolution."""
    exact = resolve_external(name, identities, entries)
    if exact:
        return [{"row": row, "reason": "Coincidencia exacta" if len(exact) == 1 else "Coincidencia ambigua; selecciona la variante", "confidence": "exact" if len(exact) == 1 else "ambiguous"} for row in exact]
    # Broad search hint only; never an identity alias or automatic match.
    term = "leg press" if normalize_exercise_name(name) == "prensa" else name.casefold()
    return [{"row": row, "reason": "Candidato por búsqueda; confirma variante y equipo", "confidence": "manual_review"} for row in entries if term in row.name.casefold()][:20]
