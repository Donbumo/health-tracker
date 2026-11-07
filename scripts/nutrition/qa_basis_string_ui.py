"""Local fictional UI only; all source data and accounts are invented."""
import os,json
from pathlib import Path
from decimal import Decimal
from flask_login import current_user,login_required
from qa_pending_basis_ui import app,db,User,NutritionImportDraft,MealLog,FoodProduct,NutritionImportReceipt
from app.models import UploadedFile
from app.services import nutrition_import_review as review
from qa_basis_string_fixtures import source14,SCENARIOS

folder=Path(os.environ['QA_STRING_FIXTURES_DIR']);folder.mkdir(parents=True,exist_ok=True)
for scenario in SCENARIOS:
    (folder/('string-'+scenario+'.json')).write_text(json.dumps(source14(scenario)),encoding='utf-8')
with app.app_context():
    for scenario in SCENARIOS:
        for screen in ['desktop','mobile']:
            user=User(username='qa-string14-'+scenario+'-'+screen,role='user',display_name='QA fictional strings only')
            user.set_password('fictional-preview-ui-password');db.session.add(user)
    db.session.commit()


@app.get('/qa/string-basis-state')
@login_required
def string_basis_state():
    uid=current_user.id
    row=db.session.scalar(db.select(NutritionImportDraft).where(NutritionImportDraft.user_id==uid).order_by(NutritionImportDraft.id.desc()))
    result=dict(logs=db.session.query(MealLog).filter_by(user_id=uid).count(),
        products=db.session.query(FoodProduct).filter_by(user_id=uid).count(),receipts=db.session.query(NutritionImportReceipt).filter_by(user_id=uid).count(),
        uploads=db.session.query(UploadedFile).filter_by(user_id=uid).count(),drafts=int(row is not None))
    if row:
        view=review.overview(row);entries=source14(current_user.username.split('-')[2])['data']['entries'];exact=True
        for key,value in view['batch_summary'].items():
            numbers=[Decimal(entries[r['index']]['declaration']['nutrients'][key]['value'])
                for r in view['records'] if r['preview'] and entries[r['index']]['declaration']['nutrients'][key]['state']=='known']
            expected=sum(numbers,Decimal(0)) if numbers else None
            exact=exact and (Decimal(value['value']) if value['value'] is not None else None)==expected
        result.update(counts=view['counts'],groupable=view['declared_basis_count'],summary=view['batch_summary'],
            groups=len(view['groups']),all_totals_exact=exact,actions=row.source_json.get('semantic_actions',[]))
    return result


if __name__=='__main__':app.run(host='127.0.0.1',port=8042,debug=False,use_reloader=False,load_dotenv=False)
