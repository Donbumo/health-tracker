"""Only the new additive migration boundary; historical SQLite DDL is unchanged."""
import importlib.util
from pathlib import Path
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.autogenerate import compare_metadata
from app.extensions import db


def baseline_metadata():
    baseline=sa.MetaData()
    excluded={'food_catalog_sources','food_catalog_revisions','catalog_foods','nutrients','food_nutrients','food_servings','meal_drafts','meal_logs'}
    removals={'daily_nutrition':{'authority','authority_baseline_json','nutrition_summary_json'},
        'food_products':{'nutrition_json'},'recipes':{'public_id','revision','nutrition_snapshot_json'},
        'recipe_ingredients':{'nutrition_snapshot_json'}}
    for table in db.metadata.sorted_tables:
        if table.name in excluded: continue
        copied=table.to_metadata(baseline)
        for column in removals.get(copied.name,[]):
            for constraint in list(copied.constraints):
                if column in getattr(constraint,'columns',{}): copied.constraints.remove(constraint)
            copied._columns.remove(copied.c[column])
    return baseline


def test_additive_upgrade_downgrade_preserves_legacy_sqlite(app,tmp_path):
    engine=sa.create_engine('sqlite:///'+(tmp_path/'migration-qa.sqlite').as_posix())
    baseline=baseline_metadata();baseline.create_all(engine)
    path=Path(__file__).resolve().parents[1]/'migrations/versions/20261009_0044_nutrition_intelligence.py'
    spec=importlib.util.spec_from_file_location('nutrition_migration',path)
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    with engine.begin() as connection:
        connection.execute(baseline.tables['users'].insert().values(id=1,username='QA migration fictitious',password_hash='QA fictional hash only',role='user'))
        connection.execute(baseline.tables['recipes'].insert().values(id=1,user_id=1,name='QA legacy recipe'))
        connection.execute(baseline.tables['daily_nutrition'].insert().values(id=1,user_id=1,date=__import__('datetime').date(2026,10,1),source='qa',calories=Decimal('1234.567')))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        assert not compare_metadata(MigrationContext.configure(connection),db.metadata)
        recipe=connection.execute(sa.text('SELECT name, public_id, revision FROM recipes WHERE id=1')).one()
        assert recipe.name=='QA legacy recipe' and len(recipe.public_id)==36 and recipe.revision==1
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert connection.execute(sa.text('SELECT calories FROM daily_nutrition WHERE id=1')).scalar()==1234.567
        assert 'meal_logs' not in sa.inspect(connection).get_table_names()
        assert connection.execute(sa.text('SELECT name FROM recipes WHERE id=1')).scalar()=='QA legacy recipe'
    engine.dispose()


from decimal import Decimal
