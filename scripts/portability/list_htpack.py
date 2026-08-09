#!/usr/bin/env python3
from __future__ import annotations

from htpack_common import dump, fail, health_warning, parser, reader, require_file


def main() -> int:
    args_parser = parser("Lista secciones y conteos sin mostrar registros de salud.")
    args_parser.add_argument("--show-records", action="store_true", help="Muestra contenido sensible tras advertirlo explícitamente.")
    args = args_parser.parse_args()
    try:
        require_file(args.package)
        inspection = reader(args.schema_root).inspect(args.package)
        attachment_metadata = [
            {
                "public_id": record["public_id"],
                "filename": record["data"].get("filename"),
                "media_type": record["data"].get("media_type"),
                "size_bytes": record["data"].get("size_bytes"),
            }
            for record in inspection.records.get("attachments", [])
        ]
        output = {
            "format": inspection.manifest["format"],
            "format_version": inspection.manifest["format_version"],
            "sections": inspection.manifest["included_sections"],
            "counts": inspection.manifest["counts"],
            "attachments": attachment_metadata,
        }
        if args.show_records:
            health_warning()
            output["records"] = inspection.records
        dump(output)
        return 0
    except Exception as error:
        return fail(error)


if __name__ == "__main__":
    raise SystemExit(main())
