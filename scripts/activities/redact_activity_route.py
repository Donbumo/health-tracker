from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from _common import PROJECT_ROOT, explicit_output

import sys
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
from app.services.activity_interchange import redact_route  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Crea una copia de activity-v1 sin ruta o con extremos recortados.")
    parser.add_argument("input", type=Path, help="JSON activity-v1")
    parser.add_argument("--output", required=True, type=Path, help="Copia nueva; nunca sobrescribe")
    parser.add_argument("--drop-route", action="store_true", help="Elimina toda la ruta")
    parser.add_argument("--start-meters", type=int, default=0, help="Metros a ocultar al inicio")
    parser.add_argument("--end-meters", type=int, default=0, help="Metros a ocultar al final")
    parser.add_argument("--show-sensitive-route", action="store_true", help="Muestra la ruta resultante tras una advertencia")
    args = parser.parse_args()
    if args.start_meters < 0 or args.end_meters < 0:
        parser.error("Los metros de recorte no pueden ser negativos.")
    document = json.loads(args.input.read_text(encoding="utf-8"))
    route = document.get("route") or {}
    points = route.get("points") or []
    if args.drop_route:
        visible = []
        document["route"] = {"present": False, "state": "removed", "policy": "drop", "pointCount": 0}
    else:
        visible = redact_route(points, args.start_meters, args.end_meters)
        document["route"] = {"present": bool(visible), "state": "available" if visible else "removed", "policy": "redact", "pointCount": len(visible), "distanceMeters": route_distance(visible), "redactStartMeters": args.start_meters, "redactEndMeters": args.end_meters, "points": visible}
    explicit_output(args.output)
    args.output.write_text(json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print("Advertencia: se creó una copia; el original no fue modificado.")
    if args.show_sensitive_route:
        print("ADVERTENCIA: se mostrarán coordenadas sensibles; no compartas esta salida.")
        print(json.dumps(visible, ensure_ascii=False, indent=2))
    return 0


def route_distance(points: list[dict]) -> float:
    def segment(left: dict, right: dict) -> float:
        lat1, lon1, lat2, lon2 = map(math.radians, [left["lat"], left["lon"], right["lat"], right["lon"]])
        dlat, dlon = lat2 - lat1, lon2 - lon1
        value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        return 6_371_000 * 2 * math.atan2(math.sqrt(value), math.sqrt(max(0, 1 - value)))
    return round(sum(segment(left, right) for left, right in zip(points, points[1:])), 2)


if __name__ == "__main__":
    raise SystemExit(main())
