from datetime import datetime, timezone

from app.extensions import db


class Exercise(db.Model):
    __tablename__ = "exercises"
    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "normalized_name",
            name="uq_exercises_user_normalized_name",
        ),
        db.Index("ix_exercises_user_name", "user_id", "normalized_name"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    canonical_name = db.Column(db.String(200), nullable=False)
    normalized_name = db.Column(db.String(255), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=db.func.current_timestamp(),
    )

    user = db.relationship("User", back_populates="exercises")
    aliases = db.relationship(
        "ExerciseAlias",
        back_populates="exercise",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ExerciseAlias.alias_name",
    )


class ExerciseAlias(db.Model):
    __tablename__ = "exercise_aliases"
    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "normalized_name",
            name="uq_exercise_aliases_user_normalized_name",
        ),
        db.Index(
            "ix_exercise_aliases_user_exercise",
            "user_id",
            "exercise_id",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    exercise_id = db.Column(
        db.Integer,
        db.ForeignKey("exercises.id", ondelete="CASCADE"),
        nullable=False,
    )
    alias_name = db.Column(db.String(200), nullable=False)
    normalized_name = db.Column(db.String(255), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=db.func.current_timestamp(),
    )

    user = db.relationship("User", back_populates="exercise_aliases")
    exercise = db.relationship("Exercise", back_populates="aliases")
