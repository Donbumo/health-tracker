"""Add daily-driver user preferences.

Revision ID: 20260717_0028
Revises: 20260716_0027
"""
from alembic import op
import sqlalchemy as sa


revision = "20260717_0028"
down_revision = "20260716_0027"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("display_name", sa.String(100), nullable=True))
        batch_op.add_column(sa.Column("timezone", sa.String(64), nullable=True))
        batch_op.add_column(
            sa.Column("onboarding_dismissed_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("onboarding_dismissed_at")
        batch_op.drop_column("timezone")
        batch_op.drop_column("display_name")
