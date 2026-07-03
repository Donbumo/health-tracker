from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import SubmitField


class WeighInImportForm(FlaskForm):
    file = FileField(
        "Pesaje JSON",
        validators=[
            FileRequired(),
            FileAllowed(["json"], "Selecciona un archivo JSON."),
        ],
    )
    submit = SubmitField("Importar pesaje")
