"""Bounded data-only source adapters. No upstream code is imported or executed."""
from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
import re
import tarfile
import time
from typing import Protocol
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from jsonschema import Draft202012Validator
from PIL import Image

from app.services.exercise_identity import normalize_exercise_name

MAX_DOWNLOAD = 256 * 1024 * 1024
MAX_EXPANDED = 512 * 1024 * 1024
MAX_FILE = 8 * 1024 * 1024
MAX_FILES = 12000
TIMEOUT = 30
DEADLINE = 300


class CatalogError(ValueError):
    pass


class ExternalExerciseCatalogSource(Protocol):
    source_id: str
    source_name: str
    source_revision: str
    license: str

    def fetch(self, staging, ref, metadata_only=False): ...
    def validate(self, content): ...
    def normalize(self, entries): ...
    def media(self, staging, entries): ...


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise CatalogError("Source redirect rejected.")


def download(url, destination, limit, content_types):
    if not url.startswith(("https://api.github.com/", "https://codeload.github.com/", "https://raw.githubusercontent.com/yuhonas/free-exercise-db/")):
        raise CatalogError("Source URL rejected.")
    started = time.monotonic()
    try:
        with build_opener(NoRedirect).open(Request(url, headers={"User-Agent": "HealthTracker-catalog/1.0", "Accept-Encoding": "identity"}), timeout=TIMEOUT) as response:
            if response.headers.get_content_type() not in content_types:
                raise CatalogError("Unexpected download content type.")
            length = response.headers.get("Content-Length")
            if length and (not length.isdigit() or int(length) > limit):
                raise CatalogError("Download exceeds size limit.")
            total = 0
            with destination.open("wb") as output:
                while chunk := response.read(64 * 1024):
                    total += len(chunk)
                    if total > limit or time.monotonic() - started > DEADLINE:
                        raise CatalogError("Download size/time limit exceeded.")
                    output.write(chunk)
    except (URLError, TimeoutError, OSError) as error:
        raise CatalogError("Source download failed or timed out.") from error


def safe_relative(value):
    if not isinstance(value, str) or not value or len(value) > 240 or "\\" in value or ":" in value or "\x00" in value:
        raise CatalogError("Unsafe archive path.")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise CatalogError("Unsafe archive path.")
    for part in path.parts:
        if part.endswith((" ", ".")) or re.search(r'[<>"|?*\x00-\x1f]', part) or re.fullmatch(r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part, re.I):
            raise CatalogError("Unsafe portable file name.")
    return path


_text = {"type": "string", "minLength": 1, "maxLength": 200}
_muscles = "abdominals abductors adductors biceps calves chest forearms glutes hamstrings lats neck quadriceps shoulders traps triceps".split() + ["lower back", "middle back"]
_schema = {
    "type": "array", "minItems": 1, "maxItems": 5000,
    "items": {"type": "object", "required": ["id", "name", "level", "mechanic", "equipment", "primaryMuscles", "secondaryMuscles", "instructions", "category", "images"],
        "additionalProperties": False, "properties": {
            "id": _text | {"pattern": "^[0-9a-zA-Z_-]+$"}, "name": _text,
            "force": {"enum": [None, "static", "pull", "push"]},
            "level": {"enum": ["beginner", "intermediate", "expert"]},
            "mechanic": {"enum": [None, "isolation", "compound"]},
            "equipment": {"enum": [None, "medicine ball", "dumbbell", "body only", "bands", "kettlebells", "foam roll", "cable", "machine", "barbell", "exercise ball", "e-z curl bar", "other"]},
            "primaryMuscles": {"type": "array", "maxItems": 20, "items": {"enum": _muscles}},
            "secondaryMuscles": {"type": "array", "maxItems": 20, "items": {"enum": _muscles}},
            "instructions": {"type": "array", "maxItems": 100, "items": {"type": "string", "maxLength": 5000}},
            "category": {"enum": ["powerlifting", "strength", "stretching", "cardio", "olympic weightlifting", "strongman", "plyometrics"]},
            "images": {"type": "array", "maxItems": 10, "uniqueItems": True, "items": {"type": "string", "maxLength": 240}},
        }},
}


class FreeExerciseDBSource:
    source_id = "free-exercise-db"
    source_name = "Free Exercise DB"
    repository = "https://github.com/yuhonas/free-exercise-db"
    license = "Unlicense"
    source_revision = ""

    def fetch(self, staging, ref="main", metadata_only=False):
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", ref):
            raise CatalogError("Invalid source ref.")
        commit_file = staging / "commit.json"
        download(f"https://api.github.com/repos/yuhonas/free-exercise-db/commits/{ref}", commit_file, 2 * 1024 * 1024, {"application/json"})
        try:
            self.source_revision = json.loads(commit_file.read_bytes())["sha"]
        except (ValueError, KeyError, TypeError) as error:
            raise CatalogError("Invalid commit response.") from error
        if not isinstance(self.source_revision, str) or not re.fullmatch("[a-f0-9]{40}", self.source_revision):
            raise CatalogError("Invalid commit revision.")
        if metadata_only:
            folder = staging / "snapshot"
            folder.mkdir()
            base = f"https://raw.githubusercontent.com/yuhonas/free-exercise-db/{self.source_revision}"
            download(base + "/dist/exercises.json", folder / "exercises.json", MAX_FILE, {"text/plain", "application/json"})
            download(base + "/LICENSE.md", folder / "LICENSE.md", 65536, {"text/plain"})
            self.validate_license(folder)
            return folder
        archive = staging / "download.tar.gz"
        download(f"https://codeload.github.com/yuhonas/free-exercise-db/tar.gz/{self.source_revision}", archive, MAX_DOWNLOAD, {"application/gzip", "application/x-gzip", "application/octet-stream"})
        self.extract(archive, staging / "snapshot", metadata_only)
        return staging / "snapshot"

    def extract(self, archive, destination, metadata_only=False):
        destination.mkdir()
        count = total = 0
        seen = set()
        root = None
        try:
            with tarfile.open(archive, "r|gz") as bundle:
                for member in bundle:
                    count += 1
                    total += member.size
                    if count > MAX_FILES or total > MAX_EXPANDED or member.size > MAX_FILE or member.size < 0:
                        raise CatalogError("Archive exceeds limits.")
                    path = safe_relative(member.name.rstrip("/"))
                    root = root or path.parts[0]
                    member_key = str(path).casefold()
                    if path.parts[0] != root or member_key in seen:
                        raise CatalogError("Invalid archive member.")
                    seen.add(member_key)
                    # The upstream frontend contains a symlink to exercises.
                    # Ignore the entire site tree; never materialize its links.
                    if len(path.parts) > 1 and path.parts[1] == "site":
                        continue
                    if not (member.isfile() or member.isdir()):
                        raise CatalogError("Invalid archive member.")
                    if member.isdir():
                        continue
                    relative = PurePosixPath(*path.parts[1:])
                    key = str(relative)
                    selected = key in {"dist/exercises.json", "LICENSE.md"} or (not metadata_only and len(relative.parts) == 3 and relative.parts[0] == "exercises" and relative.suffix.lower() in {".jpg", ".jpeg", ".png"})
                    if not selected:
                        continue
                    target = destination / ("exercises.json" if key == "dist/exercises.json" else relative)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.extractfile(member) as stream:
                        target.write_bytes(stream.read(MAX_FILE + 1))
            self.validate_license(destination)
        except (tarfile.TarError, OSError, UnicodeError, EOFError) as error:
            raise CatalogError("Malformed or incomplete source archive.") from error

    def validate_license(self, folder):
        license_text = (folder / "LICENSE.md").read_text(encoding="utf-8")
        if "public domain" not in license_text.lower() or "unlicense.org" not in license_text.lower():
            raise CatalogError("Source license needs review.")

    def validate(self, content):
        if len(content) > MAX_FILE:
            raise CatalogError("Metadata exceeds size limit.")
        try:
            entries = json.loads(content)
        except (ValueError, UnicodeError, RecursionError) as error:
            raise CatalogError("Invalid catalog JSON.") from error
        if next(Draft202012Validator(_schema).iter_errors(entries), None):
            raise CatalogError("Catalog does not satisfy the source schema.")
        seen = set()
        for entry in entries:
            if entry["id"] in seen or not entry["name"].strip():
                raise CatalogError("Duplicate ID or blank source name.")
            seen.add(entry["id"])
            for value in entry["images"]:
                path = safe_relative(value)
                if len(path.parts) != 2 or path.parts[0] != entry["id"] or path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                    raise CatalogError("Invalid media reference.")
        return entries

    def normalize(self, entries):
        return [{"external_id": e["id"], "name": e["name"], "normalized_name": normalize_exercise_name(e["name"]),
            "details": {"force": e.get("force"), "difficulty": e["level"], "mechanic": e["mechanic"], "equipment": e["equipment"], "primary_muscles": e["primaryMuscles"], "secondary_muscles": e["secondaryMuscles"], "instructions": e["instructions"], "category": e["category"]}} for e in entries]

    def media(self, staging, entries):
        result = {}
        for entry in entries:
            result[entry["id"]] = []
            for position, relative in enumerate(entry["images"]):
                path = staging / "exercises" / safe_relative(relative)
                try:
                    with Image.open(path) as picture:
                        expected = "PNG" if path.suffix.lower() == ".png" else "JPEG"
                        if picture.format != expected or picture.width * picture.height > 25_000_000:
                            raise CatalogError("Invalid image MIME or dimensions.")
                        picture.load()
                        width, height = picture.size
                except (OSError, ValueError, Image.DecompressionBombError) as error:
                    raise CatalogError("Invalid or missing catalog image.") from error
                result[entry["id"]].append({"source": self.source_id, "external_exercise_id": entry["id"], "relative_path": "exercises/" + relative, "position": position, "mime_type": "image/png" if expected == "PNG" else "image/jpeg", "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "width": width, "height": height, "license": self.license})
        return result
