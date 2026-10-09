"""Local catalog pages and public, content-versioned reference images."""
from flask import Blueprint, abort, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Exercise, ExerciseCatalogSource, ExternalExercise
from app.services.exercise_catalog import external_catalog, media_entry, resolve_external, storage_root
from app.services.exercise_catalog_source import CatalogError, safe_relative
from app.services.gym_programs import catalog

catalog_bp = Blueprint("exercise_catalog", __name__)


def _item(public_id):
    return db.session.execute(db.select(ExternalExercise).where(ExternalExercise.public_id == public_id)).scalar_one_or_none() or abort(404)


@catalog_bp.get("/exercise-catalog")
@login_required
def index():
    entries = external_catalog()
    filters = {key: request.args.get(key, "").strip()[:200] for key in ("q", "muscle", "equipment", "category", "difficulty")}
    facets = {key: sorted({value for row in entries for value in (row.details.get("primary_muscles", []) if key == "muscle" else [row.details.get(key)]) if value}) for key in ("muscle", "equipment", "category", "difficulty")}
    aliases = {}
    for identity in catalog(current_user.id):
        matches = resolve_external(identity.canonical_name, [identity], entries)
        if len(matches) == 1:
            aliases.setdefault(matches[0].id, []).extend([identity.canonical_name, *(a.alias_name for a in identity.aliases)])
    def matches(row):
        values = row.details
        terms = " ".join([row.name, *values.get("primary_muscles", []), *values.get("secondary_muscles", []), values.get("equipment") or "", *aliases.get(row.id, [])]).casefold()
        return (not filters["q"] or filters["q"].casefold() in terms) and all(not filters[key] or (filters[key] in values.get("primary_muscles", []) if key == "muscle" else filters[key] == values.get(key)) for key in facets)
    filtered = [row for row in entries if matches(row)]
    pages = max(1, (len(filtered) + 47) // 48)
    page = max(1, min(request.args.get("page", 1, type=int), pages))
    states = {state.source_id: state for state in db.session.execute(db.select(ExerciseCatalogSource)).scalars()}
    cards = [(row, media_entry(row, states[row.source])) for row in filtered[(page-1)*48:page*48]]
    return render_template("gym/catalog.html", cards=cards, filters=filters, facets=facets, count=len(filtered), page=page, pages=pages)


@catalog_bp.get("/exercise-catalog/<public_id>")
@login_required
def detail(public_id):
    row = _item(public_id)
    state = db.session.get(ExerciseCatalogSource, row.source)
    return render_template("gym/catalog_detail.html", row=row, entry=media_entry(row, state), identities=catalog(current_user.id))


@catalog_bp.post("/exercise-catalog/<public_id>/map")
@login_required
def map_identity(public_id):
    row = _item(public_id)
    if not row.available:
        abort(409)
    from app.services.gym_programs import lock_user
    lock_user(current_user.id)
    identity = db.session.execute(db.select(Exercise).where(Exercise.public_id == request.form.get("exercise_id"), Exercise.user_id == current_user.id)).scalar_one_or_none()
    if identity is None:
        abort(404)
    identity.external_catalog_id = row.id
    db.session.commit()
    return redirect(url_for("exercise_catalog.detail", public_id=row.public_id))


@catalog_bp.get("/exercise-catalog/media.json")
@login_required
def media_catalog_json():
    from app.services.gym_media import media_catalog
    states = {state.source_id: state for state in db.session.execute(db.select(ExerciseCatalogSource)).scalars()}
    response = jsonify(entries=media_catalog() + [media_entry(row, states[row.source]) for row in external_catalog()])
    response.headers["Cache-Control"] = "no-store"
    return response


@catalog_bp.get("/exercise-media/<source>/<external_id>/<int:position>")
def media(source, external_id, position):
    row = db.session.execute(db.select(ExternalExercise).where(ExternalExercise.source == source, ExternalExercise.external_id == external_id, ExternalExercise.available.is_(True))).scalar_one_or_none()
    if row is None or row.external_id != external_id:
        abort(404)
    state = db.session.get(ExerciseCatalogSource, source)
    if request.args.get("revision") != state.active_snapshot:
        abort(404)
    medium = next((m for m in row.media if m["position"] == position), None)
    if medium is None or medium["mime_type"] not in {"image/jpeg", "image/png"}:
        abort(404)
    root = storage_root() / source / state.active_snapshot
    try:
        path = root / safe_relative(medium["relative_path"])
        if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink() or not path.is_file():
            abort(404)
    except (CatalogError, OSError):
        abort(404)
    response = send_file(path, mimetype=medium["mime_type"], conditional=True, etag=medium["sha256"], max_age=86400)
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
