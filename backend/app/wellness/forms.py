from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import SubmitField


class DailyEnergyImportForm(FlaskForm):
    file = FileField(
        "Energía diaria JSON",
        validators=[
            FileRequired(),
            FileAllowed(["json"], "Selecciona un archivo JSON."),
        ],
    )
    submit = SubmitField("Importar energía")
