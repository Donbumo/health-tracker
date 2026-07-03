"""Add medical laboratory reports and results.

Revision ID: 20260705_0013
Revises: 20260704_0012
Create Date: 2026-07-05
"""

from alembic import op
import sqlalchemy as sa


revision = "20260705_0013"
down_revision = "20260704_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "medical_lab_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("laboratory_name", sa.String(length=200), nullable=True),
        sa.Column("doctor_name", sa.String(length=200), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_file_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("raw_payload_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_file_id"],
            ["uploaded_files.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_file_id",
            name="uq_medical_lab_reports_source_file",
        ),
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_medical_lab_reports_user_date",
        "medical_lab_reports",
        ["user_id", "date"],
        unique=False,
    )

    op.create_table(
        "medical_lab_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("marker_name", sa.String(length=200), nullable=False),
        sa.Column("marker_code", sa.String(length=100), nullable=True),
        sa.Column("value", sa.Numeric(20, 6), nullable=True),
        sa.Column("value_text", sa.String(length=500), nullable=True),
        sa.Column("unit", sa.String(length=100), nullable=False),
        sa.Column("reference_min", sa.Numeric(20, 6), nullable=True),
        sa.Column("reference_max", sa.Numeric(20, 6), nullable=True),
        sa.Column("reference_text", sa.String(length=500), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="unknown",
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "reference_min IS NULL OR reference_max IS NULL "
            "OR reference_min <= reference_max",
            name="ck_medical_lab_results_reference_range",
        ),
        sa.CheckConstraint(
            "status IN ('low', 'normal', 'high', 'unknown')",
            name="ck_medical_lab_results_status",
        ),
        sa.CheckConstraint(
            "value IS NOT NULL OR value_text IS NOT NULL",
            name="ck_medical_lab_results_value",
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["medical_lab_reports.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_medical_lab_results_user_marker",
        "medical_lab_results",
        ["user_id", "marker_name"],
        unique=False,
    )
    op.create_index(
        "ix_medical_lab_results_user_report",
        "medical_lab_results",
        ["user_id", "report_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_medical_lab_results_user_report",
        table_name="medical_lab_results",
    )
    op.drop_index(
        "ix_medical_lab_results_user_marker",
        table_name="medical_lab_results",
    )
    op.drop_table("medical_lab_results")
    op.drop_index(
        "ix_medical_lab_reports_user_date",
        table_name="medical_lab_reports",
    )
    op.drop_table("medical_lab_reports")
