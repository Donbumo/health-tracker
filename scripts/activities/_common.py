from __future__ import annotations

import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.activity_parsers import ActivityParserRegistry  # noqa: E402


def parse_activity(path: Path):
    if not path.is_file() or path.is_symlink():
        raise ValueError("La entrada debe ser un archivo regular.")
    content = path.read_bytes()
    return ActivityParserRegistry().parse(path.name, content)


def output_document(parsed, *, include_route: bool = True) -> dict:
    document = json.loads(json.dumps(parsed.document))
    document["series"] = {"format": "activity-series-v1", "samples": parsed.samples}
    if include_route and parsed.route_points:
        document["route"]["points"] = parsed.route_points
    return document


def explicit_output(path: Path) -> None:
    if path.exists():
        raise ValueError("La salida ya existe; no se sobrescribió.")
    path.parent.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, value: dict) -> None:
    explicit_output(path)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
