from datetime import date, datetime
from io import BytesIO
from zoneinfo import ZoneInfo

from flask import abort, current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import DailyEnergy, DailyNutrition
from app.services.files import UploadError, mark_import_status, store_uploaded_file
from app.services.daily_balance import daily_balance
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
    return record


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
    records = db.session.execute(
        db.select(DailyEnergy)
        .where(DailyEnergy.user_id == current_user.id)
        .order_by(DailyEnergy.date.desc())
    ).scalars()
    return render_template("wellness/energy_list.html", records=records)


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
    from app.models import FoodProduct
    form = DailyNutritionManualForm()
    # Populate products choice
    products = db.session.execute(
        db.select(FoodProduct)
        .where(FoodProduct.user_id == current_user.id, FoodProduct.is_active.is_(True))
        .order_by(FoodProduct.name.asc())
    ).scalars().all()
    form.food_product_id.choices = [(0, "— Ninguno —")] + [(p.id, p.name) for p in products]

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
    return render_template("wellness/manual_nutrition.html", form=form, products_json=products_json)
