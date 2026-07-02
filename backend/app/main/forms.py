from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired
from wtforms import SubmitField


class UploadForm(FlaskForm):
    file = FileField("Archivo", validators=[FileRequired()])
    submit = SubmitField("Subir archivo")
