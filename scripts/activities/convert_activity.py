from __future__ import annotations

import argparse
from pathlib import Path

from _common import output_document, parse_activity, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Convierte FIT/GPX/TCX a health-tracker-activity-v1.")
    parser.add_argument("input", type=Path, help="Archivo fuente")
    parser.add_argument("--output", required=True, type=Path, help="JSON de salida nuevo")
    parser.add_argument("--drop-route", action="store_true", help="Omite coordenadas en la copia convertida")
    args = parser.parse_args()
    parsed = parse_activity(args.input)
    document = output_document(parsed, include_route=not args.drop_route)
    if args.drop_route:
        document["route"] = {"present": False, "state": "removed", "policy": "drop", "pointCount": 0}
    write_json(args.output, document)
    print(f"Creado: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
