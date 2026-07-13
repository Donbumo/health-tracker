from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from flask import current_app

from app.extensions import db
from app.models import ExportRecord, ImportRun, UploadedFile
from app.services.backups import (
    BACKUP_RESTORE_TARGET,
    BackupError,
    _data_path,
    _remove_tree,
    _sha256_path,
    _staging_root,
)

# Pattern for paths that are entirely internal/safe (no user-supplied names).
# Matches: alphanumeric, underscore, hyphen, period, forward slash, space.
_SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9_./ -]+$")

_STORAGE_KIND_MAP = {
    "UPLOAD_ROOT": "raw",
    "GENERATED_UPLOAD_ROOT": "generated",
}

_CATEGORY_FALLBACK = "unknown"


class BackupReconciliationService:
    """Detect storage/database drift; apply only safe status and staging repairs."""

    def reconcile(
        self,
        *,
        apply: bool = False,
        stale_after_hours: int = 24,
    ) -> dict[str, Any]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max(stale_after_hours, 1))
        report: dict[str, Any] = {
            "mode": "apply" if apply else "dry-run",
            "missing_uploads": 0,
            "corrupt_uploads": 0,
            "missing_exports": 0,
            "corrupt_exports": 0,
            "orphan_files": 0,
            "stale_staging": 0,
            "abandoned_runs": 0,
            "records_updated": 0,
            "staging_removed": 0,
            "suspicious_symlinks": 0,
        }
        known_paths: set[Path] = set()

        for upload in db.session.execute(db.select(UploadedFile)).scalars():
            try:
                path = _data_path(upload.storage_path)
            except BackupError:
                report["missing_uploads"] += 1
                self._mark_upload_error(upload, apply, report)
                continue
            known_paths.add(path.resolve())
            if not path.is_file():
                report["missing_uploads"] += 1
                self._mark_upload_error(upload, apply, report)
                continue
            digest, size = _sha256_path(path)
            if digest != upload.sha256 or size != upload.size_bytes:
                report["corrupt_uploads"] += 1
                self._mark_upload_error(upload, apply, report)

        for record in db.session.execute(
            db.select(ExportRecord).where(ExportRecord.status == "ready")
        ).scalars():
            try:
                path = _data_path(record.relative_path)
            except BackupError:
                report["missing_exports"] += 1
                self._mark_export_deleted(record, apply, report)
                continue
            known_paths.add(path.resolve())
            if not path.is_file():
                report["missing_exports"] += 1
                self._mark_export_deleted(record, apply, report)
                continue
            digest, size = _sha256_path(path)
            if digest != record.sha256 or size != record.size_bytes:
                report["corrupt_exports"] += 1
                self._mark_export_deleted(record, apply, report)

        orphan_details: list[dict[str, Any]] = []
        orphan_details_skipped = 0
        suspicious_symlink_details: list[dict[str, Any]] = []

        # Pre-fetch known storage paths for matching_database_record
        db_paths: set[str] = set()
        for u_path in db.session.execute(db.select(UploadedFile.storage_path)).scalars():
            if u_path:
                db_paths.add(u_path)
        for e_path in db.session.execute(db.select(ExportRecord.relative_path)).scalars():
            if e_path:
                db_paths.add(e_path)

        data_root = Path(current_app.config["DATA_ROOT"]).resolve()

        for root_key in ("UPLOAD_ROOT", "GENERATED_UPLOAD_ROOT"):
            root = Path(current_app.config[root_key])
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                if path.is_symlink():
                    report["suspicious_symlinks"] += 1
                    if not apply:
                        try:
                            relative = str(path.relative_to(data_root).as_posix())
                        except ValueError:
                            relative = str(path.as_posix())
                        storage_kind = "raw" if root_key == "UPLOAD_ROOT" else "generated"
                        fingerprint = hashlib.sha256(f"{storage_kind}:{relative}".encode("utf-8")).hexdigest()
                        suspicious_symlink_details.append({
                            "storage_kind": storage_kind,
                            "path_fingerprint": fingerprint,
                            "reason": "symlink_not_allowed"
                        })
                    continue

                if path.is_file():
                    if path.name == ".gitkeep" and path.parent == root:
                        continue
                    if path.resolve() not in known_paths:
                        report["orphan_files"] += 1
                        if not apply:
                            detail = self._orphan_detail(root_key, root, path, data_root, db_paths)
                            if detail is not None:
                                orphan_details.append(detail)
                            else:
                                orphan_details_skipped += 1

        if not apply:
            if orphan_details:
                orphan_details.sort(
                    key=lambda d: (
                        d["storage_kind"],
                        d.get("relative_path") or d.get("path_fingerprint", ""),
                    )
                )
                report["orphan_details"] = orphan_details
            if orphan_details_skipped > 0:
                report["orphan_details_skipped"] = orphan_details_skipped
            if suspicious_symlink_details:
                suspicious_symlink_details.sort(
                    key=lambda d: (d["storage_kind"], d["path_fingerprint"])
                )
                report["suspicious_symlink_details"] = suspicious_symlink_details

        staging = _staging_root()
        for user_directory in staging.glob("user_*"):
            if not user_directory.is_dir() or user_directory.is_symlink():
                continue
            for directory in user_directory.iterdir():
                if not directory.is_dir() or directory.is_symlink():
                    continue
                modified = datetime.fromtimestamp(
                    directory.stat().st_mtime,
                    tz=timezone.utc,
                )
                if modified < cutoff:
                    report["stale_staging"] += 1
                    if apply:
                        _remove_tree(directory)
                        report["staging_removed"] += 1

        for run in db.session.execute(
            db.select(ImportRun).where(
                ImportRun.target_type == BACKUP_RESTORE_TARGET,
                ImportRun.status == "pending",
            )
        ).scalars():
            started = run.started_at
            if started is not None and started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            if started is not None and started < cutoff:
                report["abandoned_runs"] += 1
                if apply:
                    run.status = "failed"
                    run.completed_at = datetime.now(timezone.utc)
                    run.error_code = "reconciled_pending"
                    run.error_message = "Abandoned backup restore was marked failed by reconciliation."
                    db.session.add(run)
                    report["records_updated"] += 1

        if apply:
            db.session.commit()
        else:
            db.session.rollback()
        return report

    @staticmethod
    def _orphan_detail(
        root_key: str,
        root: Path,
        path: Path,
        data_root: Path,
        db_paths: set[str],
    ) -> dict[str, Any] | None:
        """Return allowlisted metadata for an orphan file. Returns None on vanished file."""
        storage_kind = _STORAGE_KIND_MAP.get(root_key, "unknown")
        try:
            relative = path.resolve().relative_to(root.resolve()).as_posix()
            data_relative = path.resolve().relative_to(data_root).as_posix()
        except ValueError:
            return None

        if _is_canonical_internal_path(storage_kind, relative):
            path_info: dict[str, Any] = {"relative_path": relative}
        else:
            fingerprint = hashlib.sha256(f"{storage_kind}:{relative}".encode("utf-8")).hexdigest()
            path_info = {"path_fingerprint": fingerprint}

        try:
            stat_result = path.stat()
            size_bytes = stat_result.st_size
            modified_at = datetime.fromtimestamp(
                stat_result.st_mtime, tz=timezone.utc
            ).isoformat()
        except OSError:
            # File vanished between scan and stat; skip silently.
            return None

        try:
            sha256, _ = _sha256_path(path)
        except OSError:
            # File vanished between scan and hash; skip silently.
            return None

        probable_category = _classify_orphan(storage_kind, relative)
        matching_db = data_relative in db_paths

        detail: dict[str, Any] = {
            "storage_kind": storage_kind,
            "size_bytes": size_bytes,
            "sha256": sha256,
            "modified_at": modified_at,
            "probable_category": probable_category,
            "matching_database_record": matching_db,
        }
        detail.update(path_info)
        return detail

    @staticmethod
    def _mark_upload_error(
        upload: UploadedFile,
        apply: bool,
        report: dict[str, Any],
    ) -> None:
        if apply:
            upload.import_status = "error"
            upload.error_message = "Managed file is missing or failed integrity reconciliation."
            db.session.add(upload)
            report["records_updated"] += 1

    @staticmethod
    def _mark_export_deleted(
        record: ExportRecord,
        apply: bool,
        report: dict[str, Any],
    ) -> None:
        if apply:
            record.status = "deleted"
            warnings = list(record.warnings_json or [])
            warnings.append("File missing or corrupt during reconciliation.")
            record.warnings_json = warnings[-20:]
            db.session.add(record)
            report["records_updated"] += 1


def _is_canonical_internal_path(storage_kind: str, relative_path: str) -> bool:
    """Explicit validation of the canonical internal layout for safety."""
    if storage_kind == "raw":
        # Format: user_\d+/[a-f0-9]{64}
        return bool(re.match(r"^user_\d+/[a-f0-9]{64}$", relative_path))
    if storage_kind == "generated":
        # Format: user_\d+/[a-f0-9]{64}\.json
        if re.match(r"^user_\d+/[a-f0-9]{64}\.json$", relative_path):
            return True
        # Format: exports/user_\d+/[a-f0-9]{32}\.[a-z0-9]+
        if re.match(r"^exports/user_\d+/[a-f0-9]{32}\.[a-z0-9]+$", relative_path):
            return True
        # Format: backups/user_\d+/health_tracker_backup_[a-f0-9]{32}\.zip
        if re.match(r"^backups/user_\d+/health_tracker_backup_[a-f0-9]{32}\.zip$", relative_path):
            return True
        # Format: restored/user_\d+/[a-f0-9]{32}\.[a-z0-9]+
        if re.match(r"^restored/user_\d+/[a-f0-9]{32}\.[a-z0-9]+$", relative_path):
            return True
    return False


def _classify_orphan(storage_kind: str, relative_path: str) -> str:
    """Heuristic classification of an orphan file based on its location. NOT definitive."""
    parts = relative_path.lower().split("/")
    if "staging" in parts or "tmp" in parts or "qa" in parts or ".generating" in relative_path:
        return "qa_artifact"

    if _is_canonical_internal_path(storage_kind, relative_path):
        if storage_kind == "raw":
            return "legacy_upload"
        if storage_kind == "generated":
            return "legacy_generated"

    return _CATEGORY_FALLBACK
