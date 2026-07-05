from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import (
    DateField,
    DecimalField,
    IntegerField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional, ValidationError


def finite_decimal(_form, field) -> None:
    if field.data is not None and not field.data.is_finite():
        raise ValidationError("Ingresa un número finito.")


class DailyEnergyImportForm(FlaskForm):
    file = FileField(
        "Energía diaria JSON",
        validators=[
            FileRequired(),
            FileAllowed(["json"], "Selecciona un archivo JSON."),
        ],
    )
    submit = SubmitField("Importar energía")


class DailyNutritionImportForm(FlaskForm):
    file = FileField(
        "Nutrición diaria JSON",
        validators=[
            FileRequired(),
            FileAllowed(["json"], "Selecciona un archivo JSON."),
        ],
    )
    submit = SubmitField("Importar nutrición")


class DailyEnergyManualForm(FlaskForm):
    date = DateField("Fecha", validators=[DataRequired()])
    total_calories = DecimalField(
        "Calorías totales",
        validators=[Optional(), finite_decimal, NumberRange(min=0, max=100000)],
    )
    active_calories = DecimalField(
        "Calorías activas",
        validators=[Optional(), finite_decimal, NumberRange(min=0, max=100000)],
    )
    resting_calories = DecimalField(
        "Calorías de reposo",
        validators=[Optional(), finite_decimal, NumberRange(min=0, max=100000)],
    )
    steps = IntegerField(
        "Pasos",
        validators=[Optional(), NumberRange(min=0, max=10000000)],
    )
    distance_meters = DecimalField(
        "Distancia (m)",
        validators=[Optional(), finite_decimal, NumberRange(min=0, max=100000000)],
    )
    notes = TextAreaField("Notas", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Guardar energía")

    def validate(self, extra_validators=None):
        valid = super().validate(extra_validators=extra_validators)
        metrics = (
            self.total_calories.data,
            self.active_calories.data,
            self.resting_calories.data,
            self.steps.data,
            self.distance_meters.data,
        )
        if all(value is None for value in metrics):
            self.total_calories.errors.append("Ingresa al menos una métrica.")
            return False
        return valid


class DailyNutritionManualForm(FlaskForm):
    date = DateField("Fecha", validators=[DataRequired()])
    meal_type = SelectField(
        "Tipo de comida",
        choices=(
            ("breakfast", "Desayuno"),
            ("lunch", "Comida"),
            ("dinner", "Cena"),
            ("snack", "Snack"),
            ("extra", "Extra"),
            ("other", "Otra"),
        ),
        validators=[DataRequired()],
    )
    meal_name = StringField("Nombre de comida", validators=[Optional(), Length(max=200)])
    item_name = StringField("Item", validators=[DataRequired(), Length(max=200)])
    food_product_id = SelectField("Producto de alacena (Opcional)", coerce=int, validators=[Optional()])
    grams_from_product = DecimalField(
        "Gramos del producto",
        validators=[Optional(), finite_decimal, NumberRange(min=0, max=1000000)],
    )
    recipe_id = SelectField("Receta (Opcional)", coerce=int, validators=[Optional()])
    recipe_amount = DecimalField(
        "Cantidad de receta",
        validators=[Optional(), finite_decimal, NumberRange(min=0, max=1000000)],
    )
    recipe_unit = SelectField(
        "Unidad de receta",
        choices=(
            ("serving", "Porción"),
            ("g", "Gramos"),
        ),
        validators=[Optional()],
    )
    quantity = DecimalField(
        "Cantidad",
        validators=[Optional(), finite_decimal, NumberRange(min=0, max=1000000)],
    )
    unit = StringField("Unidad", validators=[Optional(), Length(max=32)])
    calories = DecimalField("Calorías", validators=[Optional(), finite_decimal, NumberRange(min=0, max=1000000)])
    protein_g = DecimalField("Proteína (g)", validators=[Optional(), finite_decimal, NumberRange(min=0, max=1000000)])
    fat_g = DecimalField("Grasa (g)", validators=[Optional(), finite_decimal, NumberRange(min=0, max=1000000)])
    net_carbs_g = DecimalField("Net carbs (g)", validators=[Optional(), finite_decimal, NumberRange(min=0, max=1000000)])
    total_carbs_g = DecimalField("Carbs totales (g)", validators=[Optional(), finite_decimal, NumberRange(min=0, max=1000000)])
    fiber_g = DecimalField("Fibra (g)", validators=[Optional(), finite_decimal, NumberRange(min=0, max=1000000)])
    sugar_g = DecimalField("Azúcar (g)", validators=[Optional(), finite_decimal, NumberRange(min=0, max=1000000)])
    sodium_mg = DecimalField("Sodio (mg)", validators=[Optional(), finite_decimal, NumberRange(min=0, max=1000000)])
    notes = TextAreaField("Notas del día", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Guardar nutrición")
