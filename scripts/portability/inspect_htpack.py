#!/usr/bin/env python3
from __future__ import annotations

from htpack_common import dump, fail, health_warning, parser, reader, require_file


def main() -> int:
    args_parser = parser("Inspecciona estructura, integridad y metadata de un paquete Health Tracker.")
    args_parser.add_argument("--show-records", action="store_true", help="Muestra contenido sensible tras advertirlo explícitamente.")
    args = args_parser.parse_args()
    try:
        require_file(args.package)
        inspection = reader(args.schema_root).inspect(args.package)
        output = inspection.report()
        if args.show_records:
            health_warning()
            output["records"] = inspection.records
        dump(output)
        return 0
    except Exception as error:
        return fail(error)


if __name__ == "__main__":
    raise SystemExit(main())
