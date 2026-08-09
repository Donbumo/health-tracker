#!/usr/bin/env python3
from __future__ import annotations

from htpack_common import dump, fail, parser, reader, require_file


def main() -> int:
    args = parser("Verifica ZIP safety, límites, schemas y SHA-256 de un paquete Health Tracker.").parse_args()
    try:
        require_file(args.package)
        inspection = reader(args.schema_root).inspect(args.package)
        dump({
            "valid": True,
            "format": inspection.manifest["format"],
            "format_version": inspection.manifest["format_version"],
            "integrity": "verified",
            "authenticity": "not_proven",
            "package_sha256": inspection.package_sha256,
            "sections": inspection.manifest["included_sections"],
        })
        return 0
    except Exception as error:
        return fail(error)


if __name__ == "__main__":
    raise SystemExit(main())
