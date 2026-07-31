from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import unicodedata
from typing import Any, BinaryIO
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile, ZipInfo

from jsonschema import Draft202012Validator, FormatChecker


FORMAT = "health-tracker-portable-v1"
FORMAT_VERSION = "1.0"
MEDIA_TYPE = "application/vnd.health-tracker.portable+zip"
HEALTH_WARNING = "Este archivo contiene datos personales de salud. Guárdalo en un lugar seguro."
AUTHENTICITY_WARNING = "Los checksums demuestran integridad, no autenticidad; el paquete no está firmado."

SECTION_PATHS = {
    "profile": "records/profile.json",
    "settings": "records/settings.json",
    "goals": "records/goals.jsonl",
    "reminder_rules": "records/reminder_rules.jsonl",
    "medical_studies": "records/medical_studies.jsonl",
    "lab_panels": "records/lab_panels.jsonl",
    "lab_results": "records/lab_results.jsonl",
    "medical_documents_metadata": "records/medical_documents_metadata.jsonl",
    "exercises": "records/exercises.jsonl",
    "plans": "records/plans.jsonl",
    "workouts": "records/workouts.jsonl",
    "schedules": "records/schedules.jsonl",
    "sessions": "records/sessions.jsonl",
    "session_exercises": "records/session_exercises.jsonl",
    "sets": "records/sets.jsonl",
    "body_stats": "records/body_stats.jsonl",
    "nutrition_entries": "records/nutrition_entries.jsonl",
    "custom_foods": "records/custom_foods.jsonl",
    "steps": "records/steps.jsonl",
    "external_sources": "records/external_sources.jsonl",
    "attachments": "records/attachments.jsonl",
}
ALL_SECTIONS = tuple(SECTION_PATHS)
CORE_SCHEMA_NAMES = (
    "portable_manifest.schema.json",
    "portable_checksums.schema.json",
    "portable_inspection.schema.json",
    "portable_import_plan.schema.json",
    "portable_import_result.schema.json",
)
FORBIDDEN_KEYS = {
    "id", "user_id", "password", "password_hash", "token", "access_token",
    "refresh_token", "session", "csrf_token", "secret", "storage_path",
    "relative_path", "server_url", "host", "ip_address", "mac", "mac_address",
    "gatt", "gatt_snapshot", "changes_token", "manufacturer_data",
    "authorization", "cookie", "signing_key", "device_authentication_secret",
}


@dataclass(frozen=True)
class PortableLimits:
    max_compressed_bytes: int = 50 * 1024 * 1024
    max_uncompressed_bytes: int = 200 * 1024 * 1024
    max_files: int = 256
    max_file_bytes: int = 50 * 1024 * 1024
    max_records_per_section: int = 50_000
    max_json_depth: int = 20
    max_string_length: int = 100_000
    max_json_line_bytes: int = 2 * 1024 * 1024
    max_attachments_bytes: int = 100 * 1024 * 1024
    max_compression_ratio: int = 100


@dataclass(frozen=True)
class PortableInspection:
    manifest: dict[str, Any]
    records: dict[str, list[dict[str, Any]]]
    package_sha256: str
    files: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]

    def report(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "format": FORMAT,
            "format_version": FORMAT_VERSION,
            "export_id": self.manifest["export_id"],
            "package_sha256": self.package_sha256,
            "integrity": "verified",
            "authenticity": "not_proven",
            "sections": self.manifest["included_sections"],
            "counts": self.manifest["counts"],
            "files": list(self.files),
            "warnings": list(self.warnings),
        }


class PortableArchiveError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_path(path: Path, *, maximum: int | None = None) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            if maximum is not None and size > maximum:
                raise PortableArchiveError("package_too_large", "El paquete supera el límite permitido.")
            digest.update(chunk)
    return digest.hexdigest(), size


def safe_filename(value: str, fallback: str = "attachment.bin") -> str:
    name = PurePosixPath(str(value).replace("\\", "/")).name
    name = unicodedata.normalize("NFKC", name)
    cleaned = "".join(char if char.isascii() and (char.isalnum() or char in "._-") else "_" for char in name)
    cleaned = cleaned.strip("._")[:120]
    return cleaned or fallback


def scrub_portable(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): scrub_portable(item)
            for key, item in value.items()
            if str(key).casefold() not in FORBIDDEN_KEYS
        }
    if isinstance(value, list):
        return [scrub_portable(item) for item in value]
    if isinstance(value, tuple):
        return [scrub_portable(item) for item in value]
    if hasattr(value, "as_tuple"):
        text = format(value, "f")
        return text.rstrip("0").rstrip(".") if "." in text else text
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


class PortableArchiveWriter:
    def __init__(self, schema_root: Path):
        self.schema_root = Path(schema_root)

    def write(
        self,
        destination: Path,
        *,
        export_id: str,
        created_at: datetime,
        application_version: str,
        timezone_name: str | None,
        records: dict[str, list[dict[str, Any]]],
        omitted_sections: list[str],
        identifiable_profile: bool,
        attachment_files: dict[str, Path] | None = None,
    ) -> dict[str, Any]:
        attachment_files = attachment_files or {}
        included = [section for section in ALL_SECTIONS if section in records]
        unknown = set(records) - set(ALL_SECTIONS)
        if unknown:
            raise PortableArchiveError("unknown_section", "El export contiene una sección desconocida.")

        members: dict[str, bytes | Path] = {}
        for section in included:
            section_records = records[section]
            path = SECTION_PATHS[section]
            if section in {"profile", "settings"}:
                if len(section_records) > 1:
                    raise PortableArchiveError("invalid_section", "La sección singular contiene más de un registro.")
                members[path] = canonical_json_bytes(section_records[0]) if section_records else b"null\n"
            else:
                members[path] = b"".join(canonical_json_bytes(record) for record in section_records)

        schema_names = list(CORE_SCHEMA_NAMES) + [f"portable_{section}.schema.json" for section in included]
        for name in schema_names:
            path = self.schema_root / name
            if not path.is_file():
                raise PortableArchiveError("schema_missing", f"Falta el schema público {name}.")
            members[f"schemas/{name}"] = path

        for archive_name, source_path in attachment_files.items():
            self._validate_output_name(archive_name)
            if not archive_name.startswith("attachments/"):
                raise PortableArchiveError("invalid_attachment", "La ruta de attachment no es válida.")
            members[archive_name] = source_path

        file_rows = []
        attachment_total = 0
        for path in sorted(members):
            source = members[path]
            if isinstance(source, bytes):
                digest, size = sha256_bytes(source), len(source)
            else:
                digest, size = sha256_path(source)
            if path.startswith("attachments/"):
                attachment_total += size
            file_rows.append({"path": path, "size_bytes": size, "sha256": digest})

        manifest = {
            "format": FORMAT,
            "format_version": FORMAT_VERSION,
            "export_id": export_id,
            "created_at": scrub_portable(created_at),
            "source_application": "Health Tracker",
            "source_application_version": str(application_version or "unknown")[:80],
            "schema_versions": {section: "1.0" for section in included},
            "timezone": timezone_name,
            "included_sections": included,
            "omitted_sections": sorted(set(omitted_sections)),
            "counts": {section: len(records[section]) for section in included},
            "files": file_rows,
            "attachment_policy": {"included": bool(attachment_files), "opt_in": True, "total_bytes": attachment_total},
            "redaction_policy": {
                "identifiable_profile": identifiable_profile,
                "notes": "included_in_selected_domains",
                "technical_identifiers": "excluded",
                "external_provenance": "sanitized",
            },
            "warnings": [HEALTH_WARNING, AUTHENTICITY_WARNING],
            "minimum_reader_version": "1.0",
        }
        self._validate_schema(manifest, "portable_manifest.schema.json")
        manifest_bytes = canonical_json_bytes(manifest)
        checksums = {
            "format_version": "1.0",
            "algorithm": "sha256",
            "files": {"manifest.json": sha256_bytes(manifest_bytes), **{row["path"]: row["sha256"] for row in file_rows}},
        }
        self._validate_schema(checksums, "portable_checksums.schema.json")
        checksum_bytes = canonical_json_bytes(checksums)

        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.partial")
        try:
            with ZipFile(temporary, "w", compression=ZIP_DEFLATED, compresslevel=6, strict_timestamps=True) as archive:
                self._write_bytes(archive, "manifest.json", manifest_bytes)
                self._write_bytes(archive, "checksums.json", checksum_bytes)
                for name in sorted(members):
                    source = members[name]
                    if isinstance(source, bytes):
                        self._write_bytes(archive, name, source)
                    else:
                        self._write_path(archive, name, source)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        return manifest

    @staticmethod
    def _write_bytes(archive: ZipFile, name: str, content: bytes) -> None:
        info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = ZIP_DEFLATED
        info.external_attr = (stat.S_IFREG | 0o600) << 16
        info.create_system = 3
        archive.writestr(info, content)

    @classmethod
    def _write_path(cls, archive: ZipFile, name: str, source: Path) -> None:
        if source.is_symlink() or not source.is_file():
            raise PortableArchiveError("invalid_attachment", "El attachment no es un archivo regular.")
        cls._write_bytes(archive, name, source.read_bytes())

    @staticmethod
    def _validate_output_name(name: str) -> None:
        if not name or not name.isascii() or "\\" in name or name.startswith(("/", "\\")) or ".." in PurePosixPath(name).parts:
            raise PortableArchiveError("unsafe_path", "El nombre de archivo del paquete no es seguro.")

    def _validate_schema(self, payload: dict[str, Any], name: str) -> None:
        schema = json.loads((self.schema_root / name).read_text(encoding="utf-8"))
        errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload))
        if errors:
            raise PortableArchiveError("schema_invalid", f"El documento {name} no cumple su schema.")


class PortableArchiveReader:
    def __init__(self, schema_root: Path, limits: PortableLimits | None = None):
        self.schema_root = Path(schema_root)
        self.limits = limits or PortableLimits()

    def inspect(self, source_path: Path) -> PortableInspection:
        source_path = Path(source_path)
        package_hash, compressed_size = sha256_path(source_path, maximum=self.limits.max_compressed_bytes)
        if compressed_size == 0:
            raise PortableArchiveError("invalid_archive", "El paquete está vacío.")
        try:
            with ZipFile(source_path, "r") as archive:
                infos = archive.infolist()
                info_by_name = self._validate_infos(infos)
                if "manifest.json" not in info_by_name:
                    raise PortableArchiveError("manifest_missing", "Falta manifest.json.")
                if "checksums.json" not in info_by_name:
                    raise PortableArchiveError("checksums_missing", "Falta checksums.json.")
                manifest_raw = self._read_limited(archive, info_by_name["manifest.json"], self.limits.max_json_line_bytes)
                checksums_raw = self._read_limited(archive, info_by_name["checksums.json"], self.limits.max_json_line_bytes)
                manifest = self._decode_json(manifest_raw, "manifest.json")
                checksums = self._decode_json(checksums_raw, "checksums.json")
                self._preflight_contract(manifest)
                self._validate_schema(manifest, "portable_manifest.schema.json")
                self._validate_schema(checksums, "portable_checksums.schema.json")
                if manifest.get("format") != FORMAT or manifest.get("format_version") != FORMAT_VERSION:
                    raise PortableArchiveError("unsupported_format", "El formato o versión del paquete no es compatible.")
                self._verify_file_contract(archive, info_by_name, manifest, checksums, manifest_raw)
                self._verify_schema_members(archive, info_by_name, manifest)
                records = self._read_records(archive, info_by_name, manifest)
        except BadZipFile as error:
            raise PortableArchiveError("invalid_archive", "El archivo no es un ZIP válido.") from error
        files = tuple({"path": row["path"], "size_bytes": row["size_bytes"]} for row in manifest["files"])
        return PortableInspection(
            manifest=manifest,
            records=records,
            package_sha256=package_hash,
            files=files,
            warnings=(HEALTH_WARNING, AUTHENTICITY_WARNING),
        )

    def read_member(self, source_path: Path, member_name: str) -> bytes:
        with ZipFile(source_path, "r") as archive:
            info_by_name = self._validate_infos(archive.infolist())
            info = info_by_name.get(member_name)
            if info is None:
                raise PortableArchiveError("attachment_missing", "Falta un attachment declarado.")
            return self._read_limited(archive, info, self.limits.max_file_bytes)

    def _preflight_contract(self, manifest: Any) -> None:
        if not isinstance(manifest, dict):
            raise PortableArchiveError("schema_validation_failed", "manifest.json debe ser un objeto.")
        if manifest.get("format") != FORMAT or manifest.get("format_version") != FORMAT_VERSION:
            raise PortableArchiveError("unsupported_format", "El formato o version del paquete no es compatible.")
        included = manifest.get("included_sections")
        if isinstance(included, list) and any(section not in ALL_SECTIONS for section in included):
            raise PortableArchiveError("unknown_section", "El manifest declara una seccion desconocida.")
        versions = manifest.get("schema_versions")
        if isinstance(versions, dict) and any(version != "1.0" for version in versions.values()):
            raise PortableArchiveError("unknown_schema", "El paquete declara una version de schema desconocida.")

    def _validate_infos(self, infos: list[ZipInfo]) -> dict[str, ZipInfo]:
        if not infos or len(infos) > self.limits.max_files:
            raise PortableArchiveError("too_many_files", "El paquete contiene demasiados archivos.")
        names: dict[str, ZipInfo] = {}
        folded: set[str] = set()
        total = 0
        attachment_total = 0
        for info in infos:
            name = info.filename
            self._validate_member_name(name)
            key = name.casefold()
            if name in names or key in folded:
                raise PortableArchiveError("duplicate_file", "El paquete contiene nombres duplicados o ambiguos.")
            names[name] = info
            folded.add(key)
            if info.is_dir() or name.endswith("/"):
                raise PortableArchiveError("special_file", "No se permiten directorios explícitos.")
            mode = info.external_attr >> 16
            kind = stat.S_IFMT(mode)
            if kind not in (0, stat.S_IFREG):
                raise PortableArchiveError("special_file", "No se permiten enlaces ni archivos especiales.")
            if info.flag_bits & 0x1:
                raise PortableArchiveError("encrypted_archive", "Los paquetes cifrados no están soportados.")
            if info.file_size > self.limits.max_file_bytes:
                raise PortableArchiveError("file_too_large", "Un archivo del paquete supera el límite.")
            if info.file_size > 1024 * 1024 and info.compress_size > 0 and info.file_size / info.compress_size > self.limits.max_compression_ratio:
                raise PortableArchiveError("compression_ratio", "La compresión del paquete es insegura.")
            total += info.file_size
            if name.startswith("attachments/"):
                attachment_total += info.file_size
        if total > self.limits.max_uncompressed_bytes:
            raise PortableArchiveError("archive_too_large", "El tamaño descomprimido supera el límite.")
        if attachment_total > self.limits.max_attachments_bytes:
            raise PortableArchiveError("attachments_too_large", "Los attachments superan el límite.")
        return names

    @staticmethod
    def _validate_member_name(name: str) -> None:
        if not name or "\x00" in name or "\\" in name or not name.isascii():
            raise PortableArchiveError("unsafe_path", "El paquete contiene una ruta insegura o ambigua.")
        if unicodedata.normalize("NFKC", name) != name:
            raise PortableArchiveError("unsafe_path", "El paquete contiene un nombre Unicode ambiguo.")
        path = PurePosixPath(name)
        if path.is_absolute() or name.startswith("/") or len(name) > 255 or any(part in {"", ".", ".."} for part in path.parts):
            raise PortableArchiveError("unsafe_path", "El paquete contiene una ruta absoluta o traversal.")
        if path.parts and len(path.parts[0]) == 2 and path.parts[0][1] == ":":
            raise PortableArchiveError("unsafe_path", "El paquete contiene una ruta absoluta.")

    def _verify_file_contract(self, archive: ZipFile, info_by_name: dict[str, ZipInfo], manifest: dict[str, Any], checksums: dict[str, Any], manifest_raw: bytes) -> None:
        rows = manifest["files"]
        declared = {row["path"]: row for row in rows}
        expected_names = {"manifest.json", "checksums.json", *declared}
        if set(info_by_name) != expected_names:
            raise PortableArchiveError("undeclared_file", "El paquete contiene archivos ausentes o no declarados.")
        checksum_files = checksums.get("files", {})
        if set(checksum_files) != ({"manifest.json"} | set(declared)):
            raise PortableArchiveError("checksums_incomplete", "checksums.json no cubre todos los archivos declarados.")
        if checksum_files["manifest.json"] != sha256_bytes(manifest_raw):
            raise PortableArchiveError("checksum_mismatch", "El checksum de manifest.json no coincide.")
        for name, row in declared.items():
            info = info_by_name[name]
            if info.file_size != row["size_bytes"]:
                raise PortableArchiveError("size_mismatch", "El tamaño de un archivo no coincide con el manifest.")
            digest = hashlib.sha256()
            read = 0
            with archive.open(info, "r") as member:
                while chunk := member.read(1024 * 1024):
                    read += len(chunk)
                    if read > self.limits.max_file_bytes:
                        raise PortableArchiveError("file_too_large", "Un archivo supera el límite durante lectura.")
                    digest.update(chunk)
            actual = digest.hexdigest()
            if actual != row["sha256"] or actual != checksum_files[name]:
                raise PortableArchiveError("checksum_mismatch", "El checksum de un archivo no coincide.")

    def _verify_schema_members(self, archive: ZipFile, info_by_name: dict[str, ZipInfo], manifest: dict[str, Any]) -> None:
        required_names = set(CORE_SCHEMA_NAMES) | {
            f"portable_{section}.schema.json" for section in manifest["included_sections"]
        }
        embedded_names = {
            name.removeprefix("schemas/") for name in info_by_name if name.startswith("schemas/")
        }
        if embedded_names != required_names:
            raise PortableArchiveError("unknown_schema", "El paquete no contiene exactamente los schemas requeridos.")
        for name in required_names:
            local_path = self.schema_root / name
            if not local_path.is_file():
                raise PortableArchiveError("unknown_schema", "El lector no reconoce un schema declarado.")
            raw = self._read_limited(archive, info_by_name[f"schemas/{name}"], self.limits.max_file_bytes)
            try:
                embedded = json.loads(raw.decode("utf-8", errors="strict"))
                local = json.loads(local_path.read_text(encoding="utf-8"))
                Draft202012Validator.check_schema(embedded)
            except Exception as error:
                raise PortableArchiveError("unknown_schema", "Un schema embebido no es valido.") from error
            if embedded != local:
                raise PortableArchiveError("unknown_schema", "Un schema embebido no coincide con el contrato instalado.")

    def _read_records(self, archive: ZipFile, info_by_name: dict[str, ZipInfo], manifest: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        included = manifest["included_sections"]
        if len(included) != len(set(included)) or any(section not in ALL_SECTIONS for section in included):
            raise PortableArchiveError("unknown_section", "El manifest declara una sección desconocida.")
        if set(manifest["schema_versions"]) != set(included):
            raise PortableArchiveError("unknown_schema", "Las versiones de schema no coinciden con las secciones.")
        result: dict[str, list[dict[str, Any]]] = {}
        for section in included:
            path = SECTION_PATHS[section]
            if path not in info_by_name:
                raise PortableArchiveError("section_missing", "Falta un archivo de sección declarado.")
            raw = self._read_limited(archive, info_by_name[path], self.limits.max_file_bytes)
            if section in {"profile", "settings"}:
                value = self._decode_json(raw, path)
                records = [] if value is None else [value]
            else:
                records = []
                for line in raw.splitlines():
                    if not line.strip():
                        continue
                    if len(line) > self.limits.max_json_line_bytes:
                        raise PortableArchiveError("json_line_too_large", "Una línea JSON supera el límite.")
                    records.append(self._decode_json(line, path))
                    if len(records) > self.limits.max_records_per_section:
                        raise PortableArchiveError("too_many_records", "Una sección contiene demasiados registros.")
            if len(records) != manifest["counts"].get(section):
                raise PortableArchiveError("count_mismatch", "El conteo de una sección no coincide.")
            for record in records:
                self._reject_forbidden_keys(record)
                self._validate_schema(record, f"portable_{section}.schema.json")
            result[section] = records
        attachment_names = {name for name in info_by_name if name.startswith("attachments/")}
        declared_attachment_names = {
            record.get("data", {}).get("archive_path")
            for record in result.get("attachments", [])
            if record.get("data", {}).get("archive_path")
        }
        if attachment_names != declared_attachment_names:
            raise PortableArchiveError("undeclared_attachment", "Los attachments no coinciden con su metadata.")
        return result

    def _decode_json(self, raw: bytes, label: str) -> Any:
        try:
            text = raw.decode("utf-8", errors="strict")
            value = json.loads(text, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise PortableArchiveError("invalid_json", f"{label} no contiene JSON UTF-8 válido.") from error
        self._validate_json_limits(value)
        return value

    def _validate_json_limits(self, value: Any) -> None:
        def walk(item: Any, depth: int) -> None:
            if depth > self.limits.max_json_depth:
                raise PortableArchiveError("json_too_deep", "El JSON supera la profundidad permitida.")
            if isinstance(item, str) and len(item) > self.limits.max_string_length:
                raise PortableArchiveError("string_too_long", "Un string supera el límite permitido.")
            if isinstance(item, dict):
                for key, nested in item.items():
                    if len(str(key)) > 128:
                        raise PortableArchiveError("key_too_long", "Una clave JSON supera el límite.")
                    walk(nested, depth + 1)
            elif isinstance(item, list):
                for nested in item:
                    walk(nested, depth + 1)
        walk(value, 0)

    @staticmethod
    def _reject_forbidden_keys(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).casefold() in FORBIDDEN_KEYS:
                    raise PortableArchiveError("forbidden_field", "El paquete contiene un identificador o secreto no portable.")
                PortableArchiveReader._reject_forbidden_keys(item)
        elif isinstance(value, list):
            for item in value:
                PortableArchiveReader._reject_forbidden_keys(item)

    def _validate_schema(self, payload: Any, name: str) -> None:
        path = self.schema_root / name
        if not path.is_file():
            raise PortableArchiveError("unknown_schema", "El lector no reconoce un schema declarado.")
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload))
        except Exception as error:
            raise PortableArchiveError("unknown_schema", "El schema local no es válido.") from error
        if errors:
            raise PortableArchiveError("schema_validation_failed", f"{name} no valida el contenido del paquete.")

    @staticmethod
    def _read_limited(archive: ZipFile, info: ZipInfo, maximum: int) -> bytes:
        with archive.open(info, "r") as member:
            value = member.read(maximum + 1)
        if len(value) > maximum:
            raise PortableArchiveError("file_too_large", "Un archivo supera el límite durante lectura.")
        return value
