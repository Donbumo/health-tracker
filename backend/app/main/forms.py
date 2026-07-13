from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import (
    DateTimeLocalField,
    DecimalField,
    HiddenField,
    SelectField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional, ValidationError


def finite_decimal(_form, field) -> None:
    if field.data is not None and not field.data.is_finite():
        raise ValidationError("Ingresa un número finito.")


class UploadForm(FlaskForm):
    file = FileField("Archivo", validators=[FileRequired()])
    submit = SubmitField("Subir archivo")


class UserDataPreviewForm(FlaskForm):
    file = FileField(
        "Export JSON",
        validators=[
            FileRequired(),
            FileAllowed(["json"], "Selecciona un archivo con extensión .json."),
        ],
    )
    submit = SubmitField("Validar sin importar")


class AccountRestorePreviewForm(FlaskForm):
    file = FileField(
        "Export JSON",
        validators=[
            FileRequired(),
            FileAllowed(["json"], "Selecciona un archivo con extensiÃ³n .json."),
        ],
    )
    submit = SubmitField("Previsualizar restore")


class AccountRestoreConfirmForm(FlaskForm):
    file = FileField(
        "Repite el mismo export JSON para confirmar",
        validators=[
            FileRequired(),
            FileAllowed(["json"], "Selecciona un archivo con extensión .json."),
        ],
    )
    confirmation_token = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Confirmar restore")


class AccountBackupCreateForm(FlaskForm):
    submit = SubmitField("Generar backup ZIP")


class AccountBackupRestorePreviewForm(FlaskForm):
    file = FileField(
        "Backup ZIP",
        validators=[
            FileRequired(),
            FileAllowed(["zip"], "Selecciona un backup con extensión .zip."),
        ],
    )
    submit = SubmitField("Validar y previsualizar")


class AccountBackupRestoreConfirmForm(FlaskForm):
    staging_id = HiddenField(validators=[DataRequired()])
    confirmation_token = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Confirmar restore completo")


class StandardImportPreviewForm(FlaskForm):
    file = FileField(
        "JSON",
        validators=[
            FileRequired(),
            FileAllowed(["json"], "Selecciona un archivo con extensiÃ³n .json."),
        ],
    )
    target_type = SelectField(
        "Target",
        choices=[
            ("", "Detectar automÃ¡ticamente"),
            ("weigh_in_batch", "Pesajes"),
            ('daily_energy', 'Energía diaria'),
            ("daily_nutrition", "NutriciÃ³n diaria"),
            ("food_products", "Alimentos/productos"),
            ("recipe", "Receta"),
            ("recipe_bundle", "Bundle de recetas"),
            ("training_plan", "Rutina"),
            ("completed_workout", "SesiÃ³n completada"),
            ("medical_lab", "Laboratorio mÃ©dico"),
        ],
        validators=[Optional()],
    )
    submit = SubmitField("Analizar sin guardar")


class StandardImportConfirmForm(FlaskForm):
    payload_json = HiddenField(validators=[DataRequired()])
    target_type = HiddenField(validators=[DataRequired()])
    confirmation_token = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Confirmar e importar")


class RealFileImportPreviewForm(FlaskForm):
    file = FileField(
        "Archivo FIT, GPX, TCX, CSV o JSON",
        validators=[
            FileRequired(),
            FileAllowed(
                ["fit", "gpx", "tcx", "csv", "tsv", "txt", "json"],
                "Selecciona un archivo .fit, .gpx, .tcx, .csv, .tsv, .txt o .json.",
            ),
        ],
    )
    requested_type = SelectField(
        "Perfil CSV",
        choices=[
            ("", "Detectar automÃ¡ticamente"),
            ("weigh_in_csv", "CSV de pesajes"),
            ("daily_energy_csv", "CSV de energÃ­a diaria"),
        ],
        validators=[Optional()],
    )
    submit = SubmitField("Analizar archivo")


class RealFileImportConfirmForm(FlaskForm):
    source_file_id = HiddenField(validators=[DataRequired()])
    requested_type = HiddenField()
    target_type = HiddenField(validators=[DataRequired()])
    confirmation_token = HiddenField(validators=[DataRequired()])
    submit = SubmitField("Confirmar e importar archivo")


class WeighInForm(FlaskForm):
    recorded_at = DateTimeLocalField(
        "Fecha y hora",
        format="%Y-%m-%dT%H:%M",
        validators=[DataRequired()],
    )
    weight_kg = DecimalField(
        "Peso (kg)",
        validators=[DataRequired(), finite_decimal, NumberRange(min=0.01, max=1000)],
        render_kw={"min": "0.01", "max": "1000", "step": "0.01"},
    )
    body_fat_percent = DecimalField(
        "Grasa corporal (%)",
        validators=[Optional(), finite_decimal, NumberRange(min=0, max=100)],
        render_kw={"min": "0", "max": "100", "step": "0.1"},
    )
    muscle_mass_kg = DecimalField(
        "Masa muscular (kg)",
        validators=[Optional(), finite_decimal, NumberRange(min=0, max=1000)],
        render_kw={"min": "0", "max": "1000", "step": "0.01"},
    )
    water_percent = DecimalField(
        "Agua corporal (%)",
        validators=[Optional(), finite_decimal, NumberRange(min=0, max=100)],
        render_kw={"min": "0", "max": "100", "step": "0.1"},
    )
    visceral_fat = DecimalField(
        "Grasa visceral",
        validators=[Optional(), finite_decimal, NumberRange(min=0, max=1000)],
        render_kw={"min": "0", "max": "1000", "step": "0.1"},
    )
    bmr_kcal = DecimalField(
        "Metabolismo basal (kcal)",
        validators=[Optional(), finite_decimal, NumberRange(min=0, max=100000)],
        render_kw={"min": "0", "max": "100000", "step": "1"},
    )
    bmi = DecimalField(
        "BMI / IMC",
        validators=[Optional(), finite_decimal, NumberRange(min=0, max=1000)],
        render_kw={"min": "0", "max": "1000", "step": "0.01"},
    )
    notes = TextAreaField("Notas", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Guardar pesaje")
