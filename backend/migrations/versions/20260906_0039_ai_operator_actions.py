"""Allow domain-owned generic AI action drafts.

Revision ID: 20260906_0039
Revises: 20260811_0038
Create Date: 2026-09-06
"""

from alembic import op


revision = "20260906_0039"
down_revision = "20260811_0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ai_action_drafts") as batch:
        batch.drop_constraint("ck_ai_action_drafts_type", type_="check")
        batch.create_check_constraint(
            "ck_ai_action_drafts_type",
            "draft_type IN ('food_entry','body_measurement','workout_entry','steps_entry','capability_action')",
        )


def downgrade() -> None:
    with op.batch_alter_table("ai_action_drafts") as batch:
        batch.drop_constraint("ck_ai_action_drafts_type", type_="check")
        batch.create_check_constraint(
            "ck_ai_action_drafts_type",
            "draft_type IN ('food_entry','body_measurement','workout_entry','steps_entry')",
        )
