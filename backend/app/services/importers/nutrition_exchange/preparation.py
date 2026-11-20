"""Select the isolated exchange engine and prepare owner-scoped review data."""

from hashlib import sha256
import json
from uuid import uuid4

from flask import current_app

from app.extensions import db
from app.models import DailyNutrition, MealLog
from app.services.nutrition_math import NutritionError, decimal

from . import common, intake, normalize, projection
from . import revisions
from .source import issue

# Escaped evidence can exceed the input size. Bound the technical draft before
# the SQL transport and before creating an original.
MAX_REVIEW_BYTES = 4 * 1024 * 1024


def enabled():
    return web_enabled() or (current_app.testing and current_app.config.get("NUTRITION_EXCHANGE_QA_ENABLED") is True)


def web_enabled():
    return current_app.config.get("NUTRITION_EXCHANGE_ENABLED") is True


def _object(value):
    return value if isinstance(value, dict) else {}


def _existing_candidates(user_id, dates, *, lock=False):
    if not dates:
        return {}, {}
    query = db.select(MealLog.local_date, MealLog.snapshot_json, MealLog.id, MealLog.revision).where(
        MealLog.user_id == user_id, MealLog.local_date.in_(dates)
    ).order_by(MealLog.id)
    existing = db.session.execute(query.with_for_update() if lock else query)
    candidates = {}
    for day, snapshot, record_id, revision in existing:
        snapshot = _object(snapshot)
        declaration = _object(snapshot.get("declared_nutrition"))
        provenance = _object(declaration.get("provenance"))
        source = _object(provenance.get("source_provenance"))
        original = _object(_object(source.get("food")).get("quantity"))
        quantity = original or _object(provenance.get("consumed_quantity"))
        unit = quantity.get("unit")
        name = snapshot.get("name")
        if not isinstance(name, str) or not isinstance(unit, str) or unit not in {"g", "ml", "piece", "portion"}:
            continue
        try:
            amount = decimal(quantity.get("amount"), positive=True)
        except NutritionError:
            continue
        candidate = normalize.DuplicateCandidate(
            day, snapshot.get("meal_type") if isinstance(snapshot.get("meal_type"), str) else None,
            normalize.label(name).casefold(), amount, unit,
            normalize.label(quantity.get("label")) or None,
        )
        energy = _object(_object(snapshot.get("summary")).get("energy")).get("value")
        try:
            energy = str(decimal(energy)) if energy is not None else None
        except NutritionError:
            energy = None
        candidates.setdefault(candidate, []).append((
            (record_id, revision), name, "En tu historial", energy,
        ))
    query = db.select(DailyNutrition).where(
        DailyNutrition.user_id == user_id, DailyNutrition.date.in_(dates)
    )
    days = db.session.scalars(query.with_for_update() if lock else query)
    return candidates, {day.date.isoformat(): (
        revisions._stamp((day.id, day.authority, day.updated_at, day.calories, day.nutrition_summary_json)),
        day.authority is None, str(day.calories) if day.calories is not None else None,
    ) for day in days}


def extract_exchange(payload, filename, mime, user_id, *, decisions=None, options=None, lock=False):
    """Return exchange extractor data, or let the original importer handle it."""
    if not enabled():
        return None
    if not (str(filename).lower().endswith(".json") or mime == "application/json" or
            payload.removeprefix(b"\xef\xbb\xbf").lstrip().startswith((b"{", b"["))):
        return None
    try:
        return _extract_json(payload, user_id, decisions=decisions, options=options, lock=lock)
    except NutritionError:
        raise
    except Exception as error:
        if not web_enabled():
            raise
        reference = str(uuid4())
        current_app.logger.error("nutrition_exchange_error request_id=%s type=%s", reference, type(error).__name__)
        raise NutritionError(f"No se pudo preparar la revisión. Referencia de incidencia {reference}.", 500) from None


def _extract_json(payload, user_id, *, decisions, options, lock):
    try:
        parsed = intake.parse(payload, schema_root=current_app.config.get("SCHEMA_ROOT"))
    except intake.IntakeError as error:
        if all(item.code == "unsupported_format" for item in error.diagnostics):
            return None
        raise
    if parsed.profile in {"standard_2_1", "daily_1_0"}:
        return None

    original = parsed.batch if parsed.batch is not None else common.adapt(parsed.document)
    batch, edits = revisions.adjusted(original, options or {}) if web_enabled() else (original, {})
    days = {meal.date for meal in batch.meals if meal.date is not None}
    existing, overlaps = _existing_candidates(user_id, days, lock=lock) if batch.destination_hint == "consumed" else ({}, {})
    result = normalize.evaluate(batch, decisions=decisions or edits, existing=existing,
                                aggregate_dates={day for day in days if day.isoformat() in overlaps})
    if not result.records:
        diagnostics = result.diagnostics or (issue("missing_foods", severity="invalid"),)
        raise intake.IntakeError(diagnostics, status=422)
    found = projection.extracted(result, parsed.document, sha256(payload).hexdigest())
    if web_enabled():
        revisions.decorate(found, result, original, options or {}, existing, overlaps)
    if len(json.dumps(found, ensure_ascii=True)) > MAX_REVIEW_BYTES:
        raise intake.IntakeError((issue("limit_exceeded", severity="invalid"),), status=413)
    return found
