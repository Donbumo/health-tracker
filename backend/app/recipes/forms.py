from flask_wtf import FlaskForm
from wtforms import DecimalField, StringField, TextAreaField
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