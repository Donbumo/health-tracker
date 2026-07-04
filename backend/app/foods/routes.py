from decimal import Decimal

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.foods import foods_bp
from app.foods.forms import FoodProductForm, FoodProductImportForm
from app.models import FoodProduct
from app.services.importers.food_product import (
    FoodProductImportError,
    import_food_product_file,
)
from app.services.files import store_uploaded_file
from app.services.validation import JsonSchemaValidationError


def _decimal(value) -> Decimal | None:
    return Decimal(str(value)) if value else None


@foods_bp.route("")
@login_required
def list_foods():
    records = db.session.execute(
        db.select(FoodProduct)
        .where(FoodProduct.user_id == current_user.id)
        .order_by(FoodProduct.name.asc())
    ).scalars().all()
    return render_template("foods/list.html", records=records)


@foods_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_food():
    form = FoodProductForm()
    if form.validate_on_submit():
        product = FoodProduct(
            user_id=current_user.id,
            name=form.name.data.strip(),
            brand=form.brand.data.strip() if form.brand.data else None,
            serving_size_g=_decimal(form.serving_size_g.data),
            serving_label=form.serving_label.data.strip() if form.serving_label.data else None,
            calories_per_100g=_decimal(form.calories_per_100g.data),
            protein_g_per_100g=_decimal(form.protein_g_per_100g.data),
            fat_g_per_100g=_decimal(form.fat_g_per_100g.data),
            carbs_g_per_100g=_decimal(form.carbs_g_per_100g.data),
            net_carbs_g_per_100g=_decimal(form.net_carbs_g_per_100g.data),
            fiber_g_per_100g=_decimal(form.fiber_g_per_100g.data),
            sodium_mg_per_100g=_decimal(form.sodium_mg_per_100g.data),
            source="manual",
            notes=form.notes.data.strip() if form.notes.data else None,
            is_active=form.is_active.data,
        )
        try:
            db.session.add(product)
            db.session.commit()
            flash("Producto guardado correctamente.", "success")
            return redirect(url_for("foods.detail_food", id=product.id))
        except IntegrityError:
            db.session.rollback()
            flash("Ya existe un producto con ese nombre y marca.", "error")

    return render_template("foods/new.html", form=form)


@foods_bp.route("/<int:id>")
@login_required
def detail_food(id: int):
    product = db.session.get(FoodProduct, id)
    if product is None or product.user_id != current_user.id:
        abort(404)
    return render_template("foods/detail.html", product=product)


@foods_bp.route("/<int:id>/edit", methods=["GET", "POST"])
@login_required
def edit_food(id: int):
    product = db.session.get(FoodProduct, id)
    if product is None or product.user_id != current_user.id:
        abort(404)

    form = FoodProductForm(obj=product)

    if form.validate_on_submit():
        product.name = form.name.data.strip()
        product.brand = form.brand.data.strip() if form.brand.data else None
        product.serving_size_g = _decimal(form.serving_size_g.data)
        product.serving_label = form.serving_label.data.strip() if form.serving_label.data else None
        product.calories_per_100g = _decimal(form.calories_per_100g.data)
        product.protein_g_per_100g = _decimal(form.protein_g_per_100g.data)
        product.fat_g_per_100g = _decimal(form.fat_g_per_100g.data)
        product.carbs_g_per_100g = _decimal(form.carbs_g_per_100g.data)
        product.net_carbs_g_per_100g = _decimal(form.net_carbs_g_per_100g.data)
        product.fiber_g_per_100g = _decimal(form.fiber_g_per_100g.data)
        product.sodium_mg_per_100g = _decimal(form.sodium_mg_per_100g.data)
        product.notes = form.notes.data.strip() if form.notes.data else None
        product.is_active = form.is_active.data
        
        try:
            db.session.commit()
            flash("Producto actualizado correctamente.", "success")
            return redirect(url_for("foods.detail_food", id=product.id))
        except IntegrityError:
            db.session.rollback()
            flash("Ya existe un producto con ese nombre y marca.", "error")

    return render_template("foods/edit.html", form=form, product=product)


@foods_bp.route("/import", methods=["GET", "POST"])
@login_required
def import_food():
    form = FoodProductImportForm()
    if form.validate_on_submit():
        source_file = None
        try:
            source_file, file_duplicate = store_uploaded_file(
                form.file.data,
                current_user.id,
            )
            product, duplicate = import_food_product_file(source_file, current_user.id)
            if duplicate:
                source_file.import_status = "duplicate"
                db.session.commit()
                flash("El producto ya existe.", "info")
            else:
                source_file.import_status = "imported"
                db.session.commit()
                flash("Producto importado correctamente.", "success")
            return redirect(url_for("foods.detail_food", id=product.id))
        except (FoodProductImportError, JsonSchemaValidationError) as error:
            source_file.import_status = "error"
            source_file.error_message = str(error)
            db.session.commit()
            flash(f"Error al importar: {error}", "error")

    return render_template("foods/import.html", form=form)
