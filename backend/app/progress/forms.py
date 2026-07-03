from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, Length


class ExerciseAliasForm(FlaskForm):
    alias_name = StringField(
        "Nombre alternativo",
        validators=[DataRequired(), Length(max=200)],
    )
    submit = SubmitField("Agregar alias")
