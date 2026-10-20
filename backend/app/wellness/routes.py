from datetime import date, datetime
from io import BytesIO
from zoneinfo import ZoneInfo

from flask import abort, current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import DailyEnergy, DailyNutrition
from app.services.files import UploadError, mark_import_status, store_uploaded_file
from app.services.daily_balance import daily_balance
from app.services import energy_days
from app.services.exporters.wellness import (
    DailyEnergyCsvExporter,
    DailyEnergyJsonExporter,
    DailyNutritionCsvExporter,
    DailyNutritionJsonExporter,
)
from app.services.importers.daily_energy import (
    DailyEnergyImportError,
    import_daily_energy_file,
)
from app.services.importers.daily_nutrition import (
    DailyNutritionImportError,
    import_daily_nutrition_file,
)
from app.services.manual_json import (
    ManualJsonGenerationError,
    build_daily_energy_document,
    build_daily_nutrition_document,
    generate_standard_json,
)
from app.services.validation import JsonSchemaValidationError
from app.wellness import wellness_bp
from app.wellness.forms import (
    DailyEnergyImportForm,
    DailyEnergyEditForm,
    DailyEnergyDeleteForm,
    DailyEnergyManualForm,
    DailyNutritionImportForm,
    DailyNutritionManualForm,
)


ENERGY_EXPORTERS = {
    "json": DailyEnergyJsonExporter(),
    "csv": DailyEnergyCsvExporter(),
}
NUTRITION_EXPORTERS = {
    "json": DailyNutritionJsonExporter(),
    "csv": DailyNutritionCsvExporter(),
}


def _user_energy_or_404(record_id: int) -> DailyEnergy:
    record = db.session.execute(
        db.select(DailyEnergy).where(
            DailyEnergy.id == record_id,
            DailyEnergy.user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if record is None:
        abort(404)
    canonical = energy_days.view(current_user.id, record.date)
    if canonical is None:
        abort(404)
    return canonical


def _user_nutrition_or_404(record_id: int) -> DailyNutrition:
    record = db.session.execute(
        db.select(DailyNutrition).where(
            DailyNutrition.id == record_id,
            DailyNutrition.user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if record is None:
        abort(404)
    return record


@wellness_bp.get("/daily-energy")
@login_required
def energy_list():
    records = energy_days.views(current_user.id)
    return render_template("wellness/energy_list.html", records=records)


@wellness_bp.get("/energy")
@login_required
def energy_experience():
    from app.services.energy_history import consultation, local_today
    today, timezone_name = local_today(current_user, current_app.config['APP_TIMEZONE'])
    try:
        target = date.fromisoformat(request.args['date']) if request.args.get('date') else today
        # Leave room for warm-up and adjacent month/day links at date bounds.
        if not 1900 <= target.year <= 9998:
            raise ValueError()
        period = int(request.args.get('period', 30))
        if period not in (7, 30, 90):
            raise ValueError()
    except ValueError:
        abort(400, description='Fecha o período inválidos. Usa 7, 30 o 90 días.')
    return render_template('wellness/energy_experience.html',
                           **consultation(current_user.id, target, period),
                           today=today, timezone_name=timezone_name)


def _provenance_page(view, **values):
    response = current_app.make_response(render_template('wellness/energy_provenance.html', view=view, **values))
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@wellness_bp.get('/energy/sources')
@login_required
def energy_sources():
    from app.services.energy_history import local_today
    from app.services.energy_provenance import parsed_date, sources
    try:
        target = parsed_date(request.args.get('date')) or local_today(current_user, current_app.config['APP_TIMEZONE'])[0]
    except ValueError:
        abort(400, description='Fecha inválida.')
    return _provenance_page('sources', **sources(current_user.id, target))


@wellness_bp.get('/energy/history')
@login_required
def energy_history():
    from app.services.energy_provenance import filters, audit
    try:
        selected = filters(request.args)
    except (ValueError, TypeError):
        abort(400, description='Filtros inválidos.')
    data = audit(current_user.id, selected)
    args = {'from': selected['start'], 'to': selected['end'],
            'source': selected['source'] or None, 'operation': selected['operation'] or None}
    data['previous_url'] = url_for('wellness.energy_history', page=data['page'] - 1, **args) if data['page'] > 1 else None
    data['next_url'] = url_for('wellness.energy_history', page=data['page'] + 1, **args) if data['page'] < data['pages'] else None
    return _provenance_page('history', **data)


@wellness_bp.post('/energy/original')
@login_required
def energy_original():
    from app.services.energy_provenance import download
    try:
        # The signed locator travels in the CSRF-protected body, never an access
        # log URL. This download reads a verified descriptor; it does not write.
        stream, filename = download(current_user.id, request.form.get('reference', ''))
    except LookupError:
        abort(404)
    response = send_file(stream, mimetype='application/octet-stream', as_attachment=True, download_name=filename)
    response.call_on_close(stream.close)
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@wellness_bp.route("/daily-energy/import", methods=["GET", "POST"])
@login_required
def energy_import():
    form = DailyEnergyImportForm()
    if form.validate_on_submit():
        source_file = None
        try:
            source_file, file_duplicate = store_uploaded_file(
                form.file.data,
                current_user.id,
            )
            record, record_duplicate = import_daily_energy_file(
                source_file,
                current_user.id,
            )
        except (DailyEnergyImportError, JsonSchemaValidationError, UploadError) as error:
            if source_file is not None:
                mark_import_status(
                    source_file,
                    current_user.id,
                    status="error",
                    detected_type="daily_energy",
                    error_message=str(error),
                )
            flash(f"No fue posible importar la energía diaria: {error}", "danger")
        else:
            if getattr(record, '_energy_conflicts', None):
                flash("Se conservó la propuesta de fuente con conflicto. Revisa el día antes de usar esos valores.", "warning")
            duplicate = file_duplicate or record_duplicate
            mark_import_status(
                source_file,
                current_user.id,
                status="duplicate" if duplicate else "imported",
                detected_type="daily_energy",
            )
            flash(
                "Ese archivo de energía ya había sido importado."
                if duplicate
                else "Energía diaria importada correctamente.",
                "warning" if duplicate else "success",
            )
            return redirect(url_for("wellness.energy_detail", record_id=record.id))
    return render_template("wellness/energy_import.html", form=form)


@wellness_bp.get("/daily-energy/<int:record_id>")
@login_required
def energy_detail(record_id: int):
    return render_template(
        "wellness/energy_detail.html",
        record=_user_energy_or_404(record_id),
    )


@wellness_bp.route("/daily-energy/<int:record_id>/edit", methods=["GET", "POST"])
@login_required
def energy_edit(record_id):
    record = _user_energy_or_404(record_id)
    form = DailyEnergyEditForm(obj=record)
    if request.method == "GET":
        form.base_revision.data = str(record.revision)
    if form.validate_on_submit():
        try:
            values = {field: getattr(form, field).data for field in energy_days.FIELDS
                      if getattr(form, field).data is not None and getattr(form, field).data != ""}
            clear = [field for field in energy_days.FIELDS if getattr(form, 'clear_' + field).data]
            updated = energy_days.edit_day(current_user.id, record.date, int(form.base_revision.data), values,
                                           new_date=form.date.data, clear=clear)
            db.session.commit()
        except (energy_days.EnergyConflict, ValueError):
            db.session.rollback()
            flash("No se guardó: el día cambió o la fecha destino ya existe. Recarga y revisa.", "danger")
            return render_template("wellness/energy_edit.html", record=record, form=form), 409
        return redirect(url_for("wellness.energy_detail", record_id=updated.id))
    return render_template("wellness/energy_edit.html", record=record, form=form)


@wellness_bp.route("/daily-energy/<int:record_id>/delete", methods=["GET", "POST"])
@login_required
def energy_delete(record_id):
    record = _user_energy_or_404(record_id)
    form = DailyEnergyDeleteForm()
    if request.method == "GET":
        form.base_revision.data = str(record.revision)
        form.source_public_id.data = request.args.get('source', '')
    source = next((row for row in record.evidence if row.public_id == form.source_public_id.data), None)
    if form.source_public_id.data and source is None:
        abort(404)
    if form.validate_on_submit():
        try:
            if source:
                energy_days.delete_evidence(current_user.id, record.date, source.public_id, int(form.base_revision.data))
            else:
                energy_days.delete_day(current_user.id, record.date, int(form.base_revision.data))
            db.session.commit()
        except (energy_days.EnergyConflict, ValueError):
            db.session.rollback()
            flash("El día cambió. Recarga antes de eliminar.", "danger")
            return render_template("wellness/energy_delete.html", record=record, form=form, source=source), 409
        return redirect(url_for("wellness.energy_list"))
    return render_template("wellness/energy_delete.html", record=record, form=form, source=source)


@wellness_bp.get("/daily-energy/<int:record_id>/export/<string:format_name>")
@login_required
def energy_export(record_id: int, format_name: str):
    record = _user_energy_or_404(record_id)
    exporter = ENERGY_EXPORTERS.get(format_name)
    if exporter is None:
        abort(404)
    artifact = exporter.export(record, current_user.id)
    return send_file(
        BytesIO(artifact.content),
        mimetype=artifact.mimetype,
        as_attachment=True,
        download_name=f"daily_energy_{record.date.isoformat()}.{artifact.extension}",
    )


@wellness_bp.get("/daily-nutrition")
@login_required
def nutrition_list():
    records = db.session.execute(
        db.select(DailyNutrition)
        .where(DailyNutrition.user_id == current_user.id)
        .order_by(DailyNutrition.date.desc())
    ).scalars()
    return render_template("wellness/nutrition_list.html", records=records)


@wellness_bp.route("/daily-nutrition/import", methods=["GET", "POST"])
@login_required
def nutrition_import():
    form = DailyNutritionImportForm()
    if form.validate_on_submit():
        source_file = None
        try:
            source_file, file_duplicate = store_uploaded_file(
                form.file.data,
                current_user.id,
            )
            record, record_duplicate = import_daily_nutrition_file(
                source_file,
                current_user.id,
            )
        except (
            DailyNutritionImportError,
            JsonSchemaValidationError,
            UploadError,
        ) as error:
            if source_file is not None:
                mark_import_status(
                    source_file,
                    current_user.id,
                    status="error",
                    detected_type="daily_nutrition",
                    error_message=str(error),
                )
            flash(f"No fue posible importar la nutrición diaria: {error}", "danger")
        else:
            if getattr(record, '_energy_conflicts', None):
                flash("Se conservó la propuesta de fuente con conflicto. Revisa el día antes de usar esos valores.", "warning")
            duplicate = file_duplicate or record_duplicate
            mark_import_status(
                source_file,
                current_user.id,
                status="duplicate" if duplicate else "imported",
                detected_type="daily_nutrition",
            )
            flash(
                "Ese archivo de nutrición ya había sido importado."
                if duplicate
                else "Nutrición diaria importada correctamente.",
                "warning" if duplicate else "success",
            )
            return redirect(
                url_for("wellness.nutrition_detail", record_id=record.id)
            )
    return render_template("wellness/nutrition_import.html", form=form)


@wellness_bp.get("/daily-nutrition/<int:record_id>")
@login_required
def nutrition_detail(record_id: int):
    return render_template(
        "wellness/nutrition_detail.html",
        record=_user_nutrition_or_404(record_id),
    )


@wellness_bp.get("/daily-nutrition/<int:record_id>/export/<string:format_name>")
@login_required
def nutrition_export(record_id: int, format_name: str):
    record = _user_nutrition_or_404(record_id)
    if record.authority is not None:
        abort(409, description="Este día requiere export de cuenta/backup 2.0 para conservar micros, autoridad y snapshots.")
    exporter = NUTRITION_EXPORTERS.get(format_name)
    if exporter is None:
        abort(404)
    artifact = exporter.export(record, current_user.id)
    return send_file(
        BytesIO(artifact.content),
        mimetype=artifact.mimetype,
        as_attachment=True,
        download_name=f"daily_nutrition_{record.date.isoformat()}.{artifact.extension}",
    )


@wellness_bp.get("/daily-balance")
@login_required
def balance():
    requested_date = request.args.get("date", "").strip()
    if requested_date:
        try:
            target_date = date.fromisoformat(requested_date)
        except ValueError:
            abort(400)
    else:
        target_date = datetime.now(
            ZoneInfo(current_app.config["APP_TIMEZONE"])
        ).date()
    return render_template(
        "wellness/balance.html",
        summary=daily_balance(current_user.id, target_date),
    )


@wellness_bp.route("/manual/energy", methods=["GET", "POST"])
@login_required
def manual_energy():
    form = DailyEnergyManualForm()
    if not form.is_submitted():
        form.date.data = datetime.now(
            ZoneInfo(current_app.config["APP_TIMEZONE"])
        ).date()
    if form.validate_on_submit():
        document = build_daily_energy_document(
            user_id=current_user.id,
            record_date=form.date.data,
            total_calories=form.total_calories.data,
            active_calories=form.active_calories.data,
            resting_calories=form.resting_calories.data,
            steps=form.steps.data,
            distance_meters=form.distance_meters.data,
            notes=form.notes.data,
        )
        source_file = None
        try:
            source_file, file_duplicate = generate_standard_json(
                document=document,
                schema_name="daily_energy",
                user_id=current_user.id,
                original_filename=f"daily_energy_{form.date.data.isoformat()}.json",
            )
            record, record_duplicate = import_daily_energy_file(
                source_file,
                current_user.id,
            )
        except (
            DailyEnergyImportError,
            JsonSchemaValidationError,
            ManualJsonGenerationError,
        ) as error:
            if source_file is not None:
                mark_import_status(
                    source_file,
                    current_user.id,
                    status="error",
                    detected_type="daily_energy",
                    error_message=str(error),
                )
            flash(f"No fue posible guardar la energía diaria: {error}", "danger")
        else:
            if getattr(record, '_energy_conflicts', None):
                flash("Se conservó la propuesta de fuente con conflicto. Revisa el día antes de usar esos valores.", "warning")
            duplicate = file_duplicate or record_duplicate
            mark_import_status(
                source_file,
                current_user.id,
                status="duplicate" if duplicate else "imported",
                detected_type="daily_energy",
            )
            flash(
                "Ese registro de energía ya existía."
                if duplicate
                else "Energía diaria guardada correctamente.",
                "warning" if duplicate else "success",
            )
            return redirect(url_for("wellness.energy_detail", record_id=record.id))
    return render_template("wellness/manual_energy.html", form=form)


@wellness_bp.route("/manual/nutrition", methods=["GET", "POST"])
@login_required
def manual_nutrition():
    from app.models import FoodProduct, Recipe
    form = DailyNutritionManualForm()
    # Populate products choice
    products = db.session.execute(
        db.select(FoodProduct)
        .where(FoodProduct.user_id == current_user.id, FoodProduct.is_active.is_(True))
        .order_by(FoodProduct.name.asc())
    ).scalars().all()
    recipes = db.session.execute(
        db.select(Recipe)
        .where(Recipe.user_id == current_user.id, Recipe.is_active.is_(True), Recipe.nutrition_snapshot_json.is_(None))
        .order_by(Recipe.name.asc())
    ).scalars().all()
    form.food_product_id.choices = [(0, "— Ninguno —")] + [(p.id, p.name) for p in products]
    form.recipe_id.choices = [(0, "— Ninguna —")] + [(r.id, r.name) for r in recipes]

    products_json = []
    for p in products:
        products_json.append({
            "id": p.id,
            "calories_per_100g": float(p.calories_per_100g) if p.calories_per_100g is not None else None,
            "protein_g_per_100g": float(p.protein_g_per_100g) if p.protein_g_per_100g is not None else None,
            "fat_g_per_100g": float(p.fat_g_per_100g) if p.fat_g_per_100g is not None else None,
            "carbs_g_per_100g": float(p.carbs_g_per_100g) if p.carbs_g_per_100g is not None else None,
            "net_carbs_g_per_100g": float(p.net_carbs_g_per_100g) if p.net_carbs_g_per_100g is not None else None,
            "fiber_g_per_100g": float(p.fiber_g_per_100g) if p.fiber_g_per_100g is not None else None,
            "sodium_mg_per_100g": float(p.sodium_mg_per_100g) if p.sodium_mg_per_100g is not None else None,
        })
    recipes_json = []
    for recipe in recipes:
        per_serving = recipe.per_serving()
        per_100g = recipe.per_100g()
        recipes_json.append({
            "id": recipe.id,
            "per_serving": {
                "calories": float(per_serving["calories"]) if per_serving["calories"] is not None else None,
                "protein_g": float(per_serving["protein_g"]) if per_serving["protein_g"] is not None else None,
                "fat_g": float(per_serving["fat_g"]) if per_serving["fat_g"] is not None else None,
                "total_carbs_g": float(per_serving["total_carbs_g"]) if per_serving["total_carbs_g"] is not None else None,
                "net_carbs_g": float(per_serving["net_carbs_g"]) if per_serving["net_carbs_g"] is not None else None,
                "fiber_g": float(per_serving["fiber_g"]) if per_serving["fiber_g"] is not None else None,
                "sodium_mg": float(per_serving["sodium_mg"]) if per_serving["sodium_mg"] is not None else None,
            },
            "per_100g": {
                "calories": float(per_100g["calories"]) if per_100g["calories"] is not None else None,
                "protein_g": float(per_100g["protein_g"]) if per_100g["protein_g"] is not None else None,
                "fat_g": float(per_100g["fat_g"]) if per_100g["fat_g"] is not None else None,
                "total_carbs_g": float(per_100g["total_carbs_g"]) if per_100g["total_carbs_g"] is not None else None,
                "net_carbs_g": float(per_100g["net_carbs_g"]) if per_100g["net_carbs_g"] is not None else None,
                "fiber_g": float(per_100g["fiber_g"]) if per_100g["fiber_g"] is not None else None,
                "sodium_mg": float(per_100g["sodium_mg"]) if per_100g["sodium_mg"] is not None else None,
            },
        })
    if not form.is_submitted():
        form.date.data = datetime.now(
            ZoneInfo(current_app.config["APP_TIMEZONE"])
        ).date()
    if form.validate_on_submit():
        document = build_daily_nutrition_document(
            user_id=current_user.id,
            record_date=form.date.data,
            meal_type=form.meal_type.data,
            meal_name=form.meal_name.data,
            item_name=form.item_name.data,
            food_product_id=form.food_product_id.data if form.food_product_id.data else None,
            recipe_id=form.recipe_id.data if form.recipe_id.data else None,
            quantity=form.quantity.data,
            unit=form.unit.data,
            calories=form.calories.data,
            protein_g=form.protein_g.data,
            fat_g=form.fat_g.data,
            net_carbs_g=form.net_carbs_g.data,
            total_carbs_g=form.total_carbs_g.data,
            fiber_g=form.fiber_g.data,
            sugar_g=form.sugar_g.data,
            sodium_mg=form.sodium_mg.data,
            notes=form.notes.data,
        )
        source_file = None
        try:
            source_file, file_duplicate = generate_standard_json(
                document=document,
                schema_name="daily_nutrition",
                user_id=current_user.id,
                original_filename=f"daily_nutrition_{form.date.data.isoformat()}.json",
            )
            record, record_duplicate = import_daily_nutrition_file(
                source_file,
                current_user.id,
            )
        except (
            DailyNutritionImportError,
            JsonSchemaValidationError,
            ManualJsonGenerationError,
        ) as error:
            if source_file is not None:
                mark_import_status(
                    source_file,
                    current_user.id,
                    status="error",
                    detected_type="daily_nutrition",
                    error_message=str(error),
                )
            flash(f"No fue posible guardar la nutrición diaria: {error}", "danger")
        else:
            if getattr(record, '_energy_conflicts', None):
                flash("Se conservó la propuesta de fuente con conflicto. Revisa el día antes de usar esos valores.", "warning")
            duplicate = file_duplicate or record_duplicate
            mark_import_status(
                source_file,
                current_user.id,
                status="duplicate" if duplicate else "imported",
                detected_type="daily_nutrition",
            )
            flash(
                "Ese registro de nutrición ya existía."
                if duplicate
                else "Nutrición diaria guardada correctamente.",
                "warning" if duplicate else "success",
            )
            return redirect(
                url_for("wellness.nutrition_detail", record_id=record.id)
            )
    return render_template(
        "wellness/manual_nutrition.html",
        form=form,
        products_json=products_json,
        recipes_json=recipes_json,
    )
