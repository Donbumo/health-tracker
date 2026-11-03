"""Local fictional Issue #38 UI; never point at a personal database."""
import json
import os
from pathlib import Path
from decimal import Decimal
from flask_login import login_required,current_user
from qa_source_21_ui import app,db,User,MealLog,FoodProduct,NutritionImportReceipt,NutritionImportDraft
from qa_pending_basis_fixtures import source18
from app.services import nutrition_import_review as review

fixture_dir=Path(os.environ['QA_BASIS_FIXTURES_DIR']);fixture_dir.mkdir(parents=True,exist_ok=True)
for case in ['clean','conflict']:
    document=source18()
    if case=='conflict':document['data']['entries'][-1]['declaration']['provenance']['basis_interpretation']['consumed_quantity']='999'
    (fixture_dir/(case+'.json')).write_text(json.dumps(document),encoding='utf-8')
with app.app_context():
    for screen in ['desktop','mobile']:
        for case in ['clean','conflict']:
            user=User(username='qa-basis18-'+case+'-'+screen,role='user',display_name='QA fictional basis only')
            user.set_password('fictional-preview-ui-password');db.session.add(user)
    db.session.commit()


@app.get('/qa/basis18-state')
@login_required
def basis_state():
    uid=current_user.id
    row=db.session.scalar(db.select(NutritionImportDraft).where(NutritionImportDraft.user_id==uid).order_by(NutritionImportDraft.id.desc()))
    view=review.overview(row);entries=source18()['data']['entries'];exact=True
    for key,value in view['batch_summary'].items():
        values=[Decimal(entries[r['index']]['declaration']['nutrients'][key]['value']) for r in view['records'] if r['preview']]
        expected=sum(values,Decimal(0)) if values else None
        exact=exact and (Decimal(value['value']) if value['value'] is not None else None)==expected
    return dict(counts=view['counts'],groups=len(view['groups']),groupable=view['declared_basis_count'],
        summary=view['batch_summary'],all_totals_exact=exact,revision=row.revision,
        actions=row.source_json.get('semantic_actions',[]),
        logs=db.session.query(MealLog).filter_by(user_id=uid).count(),products=db.session.query(FoodProduct).filter_by(user_id=uid).count(),
        receipts=db.session.query(NutritionImportReceipt).filter_by(user_id=uid).count())


if __name__=='__main__':app.run(host='127.0.0.1',port=8042,debug=False,use_reloader=False,load_dotenv=False)
