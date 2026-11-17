"""Select the isolated exchange engine and prepare owner-scoped review data."""

from hashlib import sha256
import json

from flask import current_app

from app.extensions import db
from app.models import DailyNutrition, MealLog
from app.services.nutrition_math import NutritionError, decimal

from . import common, intake, normalize, projection
from .source import issue

# Escaped evidence can exceed the input size. Bound the technical draft before
# the SQL transport and before creating an original.
MAX_REVIEW_BYTES = 4 * 1024 * 1024


def enabled():
    return current_app.testing and current_app.config.get("NUTRITION_EXCHANGE_QA_ENABLED") is True


def _object(value):
    return value if isinstance(value, dict) else {}


def _existing_candidates(user_id, dates):
    if not dates:
        return (), frozenset()
    existing = db.session.execute(
        db.select(MealLog.local_date, MealLog.snapshot_json).where(
            MealLog.user_id == user_id, MealLog.local_date.in_(dates)
        )
    )
    candidates = []
    for day, snapshot in existing:
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
        candidates.append(normalize.DuplicateCandidate(
            day, snapshot.get("meal_type") if isinstance(snapshot.get("meal_type"), str) else None,
            normalize.label(name).casefold(), amount, unit,
            normalize.label(quantity.get("label")) or None,
        ))
    days = db.session.scalars(db.select(DailyNutrition.date).where(
        DailyNutrition.user_id == user_id, DailyNutrition.date.in_(dates)
    ))
    return tuple(candidates), frozenset(days)


def extract_exchange(payload, filename, mime, user_id, *, decisions=None):
    """Return ordinary extractor data for QA JSON, or let the original importer handle it."""
    if not enabled():
        return None
    if not (str(filename).lower().endswith(".json") or mime == "application/json" or
            payload.removeprefix(b"\xef\xbb\xbf").lstrip().startswith((b"{", b"["))):
        return None
    try:
        parsed = intake.parse(payload, schema_root=current_app.config.get("SCHEMA_ROOT"))
    except intake.IntakeError as error:
        if all(item.code == "unsupported_format" for item in error.diagnostics):
            return None
        raise
    if parsed.profile in {"standard_2_1", "daily_1_0"}:
        return None

    batch = parsed.batch if parsed.batch is not None else common.adapt(parsed.document)
    days = {meal.date for meal in batch.meals if meal.date is not None}
    existing, overlaps = _existing_candidates(user_id, days) if batch.destination_hint == "consumed" else ((), frozenset())
    result = normalize.evaluate(batch, decisions=decisions, aggregate_dates=overlaps, existing=existing)
    if not result.records:
        diagnostics = result.diagnostics or (issue("missing_foods", severity="invalid"),)
        raise intake.IntakeError(diagnostics, status=422)
    found = projection.extracted(result, parsed.document, sha256(payload).hexdigest())
    if len(json.dumps(found, ensure_ascii=True)) > MAX_REVIEW_BYTES:
        raise intake.IntakeError((issue("limit_exceeded", severity="invalid"),), status=413)
    return found
