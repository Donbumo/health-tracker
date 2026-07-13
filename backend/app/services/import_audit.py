from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.extensions import db
from app.models import ImportRun


AUDIT_SCHEMA_VERSION = "1.0"
MAX_ERROR_MESSAGE_LENGTH = 500
MAX_METADATA_STRING_LENGTH = 200
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

ALLOWED_METADATA_KEYS = {
    "schema_version",
    "requested_type",
    "detected_type",
    "source_path",
    "document_count",
    "route",
    "mode",
    "contract_version",
    "operation_names",
    "backup_sha256",
    "manifest_sha256",
    "file_count",
    "byte_count",
    "cleanup_status",
}


class ImportAuditService:
    """Persist privacy-preserving audit summaries for confirmed imports."""

    def create_pending(
        self,
        *,
        user_id: int,
        target_type: str,
        source_type: str | None,
        payload_sha256: str,
        plan_sha256: str,
        summary: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> ImportRun:
        run = ImportRun(
            user_id=user_id,
            target_type=target_type,
            source_type=source_type,
            status="pending",
            payload_sha256=payload_sha256,
            plan_sha256=plan_sha256,
            metadata_json=self.safe_metadata(metadata, summary),
        )
        self._apply_counts(run, summary)
        db.session.add(run)
        return run

    def record_pending(
        self,
        *,
        user_id: int,
        target_type: str,
        source_type: str | None,
        payload_sha256: str,
        plan_sha256: str,
        summary: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> ImportRun:
        run = self.create_pending(
            user_id=user_id,
            target_type=target_type,
            source_type=source_type,
            payload_sha256=payload_sha256,
            plan_sha256=plan_sha256,
            summary=summary,
            metadata=metadata,
        )
        db.session.commit()
        return run

    def finalize_succeeded(self, run: ImportRun, summary: dict[str, Any]) -> ImportRun:
        run.status = "succeeded"
        run.completed_at = _utcnow()
        run.error_code = None
        run.error_message = None
        self._apply_counts(run, summary)
        db.session.add(run)
        return run

    def record_blocked(
        self,
        *,
        user_id: int,
        target_type: str,
        source_type: str | None,
        payload_sha256: str,
        plan_sha256: str,
        summary: dict[str, Any],
        error_message: str,
        metadata: dict[str, Any] | None = None,
    ) -> ImportRun:
        run = self.create_pending(
            user_id=user_id,
            target_type=target_type,
            source_type=source_type,
            payload_sha256=payload_sha256,
            plan_sha256=plan_sha256,
            summary=summary,
            metadata=metadata,
        )
        run.status = "blocked"
        run.completed_at = _utcnow()
        run.error_code = "blocked"
        run.error_message = sanitize_error(error_message)
        db.session.add(run)
        db.session.commit()
        return run

    def record_failed(
        self,
        *,
        user_id: int,
        target_type: str,
        source_type: str | None,
        payload_sha256: str,
        plan_sha256: str,
        summary: dict[str, Any],
        error_message: str,
        metadata: dict[str, Any] | None = None,
    ) -> ImportRun:
        run = self.create_pending(
            user_id=user_id,
            target_type=target_type,
            source_type=source_type,
            payload_sha256=payload_sha256,
            plan_sha256=plan_sha256,
            summary=summary,
            metadata=metadata,
        )
        run.status = "failed"
        run.completed_at = _utcnow()
        run.error_code = "write_failed"
        run.error_message = sanitize_error(error_message)
        db.session.add(run)
        db.session.commit()
        return run

    def record_failed_existing(
        self,
        *,
        run_id: int,
        summary: dict[str, Any],
        error_message: str,
        fallback: dict[str, Any],
    ) -> ImportRun:
        run = db.session.get(ImportRun, run_id)
        if run is None:
            return self.record_failed(
                user_id=fallback["user_id"],
                target_type=fallback["target_type"],
                source_type=fallback.get("source_type"),
                payload_sha256=fallback["payload_sha256"],
                plan_sha256=fallback["plan_sha256"],
                summary=summary,
                error_message=error_message,
                metadata=fallback.get("metadata"),
            )
        run.status = "failed"
        run.completed_at = _utcnow()
        run.error_code = "write_failed"
        run.error_message = sanitize_error(error_message)
        self._apply_counts(run, summary)
        db.session.add(run)
        db.session.commit()
        return run

    def list_runs(
        self,
        *,
        user_id: int,
        page: int = 1,
        per_page: int = DEFAULT_PAGE_SIZE,
    ) -> list[ImportRun]:
        safe_page = max(page, 1)
        safe_per_page = min(max(per_page, 1), MAX_PAGE_SIZE)
        return db.session.execute(
            db.select(ImportRun)
            .where(ImportRun.user_id == user_id)
            .order_by(ImportRun.started_at.desc(), ImportRun.id.desc())
            .limit(safe_per_page)
            .offset((safe_page - 1) * safe_per_page)
        ).scalars().all()

    def get_run(self, *, user_id: int, run_id: int) -> ImportRun | None:
        return db.session.execute(
            db.select(ImportRun).where(
                ImportRun.id == run_id,
                ImportRun.user_id == user_id,
            )
        ).scalar_one_or_none()

    def safe_metadata(
        self,
        metadata: dict[str, Any] | None,
        summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        safe: dict[str, Any] = {"schema_version": AUDIT_SCHEMA_VERSION}
        for key, value in (metadata or {}).items():
            if key not in ALLOWED_METADATA_KEYS:
                continue
            safe_value = _safe_metadata_value(value)
            if safe_value is not None:
                safe[key] = safe_value

        if summary is not None:
            safe["document_count"] = int(summary.get("total") or 0)
            operations = summary.get("operations") or []
            operation_names = sorted({
                str(operation.get("operation"))
                for operation in operations
                if operation.get("operation")
            })
            if operation_names:
                safe["operation_names"] = operation_names
        return safe

    @staticmethod
    def _apply_counts(run: ImportRun, summary: dict[str, Any]) -> None:
        run.total_count = int(summary.get("total") or 0)
        run.insert_count = int(summary.get("inserts") or 0)
        run.update_count = int(summary.get("updates") or 0)
        run.skip_count = int(summary.get("skips") or 0)
        run.conflict_count = int(summary.get("conflicts") or 0)
        run.invalid_count = int(summary.get("invalid") or 0)


def sanitize_error(message: Any) -> str:
    text = " ".join(str(message or "Import failed").split())
    if len(text) > MAX_ERROR_MESSAGE_LENGTH:
        return text[: MAX_ERROR_MESSAGE_LENGTH - 3] + "..."
    return text


def _safe_metadata_value(value: Any) -> Any | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return value[:MAX_METADATA_STRING_LENGTH]
    if isinstance(value, (list, tuple)):
        safe_items = []
        for item in value[:20]:
            safe_item = _safe_metadata_value(item)
            if isinstance(safe_item, (str, int, bool)):
                safe_items.append(safe_item)
        return safe_items
    return None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
