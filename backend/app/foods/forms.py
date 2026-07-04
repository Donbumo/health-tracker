from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileRequired
from wtforms import BooleanField, DecimalField, FileField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange, Optional

from app.wellness.forms import finite_decimal


class FoodProductForm(FlaskForm):
    name = StringField("Nombre", validators=[DataRequired(), Length(max=200)])
    brand = StringField("Marca", validators=[Optional(), Length(max=200)])
    serving_size_g = DecimalField(
        "Tamaño de porción (g)", 
        validators=[Optional(), finite_decimal, NumberRange(min=0)]
    )
    serving_label = StringField("Etiqueta de porción (ej. 1 taza)", validators=[Optional(), Length(max=64)])
    
    calories_per_100g = DecimalField(
        "Calorías (kcal / 100g)", 
        validators=[Optional(), finite_decimal, NumberRange(min=0)]
    )
    protein_g_per_100g = DecimalField(
        "Proteína (g / 100g)", 
        validators=[Optional(), finite_decimal, NumberRange(min=0)]
    )
    fat_g_per_100g = DecimalField(
        "Grasa (g / 100g)", 
        validators=[Optional(), finite_decimal, NumberRange(min=0)]
    )
    carbs_g_per_100g = DecimalField(
        "Carbohidratos totales (g / 100g)", 
        validators=[Optional(), finite_decimal, NumberRange(min=0)]
    )
    net_carbs_g_per_100g = DecimalField(
        "Carbohidratos netos (g / 100g)", 
        validators=[Optional(), finite_decimal, NumberRange(min=0)]
    )
    fiber_g_per_100g = DecimalField(
        "Fibra (g / 100g)", 
        validators=[Optional(), finite_decimal, NumberRange(min=0)]
    )
    sodium_mg_per_100g = DecimalField(
        "Sodio (mg / 100g)", 
        validators=[Optional(), finite_decimal, NumberRange(min=0)]
    )
    
    notes = TextAreaField("Notas", validators=[Optional()])
    is_active = BooleanField("Activo", default=True)


class FoodProductImportForm(FlaskForm):
    file = FileField(
        "Archivo JSON",
        validators=[
            FileRequired(message="Seleccione un archivo JSON."),
            FileAllowed(["json"], message="Solo se permiten archivos JSON."),
        ],
    )
