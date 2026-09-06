from __future__ import annotations

import unicodedata

from app.services.mobile_progress import progress_exercise_detail, progress_exercises


def _normalized(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(item for item in decomposed if not unicodedata.combining(item)).strip()


class ExerciseProgressService:
    """Provider-neutral adapter over the existing owner-only progress read model."""

    def build(
        self,
        user_id: int,
        range_value: str,
        *,
        exercise: str | None = None,
        limit: int = 8,
    ) -> dict:
        mobile_range = range_value[:-1] if range_value.endswith("d") else range_value
        overview = progress_exercises(user_id, mobile_range)
        items = overview["items"]
        selected = None
        if exercise:
            needle = _normalized(exercise)
            exact = [item for item in items if _normalized(item["name"]) == needle]
            matches = exact or [item for item in items if needle in _normalized(item["name"])]
            if len(matches) == 1:
                selected = matches[0]
            elif matches:
                return {
                    "range": range_value,
                    "status": "ambiguous_exercise",
                    "matches": [item["name"] for item in matches[:10]],
                    "coverage": {"matching_exercises": len(matches)},
                }
            else:
                return {
                    "range": range_value,
                    "status": "exercise_not_found",
                    "matches": [],
                    "coverage": {"matching_exercises": 0},
                }
        if selected is None:
            return {
                "range": range_value,
                "status": "summary",
                "exercises": [self._summary(item) for item in items[:limit]],
                "coverage": {"exercises": len(items), "returned": min(limit, len(items))},
            }

        detail = progress_exercise_detail(user_id, selected["public_id"], mobile_range)
        return {
            "range": range_value,
            "status": "detail",
            "exercise": self._summary(detail["exercise"]),
            "points": [
                {
                    key: point.get(key)
                    for key in (
                        "date",
                        "best_load_kg",
                        "best_reps",
                        "volume_kg",
                        "set_count",
                        "average_rir",
                        "average_rpe",
                        "load_comparable",
                    )
                }
                for point in detail["points"][-20:]
            ],
            "personal_records": [
                {
                    key: record.get(key)
                    for key in ("type", "value", "unit", "date")
                }
                for record in detail["personal_records"]
            ],
            "coverage": {
                "sessions": detail["exercise"]["session_count"],
                "sets": detail["exercise"]["set_count"],
                "comparable": detail["exercise"]["load_comparable"],
            },
        }

    @staticmethod
    def _summary(item: dict) -> dict:
        return {
            key: item.get(key)
            for key in (
                "name",
                "last_performed_at",
                "session_count",
                "set_count",
                "best_load_kg",
                "best_repetition_set",
                "volume_kg",
                "volume_partial",
                "load_comparable",
                "load_modes",
                "trend",
            )
        }
