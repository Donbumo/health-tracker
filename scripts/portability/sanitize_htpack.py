#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import uuid

from htpack_common import (
    ALL_SECTIONS, PortableArchiveWriter, fail, parser, reader, require_file,
)


def _sanitize(value):
    if isinstance(value, dict):
        return {
            key: _sanitize(item)
            for key, item in value.items()
            if key not in {"notes", "email", "display_name", "external_origin", "source_app"}
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def main() -> int:
    args_parser = parser("Crea una copia saneada sin perfil identificable, notas, attachments ni procedencia externa.")
    args_parser.add_argument("output", type=Path, help="Nueva ruta .htpack; nunca se sobrescribe el original.")
    args = args_parser.parse_args()
    try:
        require_file(args.package)
        if args.output.exists():
            raise ValueError("La salida ya existe; sanitize nunca sobrescribe archivos.")
        if args.package.resolve() == args.output.resolve():
            raise ValueError("La salida debe ser distinta del original.")
        inspection = reader(args.schema_root).inspect(args.package)
        records = {
            section: [_sanitize(record) for record in section_records]
            for section, section_records in inspection.records.items()
            if section not in {"profile", "attachments", "external_sources"}
        }
        for section_records in records.values():
            for record in section_records:
                data = record.get("data", {})
                if "source" in data and data["source"] != "manual":
                    data["source"] = "redacted"
        omitted = [section for section in ALL_SECTIONS if section not in records]
        PortableArchiveWriter(args.schema_root).write(
            args.output,
            export_id=str(uuid.uuid4()),
            created_at=datetime.now(timezone.utc),
            application_version="sanitized-copy-1.0",
            timezone_name=None,
            records=records,
            omitted_sections=omitted,
            identifiable_profile=False,
            attachment_files={},
        )
        print(f"Copia saneada creada: {args.output}")
        print("Se eliminaron perfil identificable, notas, attachments y procedencia externa.")
        return 0
    except Exception as error:
        return fail(error)


if __name__ == "__main__":
    raise SystemExit(main())
