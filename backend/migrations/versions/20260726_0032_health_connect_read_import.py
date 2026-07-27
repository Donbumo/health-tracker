"""Add Health Connect provenance and idempotent client identities.

Revision ID: 20260726_0032
Revises: 20260726_0031
"""

from alembic import op
import sqlalchemy as sa


revision = "20260726_0032"
down_revision = "20260726_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("weigh_ins") as batch_op:
        batch_op.add_column(sa.Column("client_event_id", sa.String(length=36), nullable=True))
        batch_op.drop_constraint("uq_weigh_ins_user_recorded_at", type_="unique")
        batch_op.create_unique_constraint(
            "uq_weigh_ins_user_recorded_source", ["user_id", "recorded_at", "source"]
        )
        batch_op.create_unique_constraint(
            "uq_weigh_ins_user_client_event", ["user_id", "client_event_id"]
        )

    with op.batch_alter_table("daily_energy") as batch_op:
        batch_op.add_column(sa.Column("client_event_id", sa.String(length=36), nullable=True))
        batch_op.create_unique_constraint(
            "uq_daily_energy_user_client_event", ["user_id", "client_event_id"]
        )

    with op.batch_alter_table("nutrition_items") as batch_op:
        batch_op.add_column(
            sa.Column("source", sa.String(length=32), nullable=False, server_default="manual")
        )
        batch_op.add_column(sa.Column("client_event_id", sa.String(length=36), nullable=True))
        batch_op.create_unique_constraint(
            "uq_nutrition_items_user_client_event", ["user_id", "client_event_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("nutrition_items") as batch_op:
        batch_op.drop_constraint("uq_nutrition_items_user_client_event", type_="unique")
        batch_op.drop_column("client_event_id")
        batch_op.drop_column("source")

    with op.batch_alter_table("daily_energy") as batch_op:
        batch_op.drop_constraint("uq_daily_energy_user_client_event", type_="unique")
        batch_op.drop_column("client_event_id")

    connection = op.get_bind()
    duplicate = connection.execute(
        sa.text(
            "SELECT user_id, recorded_at FROM weigh_ins "
            "GROUP BY user_id, recorded_at HAVING COUNT(*) > 1"
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "Cannot downgrade while manual and Health Connect weights coexist at one instant."
        )
    with op.batch_alter_table("weigh_ins") as batch_op:
        batch_op.drop_constraint("uq_weigh_ins_user_client_event", type_="unique")
        batch_op.drop_constraint("uq_weigh_ins_user_recorded_source", type_="unique")
        batch_op.create_unique_constraint(
            "uq_weigh_ins_user_recorded_at", ["user_id", "recorded_at"]
        )
        batch_op.drop_column("client_event_id")
