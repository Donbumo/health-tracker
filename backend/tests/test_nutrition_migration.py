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
    excluded={'food_catalog_sources','food_catalog_revisions','catalog_foods','nutrients','food_nutrients','food_servings','meal_drafts','meal_logs','nutrition_import_drafts','nutrition_plans','nutrition_import_receipts'}
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


def test_additive_0045_upgrade_safe_rollback_preserves_0044_sqlite(app,tmp_path):
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
        path45=path.with_name('20261013_0045_nutrition_experience_import.py')
        spec45=importlib.util.spec_from_file_location('nutrition_migration45',path45)
        migration45=importlib.util.module_from_spec(spec45);spec45.loader.exec_module(migration45)
        with Operations.context(MigrationContext.configure(connection)):
            migration45.upgrade()
        assert not compare_metadata(MigrationContext.configure(connection),db.metadata)
        recipe=connection.execute(sa.text('SELECT name, public_id, revision FROM recipes WHERE id=1')).one()
        assert recipe.name=='QA legacy recipe' and len(recipe.public_id)==36 and recipe.revision==1
        with Operations.context(MigrationContext.configure(connection)):
            migration45.downgrade()
        assert connection.execute(sa.text('SELECT calories FROM daily_nutrition WHERE id=1')).scalar()==1234.567
        assert 'meal_logs' in sa.inspect(connection).get_table_names()
        assert 'nutrition_plans' not in sa.inspect(connection).get_table_names()
        assert connection.execute(sa.text('SELECT name FROM recipes WHERE id=1')).scalar()=='QA legacy recipe'
    engine.dispose()


def test_0045_downgrade_refuses_private_records_before_ddl(app):
    import pytest
    from app.models import User,NutritionPlan
    owner=User(username='QA-rollback-boundary',password_hash='QA fictional',role='user')
    db.session.add(owner);db.session.flush()
    db.session.add(NutritionPlan(user_id=owner.id,name='QA private plan',snapshot_json={'QA':'fictional'}));db.session.commit()
    path=Path(__file__).resolve().parents[1]/'migrations/versions/20261013_0045_nutrition_experience_import.py'
    spec=importlib.util.spec_from_file_location('nutrition_migration45_guard',path)
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    with Operations.context(MigrationContext.configure(db.session.connection())):
        with pytest.raises(RuntimeError,match='private records exist'):migration.downgrade()
    assert 'nutrition_plans' in sa.inspect(db.session.connection()).get_table_names()


from decimal import Decimal
