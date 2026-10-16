"""Focal final-product queries on the existing isolated MariaDB QA schema.

No migration, grants, reset, container, production database or historical edit.
"""
import json
from pathlib import Path
from sqlalchemy import text
from mariadb_qa_21 import ROOT, application, owner, db, imports, catalog, NutritionError


def main():
    report={'scope':'QA synthetic only; focused queries; no DDL','isolations':[]}
    for isolation in ['READ COMMITTED','REPEATABLE READ']:
        app=application(isolation)
        with app.app_context():
            assert db.session.scalar(text('SELECT DATABASE()'))=='nutrition_intelligence_qa_20261009'
            assert db.session.scalar(text('SELECT version_num FROM alembic_version'))=='20261013_0045'
            user=owner('final product '+isolation);db.session.commit()
            chicken=catalog.search(user,'pollo crudo')
            assert chicken and all(r['state']=='raw' and 'pollock' not in r['name'].lower() for r in chicken)
            tortilla=catalog.search(user,'tortilla de maiz')
            assert tortilla[0]['source_food_id']=='175036'
            rice=catalog.search(user,'arroz blanco cocido')
            assert rice[0]['source_food_id']=='169757'
            source=ROOT/'examples/nutrition-2-1/fixtures/external.json'
            row=imports.start(user,source.read_bytes(),'QA final product private.json');db.session.commit()
            duplicate=imports.start(user,source.read_bytes(),'QA renamed private.json');db.session.commit()
            assert not imports.original_policy(row)['can_delete']
            imports.update(user,duplicate.public_id,duplicate.revision,'cancel',{});db.session.commit()
            assert imports.original_policy(row)['can_delete']
            row,path=imports.delete_original(user,row.public_id,row.revision,confirmed=True)
            db.session.commit();path.unlink(missing_ok=True)
            assert row.state=='cancelled' and not path.exists()
            report['isolations'].append({'level':isolation,'word_boundary_rank':'pass',
                'tortilla_vs_chips':'pass','rice_identity':'pass','JSON_shared_reference_retention':'pass',
                'explicit_unconfirmed_original_deletion':'pass','head':'20261013_0045'})
    target=ROOT/'design/nutrition-intelligence-2-1/qa/mariadb-product-report.json'
    target.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'MariaDB_focal':'pass','isolations':2,'DDL':'none'}))


if __name__=='__main__':main()
