"""Read-only media projection of the existing owner-scoped exercise identities.

Asset IDs identify artwork, never a second exercise catalogue. No fuzzy matching,
DB writes, remote requests or changes to stored prescriptions.
"""
import json
from pathlib import Path

from flask import current_app

from app.services.exercise_identity import normalize_exercise_name


def media_catalog():
    path = Path(current_app.static_folder) / "media/gym-catalog.json"
    try:
        entries = json.loads(path.read_text(encoding="utf-8")).get("entries", [])
        return [entry for entry in entries if isinstance(entry, dict)
                and isinstance(entry.get("media_asset_id"), str)
                and entry["media_asset_id"] and isinstance(entry.get("name"), str)
                and entry["name"].strip()]
    except (OSError, ValueError, TypeError, AttributeError):
        return []  # A missing optional presentation file must not break a workout.


def media_projection(identities, entries):
    by_id = {item.public_id: item for item in identities}
    by_name = {}
    assets = {}
    for item in identities:
        for name in [item.normalized_name, *(a.normalized_name for a in item.aliases if a.user_id == item.user_id)]:
            by_name.setdefault(name, set()).add(item.public_id)
    for entry in entries:
        for name in [entry["name"], *entry.get("aliases", [])]:
            assets.setdefault(normalize_exercise_name(name), set()).add(entry["media_asset_id"])

    def binding(exercise):
        explicit = exercise.get("exercise_id") or exercise.get("resolved_exercise_id") or exercise.get("identity")
        name = exercise.get("name") or exercise.get("raw_name") or ""
        if explicit:
            matches = {explicit} if explicit in by_id else set()
        else:
            matches = by_name.get(normalize_exercise_name(name), set()) if name else set()
        if len(matches) != 1:
            return {"status": "ambiguous" if len(matches) > 1 else "unresolved"}
        item = by_id[next(iter(matches))]
        names = [item.normalized_name, *(a.normalized_name for a in item.aliases if a.user_id == item.user_id)]
        found = set().union(*(assets.get(n, set()) for n in names))
        result = {"internal_exercise_id": item.public_id}
        if len(found) == 1:
            return result | {"status": "available", "media_asset_id": next(iter(found))}
        ambiguous = len(found) > 1 or item.normalized_name in {"prensa", "press", "remo"}
        return result | {"status": "ambiguous" if ambiguous else "no_media"}

    return binding
