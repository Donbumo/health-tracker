"""Add planned workouts and mobile synchronization state.

Revision ID: 20260714_0023
Revises: 20260713_0022
"""
from datetime import datetime, timezone
import uuid

from alembic import op
import sqlalchemy as sa


revision = "20260714_0023"
down_revision = "20260713_0022"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "planned_workouts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("training_plan_id", sa.Integer(), sa.ForeignKey("training_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("training_plan_version_id", sa.Integer(), sa.ForeignKey("training_plan_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scheduled_for_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), server_default="planned", nullable=False),
        sa.Column("title_snapshot", sa.String(200), nullable=False),
        sa.Column("payload_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("last_modified_by_device_id", sa.Integer(), sa.ForeignKey("api_devices.id", ondelete="SET NULL")),
        sa.CheckConstraint("status IN ('planned', 'in_progress', 'completed', 'skipped', 'cancelled')", name="ck_planned_workouts_status"),
        sa.CheckConstraint("revision >= 1", name="ck_planned_workouts_revision"),
        sa.UniqueConstraint("public_id", name="uq_planned_workouts_public_id"),
    )
    op.create_index("ix_planned_workouts_user_schedule", "planned_workouts", ["user_id", "scheduled_for_date", "status"])

    with op.batch_alter_table("training_sessions") as batch_op:
        batch_op.add_column(sa.Column("public_id", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("planned_workout_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("source_device_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("client_event_id", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("client_payload_sha256", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("revision", sa.Integer(), server_default="1", nullable=False))
        batch_op.add_column(sa.Column("timezone", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False))
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key("fk_training_sessions_planned_workout", "planned_workouts", ["planned_workout_id"], ["id"], ondelete="SET NULL")
        batch_op.create_foreign_key("fk_training_sessions_source_device", "api_devices", ["source_device_id"], ["id"], ondelete="SET NULL")
        batch_op.create_unique_constraint("uq_training_sessions_public_id", ["public_id"])
        batch_op.create_unique_constraint("uq_training_sessions_device_event", ["user_id", "source_device_id", "client_event_id"])
        batch_op.create_unique_constraint("uq_training_sessions_planned_workout", ["planned_workout_id"])
        batch_op.create_check_constraint("ck_training_sessions_revision", "revision >= 1")
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id FROM training_sessions WHERE public_id IS NULL")).fetchall()
    for row in rows:
        connection.execute(
            sa.text("UPDATE training_sessions SET public_id = :public_id WHERE id = :id"),
            {"public_id": str(uuid.uuid4()), "id": row.id},
        )
    with op.batch_alter_table("training_sessions") as batch_op:
        batch_op.alter_column("public_id", existing_type=sa.String(36), nullable=False)

    op.create_table(
        "sync_changes",
        sa.Column("sequence", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_type", sa.String(40), nullable=False),
        sa.Column("entity_public_id", sa.String(36), nullable=False),
        sa.Column("operation", sa.String(10), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("changed_by_device_id", sa.Integer(), sa.ForeignKey("api_devices.id", ondelete="SET NULL")),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.JSON()),
        sa.CheckConstraint("operation IN ('upsert', 'delete')", name="ck_sync_changes_operation"),
        sa.CheckConstraint("revision >= 1", name="ck_sync_changes_revision"),
    )
    op.create_index("ix_sync_changes_user_sequence", "sync_changes", ["user_id", "sequence"])
    op.create_index("ix_sync_changes_user_entity", "sync_changes", ["user_id", "entity_type", "entity_public_id"])

    op.create_table(
        "device_sync_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("api_devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("last_pull_sequence", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_push_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.UniqueConstraint("user_id", "device_id", name="uq_device_sync_user_device"),
        sa.CheckConstraint("last_pull_sequence >= 0", name="ck_device_sync_last_pull_sequence"),
    )

    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("api_devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("operation", sa.String(80), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response_status", sa.Integer()),
        sa.Column("response_body_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "device_id", "key_hash", name="uq_idempotency_user_device_key"),
    )
    op.create_index("ix_idempotency_expires", "idempotency_records", ["expires_at"])


def downgrade():
    op.drop_table("idempotency_records")
    op.drop_table("device_sync_states")
    op.drop_table("sync_changes")
    with op.batch_alter_table("training_sessions") as batch_op:
        batch_op.drop_constraint("ck_training_sessions_revision", type_="check")
        batch_op.drop_constraint("uq_training_sessions_planned_workout", type_="unique")
        batch_op.drop_constraint("uq_training_sessions_device_event", type_="unique")
        batch_op.drop_constraint("uq_training_sessions_public_id", type_="unique")
        batch_op.drop_constraint("fk_training_sessions_source_device", type_="foreignkey")
        batch_op.drop_constraint("fk_training_sessions_planned_workout", type_="foreignkey")
        for column in (
            "deleted_at", "updated_at", "completed_at", "started_at", "timezone",
            "revision", "client_payload_sha256", "client_event_id",
            "source_device_id", "planned_workout_id", "public_id",
        ):
            batch_op.drop_column(column)
    op.drop_table("planned_workouts")
