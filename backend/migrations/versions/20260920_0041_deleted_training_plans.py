"""Keep historical plan references after removal from planning."""
from alembic import op
import sqlalchemy as sa

revision = '20260920_0041'
down_revision = '20260913_0040'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('training_plans', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    # Never silently resurrect deleted routines on downgrade.
    if op.get_bind().execute(sa.text('SELECT COUNT(*) FROM training_plans WHERE deleted_at IS NOT NULL')).scalar():
        raise RuntimeError('Deleted historical routines exist; downgrade would resurrect them.')
    op.drop_column('training_plans', 'deleted_at')
