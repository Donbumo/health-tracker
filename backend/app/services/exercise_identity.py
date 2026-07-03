import unicodedata

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Exercise, ExerciseAlias


class ExerciseIdentityError(ValueError):
    pass


def _clean_name(name: str) -> str:
    if not isinstance(name, str):
        raise ExerciseIdentityError("Exercise name must be text")
    cleaned = " ".join(unicodedata.normalize("NFKC", name).split())
    if not cleaned:
        raise ExerciseIdentityError("Exercise name must not be blank")
    if len(cleaned) > 200:
        raise ExerciseIdentityError("Exercise name is too long")
    return cleaned


def normalize_exercise_name(name: str) -> str:
    normalized = _clean_name(name).casefold()
    if len(normalized) > 255:
        raise ExerciseIdentityError("Normalized exercise name is too long")
    return normalized


def find_exercise_identity(user_id: int, name: str) -> Exercise | None:
    normalized = normalize_exercise_name(name)
    exercise = db.session.execute(
        db.select(Exercise).where(
            Exercise.user_id == user_id,
            Exercise.normalized_name == normalized,
        )
    ).scalar_one_or_none()
    if exercise is not None:
        return exercise

    alias = db.session.execute(
        db.select(ExerciseAlias).where(
            ExerciseAlias.user_id == user_id,
            ExerciseAlias.normalized_name == normalized,
        )
    ).scalar_one_or_none()
    if alias is None or alias.exercise.user_id != user_id:
        return None
    return alias.exercise


def get_or_create_exercise(
    user_id: int,
    canonical_name: str,
) -> tuple[Exercise, bool]:
    cleaned = _clean_name(canonical_name)
    existing = find_exercise_identity(user_id, cleaned)
    if existing is not None:
        return existing, False

    exercise = Exercise(
        user_id=user_id,
        canonical_name=cleaned,
        normalized_name=normalize_exercise_name(cleaned),
    )
    db.session.add(exercise)
    try:
        db.session.commit()
        return exercise, True
    except IntegrityError:
        db.session.rollback()
        existing = find_exercise_identity(user_id, cleaned)
        if existing is not None:
            return existing, False
        raise


def add_exercise_alias(
    user_id: int,
    exercise_id: int,
    alias_name: str,
) -> tuple[ExerciseAlias | None, bool]:
    exercise = db.session.execute(
        db.select(Exercise).where(
            Exercise.id == exercise_id,
            Exercise.user_id == user_id,
        )
    ).scalar_one_or_none()
    if exercise is None:
        raise ExerciseIdentityError("Exercise identity does not belong to this user")

    cleaned = _clean_name(alias_name)
    normalized = normalize_exercise_name(cleaned)
    existing_identity = find_exercise_identity(user_id, cleaned)
    if existing_identity is not None:
        if existing_identity.id == exercise.id:
            existing_alias = next(
                (
                    alias
                    for alias in exercise.aliases
                    if alias.normalized_name == normalized
                ),
                None,
            )
            return existing_alias, False
        raise ExerciseIdentityError(
            "That name already belongs to another exercise identity"
        )

    alias = ExerciseAlias(
        user_id=user_id,
        exercise_id=exercise.id,
        alias_name=cleaned,
        normalized_name=normalized,
    )
    db.session.add(alias)
    try:
        db.session.commit()
        return alias, True
    except IntegrityError:
        db.session.rollback()
        existing_identity = find_exercise_identity(user_id, cleaned)
        if existing_identity is not None and existing_identity.id == exercise.id:
            return None, False
        raise


def exercise_identity_names(exercise: Exercise) -> set[str]:
    return {
        exercise.normalized_name,
        *(alias.normalized_name for alias in exercise.aliases),
    }
