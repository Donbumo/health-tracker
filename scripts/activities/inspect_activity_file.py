from __future__ import annotations

import argparse
import json
from pathlib import Path

from _common import parse_activity


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspecciona FIT/GPX/TCX/JSON/CSV sin importar ni escribir datos.")
    parser.add_argument("input", type=Path, help="Archivo de actividad")
    parser.add_argument("--show-sensitive-route", action="store_true", help="Muestra coordenadas sintéticas/sensibles tras advertencia explícita")
    args = parser.parse_args()
    parsed = parse_activity(args.input)
    summary = {
        "format": parsed.source_format, "size_bytes": args.input.stat().st_size,
        "start_time_hour": parsed.document["activity"]["startTime"][:13] + ":00:00Z",
        "discipline": parsed.document["activity"]["discipline"],
        "laps": len(parsed.laps), "samples": len(parsed.samples),
        "metrics": parsed.document["sampleSeries"]["fields"],
        "route_present": bool(parsed.route_points), "route_points": len(parsed.route_points),
        "warnings": parsed.warnings,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.show_sensitive_route:
        print("ADVERTENCIA: se mostrarán coordenadas sensibles; no compartas esta salida.")
        print(json.dumps(parsed.route_points, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
