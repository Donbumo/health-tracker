"""Bounded, deterministic adapters. Parsers never write domain or execute files."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import unicodedata
import zipfile
from dataclasses import asdict, dataclass, field
from typing import Protocol, TypedDict
from xml.etree import ElementTree as ET

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 1000
MAX_COLUMNS = 24
MAX_DAYS = 28
MAX_EXERCISES = 100
MAX_SETS = 30


class RoutineParseError(ValueError):
    pass


class ProgramDraft(TypedDict, total=False):
    name: str
    description: str


class ExerciseDraft(TypedDict, total=False):
    raw_name: str
    resolved_exercise_id: str
    create_new: bool
    name: str
    notes: str
    sets: list[dict]  # Canonical training_plan.$defs.set prescriptions.


class ProgramDayDraft(TypedDict, total=False):
    name: str
    order: int
    notes: str
    exercises: list[ExerciseDraft]


@dataclass
class RoutineImportDraft:
    program: ProgramDraft
    days: list[ProgramDayDraft]
    warnings: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    source_sha256: str | None = None
    source_ref: str | None = None
    source_filename: str | None = None

    def to_dict(self):
        return asdict(self)


class RoutineParser(Protocol):
    def parse(self, content: bytes, filename: str, name: str) -> RoutineImportDraft: ...


def normalized(value):
    text = unicodedata.normalize("NFKD", str(value).strip().casefold())
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).replace("_", " ").split())


ALIASES = {
    "day": ("day", "dia", "day name"),
    "exercise": ("exercise", "ejercicio", "name", "exercise name"),
    "sets": ("sets", "series"), "reps": ("reps", "repeticiones"),
    "reps_min": ("min reps", "reps min", "rep min"),
    "reps_max": ("max reps", "reps max", "rep max"),
    "load": ("weight", "load", "peso", "carga", "load value"),
    "unit": ("unit", "unidad", "load unit"),
    "rir": ("rir",), "rpe": ("rpe",),
    "rest_seconds": ("rest", "descanso", "rest seconds"),
    "notes": ("notes", "notas"),
}
HEADERS = {alias: key for key, values in ALIASES.items() for alias in values}


def _xml(content):
    if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
        raise RoutineParseError("XML con entidades no permitido.")
    return ET.fromstring(content)


def _xlsx(content):
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            names = [item.filename for item in entries]
            if len(entries) > 100 or len(names) != len(set(names)) or sum(item.file_size for item in entries) > 10 * MAX_BYTES:
                raise RoutineParseError("Workbook demasiado grande.")
            if any("vba" in name.casefold() or "externallinks" in name.casefold() for name in names):
                raise RoutineParseError("Macros y vínculos externos no permitidos.")
            if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
                raise RoutineParseError("Se requiere un archivo XLSX.")
            types = archive.read("[Content_Types].xml")
            if b"macroEnabled" in types:
                raise RoutineParseError("Macros no permitidas.")
            sheets = sorted(name for name in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name))
            if len(sheets) != 1:
                raise RoutineParseError("Usa una hoja con columna Día; no se omiten hojas silenciosamente.")
            strings = []
            if "xl/sharedStrings.xml" in names:
                strings = ["".join(item.itertext()) for item in _xml(archive.read("xl/sharedStrings.xml")).findall("s:si", ns)]
            rows = []
            for row in _xml(archive.read(sheets[0])).findall("s:sheetData/s:row", ns):
                values = []
                for cell in row.findall("s:c", ns):
                    if cell.find("s:f", ns) is not None:
                        raise RoutineParseError("Fórmulas no permitidas; exporta valores.")
                    address = re.fullmatch(r"([A-Z]+)[1-9][0-9]*", cell.get("r", ""))
                    if address is None:
                        raise RoutineParseError("Celda XLSX inválida.")
                    column = 0
                    for letter in address[1]:
                        column = column * 26 + ord(letter) - 64
                    if column > MAX_COLUMNS:
                        raise RoutineParseError("Demasiadas columnas.")
                    while len(values) < column:
                        values.append("")
                    value = cell.findtext("s:v", default="", namespaces=ns)
                    if cell.get("t") == "s":
                        value = strings[int(value)]
                    elif cell.get("t") == "inlineStr":
                        inline = cell.find("s:is", ns)
                        value = "".join(inline.itertext()) if inline is not None else ""
                    values[column - 1] = value
                rows.append(values)
                if len(rows) > MAX_ROWS + 1:
                    raise RoutineParseError("Demasiadas filas.")
            return rows
    except (zipfile.BadZipFile, ET.ParseError, KeyError, IndexError, TypeError, ValueError) as error:
        if isinstance(error, RoutineParseError):
            raise
        raise RoutineParseError("Workbook XLSX inválido.") from error


def _number(value, label, integer=False):
    text = str(value).strip().replace(",", ".")
    if not re.fullmatch(r"\d+(?:\.\d+)?", text) or len(text) > 12:
        raise RoutineParseError(f"{label}: número inválido.")
    if integer:
        if not float(text).is_integer():
            raise RoutineParseError(f"{label}: usa un entero.")
        return int(float(text))
    return text


class DeterministicParser:
    def parse(self, content: bytes, filename: str, name: str) -> RoutineImportDraft:
        if not content or len(content) > MAX_BYTES:
            raise RoutineParseError("Archivo vacío o mayor a 2 MB.")
        extension = filename.rsplit(".", 1)[-1].lower()
        if extension not in {"csv", "xlsx", "json", "txt"}:
            raise RoutineParseError("Soporte: CSV, XLSX, JSON y texto tabular. PDF/fotos requieren un parser futuro.")
        warnings = []
        try:
            if extension == "xlsx":
                table = _xlsx(content)
            else:
                text = content.decode("utf-8-sig")
                if extension == "json":
                    raw = json.loads(text)
                    if isinstance(raw, dict) and "days" in raw:
                        draft = RoutineImportDraft(program={"name": name or raw.get("program", {}).get("name", "")}, days=raw["days"])
                        validate_draft_shape(draft)
                        draft.source_sha256 = hashlib.sha256(content).hexdigest()
                        return draft
                    if isinstance(raw, dict) and raw.get("record_type") == "training_plan":
                        draft = draft_from_document(raw, name=name, digest=hashlib.sha256(content).hexdigest())
                        # Imported IDs are source-account references, not authority.
                        for day in draft.days:
                            for exercise in day["exercises"]:
                                exercise.pop("resolved_exercise_id", None)
                        return draft
                    if not isinstance(raw, list) or not raw or not all(isinstance(row, dict) for row in raw):
                        raise RoutineParseError("JSON debe contener filas o un RoutineImportDraft.")
                    headers = list(dict.fromkeys(key for row in raw for key in row))
                    table = [headers] + [[row.get(key, "") for key in headers] for row in raw]
                else:
                    first = text.splitlines()[0]
                    delimiter = max((",", ";", "\t", "|"), key=first.count)
                    table = list(csv.reader(io.StringIO(text), delimiter=delimiter))
        except (UnicodeError, json.JSONDecodeError, RecursionError, IndexError) as error:
            raise RoutineParseError("Contenido inválido; usa UTF-8 y texto tabular con encabezados.") from error
        if not table or len(table) > MAX_ROWS + 1 or any(len(row) > MAX_COLUMNS for row in table):
            raise RoutineParseError("Límite: 1000 filas y 24 columnas.")
        headers = [HEADERS.get(normalized(item)) for item in table[0]]
        recognized = [item for item in headers if item]
        if len(recognized) != len(set(recognized)):
            raise RoutineParseError("Columnas equivalentes duplicadas.")
        if not {"day", "exercise"}.issubset(headers):
            raise RoutineParseError("Incluye las columnas Día y Ejercicio.")
        if None in headers:
            warnings.append(f"{headers.count(None)} columnas no reconocidas se ignoraron.")
        days = {}
        for index, cells in enumerate(table[1:], 2):
            if not any(str(cell).strip() for cell in cells):
                warnings.append(f"Fila {index} vacía ignorada.")
                continue
            row = {key: cells[pos] for pos, key in enumerate(headers) if key and pos < len(cells) and cells[pos] not in (None, "")}
            if not row.get("day") or not row.get("exercise"):
                raise RoutineParseError(f"Fila {index}: Día y Ejercicio son obligatorios.")
            day_name = str(row["day"]).strip()
            day = days.setdefault(day_name, {"name": day_name, "order": len(days) + 1, "exercises": []})
            prescription = {}
            count = row.get("sets")
            reps = str(row.get("reps", "")).strip()
            combined = re.fullmatch(r"(\d+)\s*[x×]\s*(.+)", reps, re.I)
            if combined:
                if count is not None and str(count) != combined[1]:
                    raise RoutineParseError(f"Fila {index}: series contradictorias.")
                count, reps = combined.groups()
            if count is None:
                raise RoutineParseError(f"Fila {index}: falta Series (o 3x8 en Reps).")
            count = _number(count, "Series", True)
            if not 1 <= count <= MAX_SETS:
                raise RoutineParseError("Series fuera de rango (1–30).")
            if reps:
                pair = re.fullmatch(r"(\d+)\s*[-–]\s*(\d+)", reps)
                if pair:
                    prescription.update(reps_min=int(pair[1]), reps_max=int(pair[2]))
                else:
                    prescription["reps"] = _number(reps, "Reps", True)
            for key in ("reps_min", "reps_max", "rest_seconds"):
                if key in row:
                    prescription[key] = _number(row[key], key, True)
            for key in ("rir", "rpe"):
                if key in row:
                    prescription[key] = _number(re.sub(rf"^{key}\s*", "", str(row[key]), flags=re.I), key)
            if "load" in row:
                load = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*(kg|lb)?\s*", str(row["load"]), re.I)
                if not load:
                    raise RoutineParseError(f"Fila {index}: carga inválida.")
                unit = str(row.get("unit", load[2] or "")).lower()
                if unit not in {"kg", "lb"} or (load[2] and unit != load[2].lower()):
                    raise RoutineParseError(f"Fila {index}: indica unidad kg/lb sin ambigüedad.")
                prescription.update(load_value=_number(load[1], "Carga"), load_unit=unit)
            exercise = {"raw_name": str(row["exercise"]).strip(), "sets": [{"set_number": i + 1, **prescription} for i in range(count)]}
            if "notes" in row:
                exercise["notes"] = str(row["notes"])
            day["exercises"].append(exercise)
        draft = RoutineImportDraft({"name": name}, list(days.values()), warnings, source_sha256=hashlib.sha256(content).hexdigest())
        validate_draft_shape(draft)
        return draft


def validate_draft_shape(draft):
    if draft.source_sha256 is not None and (not isinstance(draft.source_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", draft.source_sha256)):
        raise RoutineParseError("Hash del original inválido.")
    if not isinstance(draft.warnings, list) or len(draft.warnings) > MAX_ROWS or any(not isinstance(item, str) or len(item) > 500 for item in draft.warnings):
        raise RoutineParseError("Warnings inválidos.")
    if not isinstance(draft.program, dict) or not isinstance(draft.program.get("name"), str) or not 1 <= len(draft.program["name"].strip()) <= 200:
        raise RoutineParseError("Indica el nombre del programa (1–200 caracteres).")
    if not isinstance(draft.days, list) or not 1 <= len(draft.days) <= MAX_DAYS:
        raise RoutineParseError("Se requieren entre 1 y 28 días.")
    for day in draft.days:
        if not isinstance(day, dict) or not isinstance(day.get("name"), str) or not 1 <= len(day["name"].strip()) <= 200:
            raise RoutineParseError("Nombre de día inválido.")
        exercises = day.get("exercises")
        if not isinstance(exercises, list) or len(exercises) > MAX_EXERCISES:
            raise RoutineParseError("Cada día admite hasta 100 ejercicios; un día de descanso puede estar vacío.")
        for exercise in exercises:
            if not isinstance(exercise, dict) or not isinstance(exercise.get("raw_name"), str) or not 1 <= len(exercise["raw_name"].strip()) <= 200:
                raise RoutineParseError("Nombre de ejercicio inválido.")
            if not isinstance(exercise.get("sets"), list) or not 1 <= len(exercise["sets"]) <= MAX_SETS:
                raise RoutineParseError("Cada ejercicio requiere entre 1 y 30 series.")


def draft_from_document(document, *, name="", digest=None):
    from app.services.validation import validate_json_document
    validate_json_document(document, "training_plan")
    days = [{"name": day["name"], "notes": day.get("notes"), "exercises": [
        {"raw_name": exercise["name"], "resolved_exercise_id": exercise.get("exercise_id"), "sets": exercise["sets"], "notes": exercise.get("notes")}
        for exercise in day["exercises"]]} for week in document["data"]["weeks"] for day in week["days"]]
    draft = RoutineImportDraft({"name": name or document["data"]["name"], "description": document["data"].get("description")}, days, source_sha256=digest)
    validate_draft_shape(draft)
    return draft
