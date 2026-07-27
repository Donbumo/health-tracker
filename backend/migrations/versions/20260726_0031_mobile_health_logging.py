"""Add public mobile identities and revisions to existing health domains.

Revision ID: 20260726_0031
Revises: 20260724_0030
"""
import uuid

from alembic import op
import sqlalchemy as sa


revision = "20260726_0031"
down_revision = "20260724_0030"
branch_labels = None
depends_on = None


RESOURCE_TABLES = ("weigh_ins", "daily_energy", "nutrition_items", "food_products")


def _add_identity(table_name: str) -> None:
    op.add_column(table_name, sa.Column("public_id", sa.String(length=36), nullable=True))
    op.add_column(
        table_name,
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    connection = op.get_bind()
    ids = connection.execute(sa.text(f"SELECT id FROM {table_name}")).scalars()
    for record_id in ids:
        connection.execute(
            sa.text(f"UPDATE {table_name} SET public_id=:public_id WHERE id=:record_id"),
            {"public_id": str(uuid.uuid4()), "record_id": record_id},
        )


def upgrade() -> None:
    for table_name in RESOURCE_TABLES:
        _add_identity(table_name)

    op.add_column(
        "nutrition_items",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "nutrition_items",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.execute(
        sa.text(
            "UPDATE nutrition_items SET created_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP"
        )
    )
    with op.batch_alter_table("nutrition_items") as batch_op:
        batch_op.alter_column(
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        )
        batch_op.alter_column(
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        )

    constraint_names = {
        "weigh_ins": ("uq_weigh_ins_public_id", "ck_weigh_ins_revision"),
        "daily_energy": ("uq_daily_energy_public_id", "ck_daily_energy_revision"),
        "nutrition_items": ("uq_nutrition_items_public_id", "ck_nutrition_items_revision"),
        "food_products": ("uq_food_products_public_id", "ck_food_products_revision"),
    }
    for table_name, (unique_name, check_name) in constraint_names.items():
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column("public_id", existing_type=sa.String(length=36), nullable=False)
            batch_op.create_unique_constraint(unique_name, ["public_id"])
            batch_op.create_check_constraint(check_name, "revision >= 1")

    with op.batch_alter_table("daily_energy") as batch_op:
        batch_op.drop_constraint("uq_daily_energy_user_date", type_="unique")
        batch_op.create_unique_constraint(
            "uq_daily_energy_user_date_source", ["user_id", "date", "source"]
        )


def downgrade() -> None:
    connection = op.get_bind()
    duplicate = connection.execute(
        sa.text(
            "SELECT user_id, date FROM daily_energy "
            "GROUP BY user_id, date HAVING COUNT(*) > 1"
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "Cannot downgrade while multiple daily_energy sources coexist for one day."
        )
    with op.batch_alter_table("daily_energy") as batch_op:
        batch_op.drop_constraint("uq_daily_energy_user_date_source", type_="unique")
        batch_op.create_unique_constraint("uq_daily_energy_user_date", ["user_id", "date"])

    constraint_names = {
        "weigh_ins": ("uq_weigh_ins_public_id", "ck_weigh_ins_revision"),
        "daily_energy": ("uq_daily_energy_public_id", "ck_daily_energy_revision"),
        "nutrition_items": ("uq_nutrition_items_public_id", "ck_nutrition_items_revision"),
        "food_products": ("uq_food_products_public_id", "ck_food_products_revision"),
    }
    for table_name, (unique_name, check_name) in constraint_names.items():
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_constraint(check_name, type_="check")
            batch_op.drop_constraint(unique_name, type_="unique")
            batch_op.drop_column("revision")
            batch_op.drop_column("public_id")
    with op.batch_alter_table("nutrition_items") as batch_op:
        batch_op.drop_column("updated_at")
        batch_op.drop_column("created_at")
