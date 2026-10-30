"""Issue #32 real Flask UI, loopback only, fictional accounts and temp storage."""
import copy
import json
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
from app import create_app
from app.extensions import db
from app.models import User,MealLog,FoodProduct,NutritionImportReceipt,NutritionImportDraft
from app.services import nutrition_import_review as compact, nutrition_import as imports
from flask_login import current_user,login_required

root=Path(tempfile.mkdtemp(prefix='issue32-fictional-flask-'))
app=create_app(dict(TESTING=True,SECRET_KEY='qa-preview-fictional-secret-longer-than-32-characters',
    API_TOKEN_SIGNING_KEY='qa-preview-fictional-api-key-longer-than-32-characters',
    SQLALCHEMY_DATABASE_URI='sqlite:///'+(root/'qa.sqlite').as_posix(),SQLALCHEMY_ENGINE_OPTIONS={},
    DATA_ROOT=root,UPLOAD_ROOT=root/'uploads/raw',GENERATED_UPLOAD_ROOT=root/'generated',PORTABILITY_ROOT=root/'portable',
    SCHEMA_ROOT=ROOT/'schemas',NUTRITION_INTELLIGENCE_ENABLED=True,NUTRITION_QA_LABEL=True,
    AI_ENABLED=False,NUTRITION_EXTERNAL_LOOKUP_ENABLED=False,APP_TIMEZONE='UTC'))
with app.app_context():
    db.create_all()
    for screen in ['mobile','desktop']:
        for case in ['clean','error','edit']:
            account=User(username='qa-preview-'+case+'-'+screen,role='user',display_name='QA ficticia')
            account.set_password('fictional-preview-ui-password');db.session.add(account)
    manual=User(username='qa-preview-manual',role='user',display_name='QA visual ficticia')
    manual.set_password('fictional-preview-ui-password');db.session.add(manual)
    db.session.commit()


@app.get('/qa/preview-state')
@login_required
def state():
    uid=current_user.id
    rows=db.session.scalars(db.select(NutritionImportDraft).where(NutritionImportDraft.user_id==uid).order_by(NutritionImportDraft.id.desc())).all()
    logs=db.session.scalars(db.select(MealLog).where(MealLog.user_id==uid).order_by(MealLog.id)).all()
    row=rows[0] if rows else None
    return dict(logs=len(logs),products=db.session.query(FoodProduct).filter_by(user_id=uid).count(),
        receipts=db.session.query(NutritionImportReceipt).filter_by(user_id=uid).count(),
        revision=row.revision if row else None,counts=compact.overview(row)['counts'] if row and row.state=='pending' else None,
        first_energy=logs[0].snapshot_json['summary']['energy']['value'] if logs else None,
        first_protein=logs[0].snapshot_json['summary']['protein']['value'] if logs else None,
        corrected_rows=sum(bool(r.get('corrections')) for r in row.review_json['rows']) if row else 0,
        original_unchanged=[r['original'] for r in row.review_json['rows']]==[r['original'] for r in imports.verified_original(row)[1]['rows']] if row else True)


if __name__=='__main__':
    print('Fictional preview Flask QA ready on loopback 8042',flush=True)
    app.run(host='127.0.0.1',port=8042,debug=False,use_reloader=False,load_dotenv=False)
