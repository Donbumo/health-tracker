"""Add advanced workout load entry preferences and details.

Revision ID: 20260716_0027
Revises: 20260715_0026
"""
from alembic import op
import sqlalchemy as sa


revision = "20260716_0027"
down_revision = "20260715_0026"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("preferred_load_unit", sa.String(2), server_default="kg", nullable=False))
        batch_op.create_check_constraint("ck_users_load_unit", "preferred_load_unit IN ('kg', 'lb')")
    with op.batch_alter_table("training_sets") as batch_op:
        batch_op.add_column(sa.Column("load_details_json", sa.JSON(), nullable=True))
    op.create_table(
        "exercise_load_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("exercise_id", sa.Integer(), sa.ForeignKey("exercises.id", ondelete="CASCADE"), nullable=False),
        sa.Column("load_mode", sa.String(64), server_default="direct_total", nullable=False),
        sa.Column("preferred_unit", sa.String(2), server_default="kg", nullable=False),
        sa.Column("configuration_json", sa.JSON(), nullable=False),
        sa.Column("quick_increments_json", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.UniqueConstraint("public_id", name="uq_exercise_load_profiles_public_id"),
        sa.UniqueConstraint("user_id", "exercise_id", name="uq_exercise_load_profiles_user_exercise"),
        sa.CheckConstraint("preferred_unit IN ('kg', 'lb')", name="ck_exercise_load_profiles_unit"),
        sa.CheckConstraint("load_mode IN ('direct_total','per_side','bar_plus_per_side','machine_initial_total','machine_initial_per_side','machine_external_per_side_initial_total','selector_stack','dumbbell_each','bodyweight','bodyweight_plus','assistance','duration_distance')", name="ck_exercise_load_profiles_mode"),
        sa.CheckConstraint("revision >= 1", name="ck_exercise_load_profiles_revision"),
    )
    op.create_index("ix_exercise_load_profiles_user_exercise", "exercise_load_profiles", ["user_id", "exercise_id"])


def downgrade():
    op.drop_table("exercise_load_profiles")
    with op.batch_alter_table("training_sets") as batch_op:
        batch_op.drop_column("load_details_json")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("ck_users_load_unit", type_="check")
        batch_op.drop_column("preferred_load_unit")
