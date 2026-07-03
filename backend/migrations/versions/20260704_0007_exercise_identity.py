"""Add user-scoped exercise identities and aliases.

Revision ID: 20260704_0007
Revises: 20260703_0006
Create Date: 2026-07-04
"""

from alembic import op
import sqlalchemy as sa


revision = "20260704_0007"
down_revision = "20260703_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exercises",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("canonical_name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "normalized_name",
            name="uq_exercises_user_normalized_name",
        ),
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_exercises_user_name",
        "exercises",
        ["user_id", "normalized_name"],
        unique=False,
    )

    op.create_table(
        "exercise_aliases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("exercise_id", sa.Integer(), nullable=False),
        sa.Column("alias_name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["exercise_id"],
            ["exercises.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "normalized_name",
            name="uq_exercise_aliases_user_normalized_name",
        ),
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_exercise_aliases_user_exercise",
        "exercise_aliases",
        ["user_id", "exercise_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_exercise_aliases_user_exercise",
        table_name="exercise_aliases",
    )
    op.drop_table("exercise_aliases")
    op.drop_index("ix_exercises_user_name", table_name="exercises")
    op.drop_table("exercises")
