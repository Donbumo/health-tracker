"""Add canonical daily registry without changing any source/mobile identity.

All original rows, values, revisions, uploads and payloads remain in place.
Duplicates become evidence of a single registered day, never summed/removed.
Conflicting values are unknown until reviewed through explicit day editing.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261018_0046"
down_revision = "20261013_0045"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("daily_energy", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("daily_energy", sa.Column("source_file_sha256", sa.String(64), nullable=True))
    op.execute(sa.text("UPDATE daily_energy SET source_file_sha256=(SELECT sha256 FROM uploaded_files WHERE uploaded_files.id=daily_energy.source_file_id AND uploaded_files.user_id=daily_energy.user_id) WHERE source_file_id IS NOT NULL"))
    op.create_table(
        "energy_days",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("resolutions_json", sa.JSON(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "date", name="uq_energy_day_user_date"),
        sa.CheckConstraint("revision >= 1", name="ck_energy_day_revision"),
    )
    op.create_table(
        "energy_evidence_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("evidence_public_id", sa.String(36), nullable=False),
        sa.Column("event_key", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("source_file_id", sa.Integer(), sa.ForeignKey("uploaded_files.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_file_sha256", sa.String(64), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.UniqueConstraint("user_id", "event_key", name="uq_energy_event_owner_key"),
    )
    op.create_index("ix_energy_event_owner_date", "energy_evidence_events", ["user_id", "date"])
    op.execute(sa.text("INSERT INTO energy_days (user_id, date, revision) SELECT user_id, date, 1 FROM daily_energy GROUP BY user_id, date"))


def downgrade():
    # New source tombstones and explicit resolutions cannot be represented by
    # 0045. Even apparently empty days may carry recovery evidence. No data loss.
    raise RuntimeError("0046 preserves source identities and review decisions; use a compatible image/functional rollback, never destructive downgrade")
