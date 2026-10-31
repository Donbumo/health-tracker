"""Real local Flask UI with synthetic source21 cases; no production data."""
import json
from datetime import date
from decimal import Decimal
from qa_preview_ui import app,db,User,MealLog,FoodProduct,NutritionImportReceipt,NutritionImportDraft
from qa_source_21_fixtures import source21,variant
from app.services import nutrition_import_review as review,nutrition_intelligence as ni
from flask_login import login_required,current_user

with app.app_context():
    for screen in ['mobile','desktop']:
        for case in ['clean','conflict','partial']:
            user=User(username='qa-source21-'+case+'-'+screen,role='user',display_name='QA synthetic only')
            user.set_password('fictional-preview-ui-password');db.session.add(user)
    db.session.commit()

@app.get('/qa/source21-state')
@login_required
def source_state():
    uid=current_user.id
    row=db.session.scalar(db.select(NutritionImportDraft).where(NutritionImportDraft.user_id==uid).order_by(NutritionImportDraft.id.desc()))
    view=review.overview(row) if row and row.state=='pending' else None
    return dict(counts=view['counts'] if view else None,groups=len(view['groups']) if view else None,
        summary=view['batch_summary'] if view else ni.daily_summary(uid,date(2026,1,15))['summary'],
        logs=db.session.query(MealLog).filter_by(user_id=uid).count(),products=db.session.query(FoodProduct).filter_by(user_id=uid).count(),
        receipts=db.session.query(NutritionImportReceipt).filter_by(user_id=uid).count())

if __name__=='__main__':app.run(host='127.0.0.1',port=8042,debug=False,use_reloader=False,load_dotenv=False)
