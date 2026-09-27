"""Local external reference catalog; preserve owner identities and history."""
from alembic import op
import sqlalchemy as sa

revision = "20260927_0042"
down_revision = "20260920_0041"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("exercise_catalog_sources",
        sa.Column("source_id", sa.String(64), primary_key=True),
        sa.Column("active_snapshot", sa.String(64)),
        sa.Column("previous_snapshot", sa.String(64)),
        sa.Column("manifest", sa.JSON(), nullable=False))
    op.create_table("external_exercises",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(36), nullable=False, unique=True),
        sa.Column("source", sa.String(64), sa.ForeignKey("exercise_catalog_sources.source_id"), nullable=False),
        sa.Column("external_id", sa.String(200, collation="utf8mb4_bin").with_variant(sa.String(200), "sqlite"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("normalized_name", sa.String(255), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("media", sa.JSON(), nullable=False),
        sa.UniqueConstraint("source", "external_id", name="uq_external_exercise_source_id"))
    op.create_index("ix_external_exercises_normalized_name", "external_exercises", ["normalized_name"])
    with op.batch_alter_table("exercises") as batch:
        batch.add_column(sa.Column("external_catalog_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_exercises_external_catalog", "external_exercises", ["external_catalog_id"], ["id"])


def downgrade():
    with op.batch_alter_table("exercises") as batch:
        batch.drop_constraint("fk_exercises_external_catalog", type_="foreignkey")
        batch.drop_column("external_catalog_id")
    op.drop_table("external_exercises")
    op.drop_table("exercise_catalog_sources")
