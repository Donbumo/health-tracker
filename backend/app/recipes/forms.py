from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileRequired
from wtforms import DecimalField, FileField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange, Optional


class RecipeForm(FlaskForm):
    name = StringField(
        "Nombre",
        validators=[DataRequired(), Length(max=200)],
    )
    description = TextAreaField(
        "Descripción",
        validators=[Optional()],
    )
    servings = DecimalField(
        "Porciones",
        places=3,
        validators=[DataRequired(), NumberRange(min=0.001)],
        default=1,
    )
    yield_weight_g = DecimalField(
        "Rendimiento final en gramos",
        places=3,
        validators=[Optional(), NumberRange(min=0.001)],
    )
    notes = TextAreaField(
        "Notas",
        validators=[Optional()],
    )


class RecipeImportForm(FlaskForm):
    file = FileField(
        "Archivo JSON",
        validators=[
            FileRequired(message="Seleccione un archivo JSON."),
            FileAllowed(["json"], message="Solo se permiten archivos JSON."),
        ],
    )


class RecipeDuplicateForm(FlaskForm):
    pass