"""Make companion profile deletion cascade to its deliveries safely.

Revision ID: 20260714_0025
Revises: 20260714_0024
"""
from alembic import op
import sqlalchemy as sa


revision = "20260714_0025"
down_revision = "20260714_0024"
branch_labels = None
depends_on = None


_SQLITE_NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}


def _profile_fk_name():
    bind = op.get_bind()
    foreign_keys = sa.inspect(bind).get_foreign_keys(
        "companion_workout_deliveries"
    )
    for foreign_key in foreign_keys:
        if foreign_key.get("constrained_columns") == ["profile_id"]:
            if foreign_key.get("name"):
                return foreign_key["name"]
            if bind.dialect.name == "sqlite":
                return (
                    "fk_companion_workout_deliveries_profile_id_"
                    "companion_device_profiles"
                )
    raise RuntimeError("companion profile foreign key was not found")


def _batch_kwargs():
    if op.get_bind().dialect.name == "sqlite":
        return {"naming_convention": _SQLITE_NAMING_CONVENTION}
    return {}


def upgrade():
    old_name = _profile_fk_name()
    with op.batch_alter_table(
        "companion_workout_deliveries", **_batch_kwargs()
    ) as batch_op:
        batch_op.drop_constraint(old_name, type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_companion_deliveries_profile",
            "companion_device_profiles",
            ["profile_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade():
    with op.batch_alter_table(
        "companion_workout_deliveries", **_batch_kwargs()
    ) as batch_op:
        batch_op.drop_constraint(
            "fk_companion_deliveries_profile", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            "fk_companion_deliveries_profile_restrict",
            "companion_device_profiles",
            ["profile_id"],
            ["id"],
            ondelete="RESTRICT",
        )
