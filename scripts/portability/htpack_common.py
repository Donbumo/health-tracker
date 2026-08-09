from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_MODULE_PATH = next(path for path in (
    PROJECT_ROOT / "backend" / "app" / "services" / "portable_archive.py",
    PROJECT_ROOT / "app" / "services" / "portable_archive.py",
) if path.is_file())
_spec = importlib.util.spec_from_file_location("health_tracker_portable_archive", ARCHIVE_MODULE_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError("No se pudo cargar el lector portable.")
_archive = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _archive
_spec.loader.exec_module(_archive)

PortableArchiveError = _archive.PortableArchiveError
PortableArchiveReader = _archive.PortableArchiveReader
PortableArchiveWriter = _archive.PortableArchiveWriter
PortableLimits = _archive.PortableLimits
ALL_SECTIONS = _archive.ALL_SECTIONS


def parser(description: str) -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=description)
    value.add_argument("package", type=Path, help="Ruta al paquete .htpack (se valida por contenido).")
    value.add_argument("--schema-root", type=Path, default=PROJECT_ROOT / "schemas", help="Directorio de JSON Schemas públicos.")
    return value


def reader(schema_root: Path) -> PortableArchiveReader:
    return PortableArchiveReader(schema_root, PortableLimits())


def require_file(path: Path) -> None:
    if not path.is_file():
        raise PortableArchiveError("file_not_found", "No existe el archivo indicado.")


def dump(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def fail(error: Exception) -> int:
    code = getattr(error, "code", "unexpected_error")
    print(f"ERROR [{code}]: {error}", file=sys.stderr)
    return 3 if code == "file_not_found" else 2


def health_warning() -> None:
    print("ADVERTENCIA: mostrar registros puede revelar datos personales de salud.", file=sys.stderr)
