"""Durable normalized Gym import drafts; no uploaded file dependency."""
from alembic import op
import sqlalchemy as sa

revision = "20260928_0043"
down_revision = "20260927_0042"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("gym_import_drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(36), nullable=False, unique=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_plan_id", sa.Integer(), sa.ForeignKey("training_plans.id", ondelete="SET NULL")),
        sa.Column("target_public_id", sa.String(36)),
        sa.Column("base_revision", sa.Integer()),
        sa.Column("result_plan_id", sa.Integer(), sa.ForeignKey("training_plans.id", ondelete="SET NULL")),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.CheckConstraint("state IN ('pending', 'completed', 'cancelled')", name="ck_gym_import_drafts_state"),
        sa.CheckConstraint("revision >= 1", name="ck_gym_import_drafts_revision"))
    op.create_index("ix_gym_import_drafts_user_state", "gym_import_drafts", ["user_id", "state", "updated_at"])


def downgrade():
    op.drop_table("gym_import_drafts")
