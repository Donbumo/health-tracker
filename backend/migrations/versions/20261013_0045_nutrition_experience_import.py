"""Add private nutrition plans/review receipts and expanded catalog search.

No legacy domain rows or consumed snapshots are recalculated. Never downgrades
0044. A rollback of this revision refuses to delete any new private records.
"""
import json
import unicodedata
from alembic import op
import sqlalchemy as sa

revision = '20261013_0045'
down_revision = '20261009_0044'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('catalog_foods') as batch:
        batch.add_column(sa.Column('search_text', sa.Text(), nullable=True))
        batch.add_column(sa.Column('brand', sa.String(200), nullable=True))
        batch.add_column(sa.Column('barcode', sa.String(32), nullable=True))
        batch.add_column(sa.Column('food_type', sa.String(64), nullable=True))
        batch.add_column(sa.Column('preparation_state', sa.String(16), nullable=True))
        batch.create_index('ix_catalog_food_barcode', ['catalog_revision_id', 'barcode'])
    table = sa.table('catalog_foods', sa.column('id', sa.Integer()), sa.column('snapshot_json', sa.JSON()),
                     sa.column('search_text', sa.Text()), sa.column('brand', sa.String(200)),
                     sa.column('barcode', sa.String(32)), sa.column('food_type', sa.String(64)),
                     sa.column('preparation_state', sa.String(16)))
    connection = op.get_bind()
    for row in connection.execute(sa.select(table.c.id, table.c.snapshot_json)):
        food = json.loads(row.snapshot_json) if isinstance(row.snapshot_json, str) else row.snapshot_json
        metadata = food.get('metadata') or {}
        text = ' '.join([food.get('name', ''), food.get('preparation', ''), food.get('source_name', ''),
                         *metadata.get('aliases', []), metadata.get('brand') or '', metadata.get('barcode') or ''])
        text = ''.join(c for c in unicodedata.normalize('NFKD', text).casefold() if not unicodedata.combining(c))
        connection.execute(table.update().where(table.c.id == row.id).values(search_text=text,
            **{key:metadata.get(key) for key in ['brand','barcode','food_type','preparation_state']}))
    op.create_table('nutrition_import_drafts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('public_id', sa.String(36), nullable=False, unique=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('state', sa.String(16), nullable=False),
        sa.Column('source_sha256', sa.String(64), nullable=False),
        sa.Column('source_json', sa.JSON(), nullable=False),
        sa.Column('review_json', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_nutrition_import_owner_state', 'nutrition_import_drafts', ['user_id', 'state'])
    op.create_table('nutrition_plans',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('public_id', sa.String(36), nullable=False, unique=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('snapshot_json', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_nutrition_plan_owner', 'nutrition_plans', ['user_id', 'is_active'])
    op.create_table('nutrition_import_receipts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('public_id', sa.String(36), nullable=False, unique=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('event_key', sa.String(64), nullable=False),
        sa.Column('source_sha256', sa.String(64), nullable=False),
        sa.Column('raw_payload_json', sa.JSON(), nullable=False),
        sa.Column('result_json', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('user_id', 'event_key', name='uq_nutrition_import_event'))


def downgrade():
    connection = op.get_bind()
    for name in ('nutrition_plans', 'nutrition_import_receipts', 'nutrition_import_drafts'):
        if connection.execute(sa.text(f'SELECT COUNT(*) FROM {name}')).scalar():
            raise RuntimeError('Nutrition 2.1 private records exist; use functional rollback, not destructive downgrade.')
    for name in ('nutrition_import_receipts', 'nutrition_plans', 'nutrition_import_drafts'):
        op.drop_table(name)
    with op.batch_alter_table('catalog_foods') as batch:
        batch.drop_index('ix_catalog_food_barcode')
        for name in ('search_text','brand','barcode','food_type','preparation_state'):
            batch.drop_column(name)
