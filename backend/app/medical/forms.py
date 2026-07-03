from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import (
    DateField,
    DecimalField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, Optional, ValidationError


def finite_decimal(_form, field) -> None:
    if field.data is not None and not field.data.is_finite():
        raise ValidationError("Ingresa un número finito.")


class MedicalLabImportForm(FlaskForm):
    file = FileField(
        "Reporte médico JSON",
        validators=[
            FileRequired(),
            FileAllowed(["json"], "Selecciona un archivo JSON."),
        ],
    )
    submit = SubmitField("Importar reporte")


class MedicalLabManualForm(FlaskForm):
    date = DateField("Fecha", validators=[DataRequired()])
    laboratory_name = StringField(
        "Laboratorio",
        validators=[Optional(), Length(max=200)],
    )
    doctor_name = StringField(
        "Profesional / médico",
        validators=[Optional(), Length(max=200)],
    )
    marker_name = StringField(
        "Marcador",
        validators=[DataRequired(), Length(max=200)],
    )
    marker_code = StringField(
        "Código",
        validators=[Optional(), Length(max=100)],
    )
    value = StringField(
        "Valor",
        validators=[DataRequired(), Length(max=500)],
    )
    unit = StringField(
        "Unidad",
        validators=[DataRequired(), Length(max=100)],
    )
    reference_min = DecimalField(
        "Referencia mínima",
        validators=[Optional(), finite_decimal],
    )
    reference_max = DecimalField(
        "Referencia máxima",
        validators=[Optional(), finite_decimal],
    )
    reference_text = StringField(
        "Referencia textual",
        validators=[Optional(), Length(max=500)],
    )
    status = SelectField(
        "Estado",
        choices=(
            ("unknown", "Desconocido"),
            ("low", "Bajo"),
            ("normal", "Normal"),
            ("high", "Alto"),
        ),
        validators=[DataRequired()],
    )
    notes = TextAreaField("Notas del reporte", validators=[Optional(), Length(max=5000)])
    marker_notes = TextAreaField(
        "Notas del marcador",
        validators=[Optional(), Length(max=2000)],
    )
    submit = SubmitField("Guardar reporte")

    def validate(self, extra_validators=None):
        valid = super().validate(extra_validators=extra_validators)
        if (
            self.reference_min.data is not None
            and self.reference_max.data is not None
            and self.reference_min.data > self.reference_max.data
        ):
            self.reference_max.errors.append(
                "La referencia máxima debe ser mayor o igual a la mínima."
            )
            return False
        return valid
