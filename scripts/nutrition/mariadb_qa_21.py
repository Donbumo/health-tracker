"""Additive 0044→0045 QA on the existing, explicitly reserved local schema.

No containers, schema resets, 0044 downgrades or personal database access.
Each run adds only new fictional QA owners; existing QA snapshots stay intact.
"""
import copy
import importlib.util
import json
from uuid import uuid4
from pathlib import Path
from sqlalchemy import text,inspect
from flask_migrate import upgrade,check
from alembic.operations import Operations
from alembic.migration import MigrationContext
from mariadb_qa import ROOT,application as base_application,race,db,ni,catalog,date,Decimal,NutritionError
from app.models import User,MealLog,NutritionPlan,NutritionImportReceipt,DailyNutrition
from app.services import nutrition_import as imports
from app.services.importers.standard_import_executor import StandardImportExecutor
from app.services.nutrition_portability import export_bundle,semantic_snapshot
from app.services.account_restore import AccountRestoreService
from app.services.exporters.user_data import build_user_data_document
from app.services.backups import AccountBackupService,BackupRestoreCoordinator
from tests.test_full_backup import _stage


def application(level):
    app=base_application(level)
    root=Path(app.config['DATA_ROOT'])
    app.config.update(UPLOAD_ROOT=root/'uploads/raw',GENERATED_UPLOAD_ROOT=root/'uploads/generated')
    return app


def owner(label):
    row=User(username='QA synthetic 21 '+label+' '+uuid4().hex,role='user',timezone='UTC');row.set_password('QA fictional password only')
    db.session.add(row);db.session.commit();return row.id


def document(user,ref,destination='consumed',nonce=None):
    path=ROOT/'examples/nutrition-2-1/fixtures/compound-macros.json'
    row=imports.start(user,path.read_bytes(),path.name)
    review=copy.deepcopy(row.review_json);review['destination']=destination
    review['rows'][0].update(confirmed=True,ingredients=[{'ref':ref,'food_revision':catalog.detail(user,ref)['revision'],'amount':'220','unit':'g'}])
    row.review_json=review;db.session.commit();doc=imports.canonical(row)
    if nonce:doc['data']['event_key']=ni.hash_document({'QA_explicit_new_file_event':nonce})
    return doc


def commit(doc,user):return StandardImportExecutor().commit_documents([doc],user_id=user,target_type='nutrition_import',confirmed=True)


def run():
    report={'data':'QA synthetic only','schema':'nutrition_intelligence_qa_20261009','isolations':[]}
    with application('READ COMMITTED').app_context():
        with db.engine.connect() as connection:
            assert connection.execute(text('SELECT DATABASE()')).scalar()=='nutrition_intelligence_qa_20261009'
            assert connection.execute(text('SELECT CURRENT_USER()')).scalar().startswith('progression_qa@')
            head=connection.execute(text('SELECT version_num FROM alembic_version')).scalar()
            assert head in {'20261009_0044','20261013_0045'}
        before={row.id:ni.hash_document(row.snapshot_json) for row in db.session.execute(db.select(MealLog)).scalars()};db.session.rollback()
        upgrade(directory=str(ROOT/'backend/migrations'));check(directory=str(ROOT/'backend/migrations'))
        upgrade(directory=str(ROOT/'backend/migrations'))
        assert db.session.execute(text('SELECT version_num FROM alembic_version')).scalar()=='20261013_0045'
        assert all(ni.hash_document(db.session.get(MealLog,key).snapshot_json)==sha for key,sha in before.items())
        report['migration']={'from':head,'head':'20261013_0045','db_check':'pass','repeated_upgrade':'no-op','existing_QA_snapshots_preserved':len(before)}
        indexed=inspect(db.engine).get_indexes('catalog_foods');assert any(i['name']=='ix_catalog_food_barcode' for i in indexed)
        report['catalog']=[]
        for path in sorted((ROOT/'examples/catalog/nutrition-2-1').glob('*.json')):
            if path.name=='manifest.json':continue
            doc=json.loads(path.read_bytes());catalog.stage(doc)
            from app.models.nutrition_intelligence import FoodCatalogSource
            source=db.session.get(FoodCatalogSource,doc['source'])
            if source.active_revision!=doc['revision']:catalog.activate(source.id,doc['revision'],source.revision)
            db.session.commit();report['catalog'].append({'source':doc['source'],'foods':len(doc['foods'])})
    for level in ('READ COMMITTED','REPEATABLE READ'):
        app=application(level)
        with app.app_context():
            assert db.session.execute(text('SELECT @@tx_isolation')).scalar().replace('-',' ')==level
            user=owner(level);ref=next(r['ref'] for r in catalog.search(user,'chicken breast cooked',source='usda_sr_legacy') if r['state']=='cooked')
            doc=document(user,ref);db.session.commit()
        results=race(app,user,[lambda:commit(doc,user),lambda:commit(doc,user)])
        with app.app_context():
            assert all(r['ok'] and r['result']['committed'] for r in results),results
            assert db.session.query(MealLog).filter_by(user_id=user).count()==1
            assert db.session.query(NutritionImportReceipt).filter_by(user_id=user).count()==1
            log=db.session.query(MealLog).filter_by(user_id=user).one();frozen=copy.deepcopy(log.snapshot_json)
            assert Decimal(ni.daily_summary(user,date(2026,10,5))['summary']['energy']['value'])==450
            assert log.snapshot_json['summary']['iron']['state']=='partial'
            changed=copy.deepcopy(doc);changed['data']['entries'][0]['name']='QA changed identity'
            assert StandardImportExecutor().plan_documents([changed],user_id=user,target_type='nutrition_import')['conflicts']==1
            plan_doc=document(user,ref,'plan','QA plan '+level);assert commit(plan_doc,user)['committed']
            plan=db.session.query(NutritionPlan).filter_by(user_id=user).one()
            editing=imports.edit_plan(user,plan.public_id);db.session.commit()
            assert ni.owned_log(user,log.public_id).snapshot_json==frozen
            try:imports.owned(user+100000,editing.public_id)
            except NutritionError as error:assert error.status==404
            else:raise AssertionError('Owner isolation failed')
            exported=build_user_data_document(db.session.get(User,user),user)
            recipient=owner('restore '+level);service=AccountRestoreService();preview=service.preview(exported,user_id=recipient)
            assert service.commit(exported,user_id=recipient,confirmation_token=preview['confirmation_token'])['committed']
            restored=export_bundle(recipient)
            assert semantic_snapshot(restored['logs'][0]['snapshot'])==semantic_snapshot(frozen)
            assert len(restored['plans'])==1 and len(restored['receipts'])==2
            backup=AccountBackupService();archive=backup.create(db.session.get(User,user),user_id=user)
            target=owner('zip '+level);coordinator=BackupRestoreCoordinator();staging=_stage(backup.resolve_download(archive,user_id=user),coordinator,target)
            preview=coordinator.preview(staging_id=staging,user_id=target)
            assert coordinator.confirm(staging_id=staging,user_id=target,confirmation_token=preview['confirmation_token'])['committed']
            assert len(export_bundle(target)['plans'])==1
            path=ROOT/'backend/migrations/versions/20261013_0045_nutrition_experience_import.py'
            spec=importlib.util.spec_from_file_location('qa45guard',path);migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
            with Operations.context(MigrationContext.configure(db.session.connection())):
                try:migration.downgrade()
                except RuntimeError as error:assert 'private records exist' in str(error)
                else:raise AssertionError('Unsafe 0045 rollback was allowed')
            db.session.rollback()
            app.config['NUTRITION_INTELLIGENCE_ENABLED']=False
            assert ni.owned_log(user,log.public_id).snapshot_json==frozen
            report['isolations'].append({'level':level,'concurrent_import_replay':'pass','receipts':1,'logs':1,'declared_450_not_double_counted':'pass',
                'changed_event_conflict':'pass','owner_only':'pass','plan_not_consumed':'pass','JSON_restore':'pass','ZIP_restore':'pass','0045_destructive_rollback_blocked':'pass','flag_off_history':'pass'})
    out=ROOT/'design/nutrition-intelligence-2-1/qa';out.mkdir(parents=True,exist_ok=True)
    (out/'mariadb-report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':run()
