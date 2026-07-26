"""Add mutable version-backed mobile planning aggregates.

Revision ID: 20260724_0030
Revises: 20260724_0029
"""
from datetime import datetime, timezone
import json
import uuid

from alembic import op
import sqlalchemy as sa


revision = "20260724_0030"
down_revision = "20260724_0029"
branch_labels = None
depends_on = None


def _document(value):
    return json.loads(value) if isinstance(value, str) else value


def _mobile_exercises(value):
    exercises = json.loads(json.dumps(value or []))
    for exercise in exercises:
        exercise.setdefault("id", str(uuid.uuid4()))
        for planned_set in exercise.get("sets", []):
            planned_set.setdefault("id", str(uuid.uuid4()))
    return exercises


def upgrade() -> None:
    op.add_column(
        "training_plans",
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
    )
    op.add_column(
        "training_plans",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "training_plans",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    with op.batch_alter_table("training_plans") as batch_op:
        batch_op.create_check_constraint(
            "ck_training_plans_status", "status IN ('active', 'archived')"
        )
        batch_op.create_check_constraint("ck_training_plans_revision", "revision >= 1")

    op.create_table(
        "training_plan_workouts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("training_plan_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("exercises_json", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.CheckConstraint("position >= 1", name="ck_training_plan_workouts_position"),
        sa.CheckConstraint("revision >= 1", name="ck_training_plan_workouts_revision"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["training_plan_id"], ["training_plans.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "training_plan_id", "position", name="uq_training_plan_workouts_position"
        ),
        sa.UniqueConstraint("public_id", name="uq_training_plan_workouts_public_id"),
    )
    op.create_index(
        "ix_training_plan_workouts_user_plan",
        "training_plan_workouts",
        ["user_id", "training_plan_id"],
    )

    connection = op.get_bind()
    workouts = sa.table(
        "training_plan_workouts",
        sa.column("public_id", sa.String()),
        sa.column("user_id", sa.Integer()),
        sa.column("training_plan_id", sa.Integer()),
        sa.column("name", sa.String()),
        sa.column("notes", sa.Text()),
        sa.column("position", sa.Integer()),
        sa.column("exercises_json", sa.JSON()),
        sa.column("revision", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    plans = connection.execute(
        sa.text("SELECT id, user_id, active_version_number FROM training_plans")
    ).mappings()
    now = datetime.now(timezone.utc)
    for plan in plans:
        content = connection.execute(
            sa.text(
                "SELECT content FROM training_plan_versions "
                "WHERE training_plan_id=:plan_id AND user_id=:user_id "
                "AND version_number=:version_number"
            ),
            {
                "plan_id": plan["id"],
                "user_id": plan["user_id"],
                "version_number": plan["active_version_number"],
            },
        ).scalar_one_or_none()
        if content is None:
            continue
        document = _document(content)
        days = [
            day
            for week in document.get("data", {}).get("weeks", [])
            for day in week.get("days", [])
        ]
        for position, day in enumerate(days, start=1):
            connection.execute(
                workouts.insert().values(
                    public_id=str(uuid.uuid4()),
                    user_id=plan["user_id"],
                    training_plan_id=plan["id"],
                    name=day["name"],
                    notes=day.get("notes"),
                    position=position,
                    exercises_json=_mobile_exercises(day.get("exercises", [])),
                    revision=1,
                    created_at=now,
                    updated_at=now,
                )
            )


def downgrade() -> None:
    op.drop_table("training_plan_workouts")
    with op.batch_alter_table("training_plans") as batch_op:
        batch_op.drop_constraint("ck_training_plans_revision", type_="check")
        batch_op.drop_constraint("ck_training_plans_status", type_="check")
        batch_op.drop_column("archived_at")
        batch_op.drop_column("revision")
        batch_op.drop_column("status")
