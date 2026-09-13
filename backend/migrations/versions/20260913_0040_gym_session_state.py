"""Gym session lifecycle; preserve legacy sessions as completed."""
from alembic import op
import sqlalchemy as sa

revision = "20260913_0040"
down_revision = "20260906_0039"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("training_plans", sa.Column("gym_active", sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table("training_sessions") as batch:
        batch.add_column(sa.Column("status", sa.String(20), nullable=False, server_default="completed"))
        batch.create_check_constraint("ck_training_sessions_status", "status IN ('in_progress', 'completed', 'abandoned')")
        batch.create_index("ix_training_sessions_user_status", ["user_id", "status"])


def downgrade():
    # Only run against disposable QA storage or after exporting open sessions.
    with op.batch_alter_table("training_sessions") as batch:
        batch.drop_index("ix_training_sessions_user_status")
        batch.drop_constraint("ck_training_sessions_status", type_="check")
        batch.drop_column("status")
    op.drop_column("training_plans", "gym_active")
