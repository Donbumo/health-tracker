from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from _common import PROJECT_ROOT


def main() -> int:
    parser = argparse.ArgumentParser(description="Verifica contrato, fechas, métricas, límites y checksum de activity-v1.")
    parser.add_argument("input", type=Path, help="JSON health-tracker-activity-v1")
    args = parser.parse_args()
    if not args.input.is_file() or args.input.is_symlink():
        parser.error("La entrada debe ser un archivo regular.")
    raw = args.input.read_bytes()
    document = json.loads(raw.decode("utf-8"))
    schema = json.loads((PROJECT_ROOT / "schemas" / "activity_v1.schema.json").read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(document), key=lambda item: list(item.absolute_path))
    if errors:
        for error in errors[:20]:
            location = ".".join(map(str, error.absolute_path)) or "$"
            print(f"ERROR {location}: {error.message}")
        return 1
    series = document.get("series", {}).get("samples", [])
    if len(series) > 100000:
        print("ERROR series: demasiadas muestras")
        return 1
    print(json.dumps({"valid": True, "format": document["format"], "samples": len(series), "file_sha256_short": hashlib.sha256(raw).hexdigest()[:12]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
