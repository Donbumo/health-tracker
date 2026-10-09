"""Progressive Flask/Jinja UI. Forms call official services in one transaction."""
from datetime import date, datetime
from zoneinfo import ZoneInfo
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4
from flask import render_template, request, redirect, url_for, abort, current_app
from flask_login import login_required, current_user
from itsdangerous import URLSafeTimedSerializer, BadSignature
from sqlalchemy.exc import IntegrityError
from app.services.mobile_health import MobileSyncError
from app.nutrition import nutrition_bp
from app.extensions import db
from app.models import Recipe, FoodProduct
from app.models.nutrition_intelligence import MealLog
from app.services import nutrition_intelligence as ni, food_catalog as catalog
from app.services.nutrition_math import NutritionError, NUTRIENTS, PRODUCT, ingredient, summarize, decimal, COVERAGE_EXPLANATION


@nutrition_bp.app_template_filter("nutrient_value")
def value(value):
    if value is None:
        return "Sin dato conocido"
    number = Decimal(str(value))
    if 0 < number < Decimal("0.1"):
        return "<0.1"
    return str(number.quantize(Decimal("0.1"),rounding=ROUND_HALF_UP)).removesuffix(".0")


@nutrition_bp.errorhandler(NutritionError)
def nutrition_error(error):
    db.session.rollback()
    return render_template("nutrition/error.html",message=str(error)),error.status


@nutrition_bp.errorhandler(IntegrityError)
def concurrent_error(_error):
    db.session.rollback()
    return render_template('nutrition/error.html',message='Otra operación cambió estos datos. Reabre la comida y revisa.'),409


@nutrition_bp.errorhandler(MobileSyncError)
def food_error(error):
    db.session.rollback()
    return render_template('nutrition/error.html',message=str(error)),error.status


def render(view, **values):
    return render_template("nutrition/page.html",view=view,nutrients=NUTRIENTS,
        coverage_explanation=COVERAGE_EXPLANATION,enabled=current_app.config.get("NUTRITION_INTELLIGENCE_ENABLED"),**values)


def date_arg():
    try:
        return date.fromisoformat(request.values.get("date") or datetime.now(ZoneInfo(current_user.timezone or 'UTC')).date().isoformat())
    except ValueError as error:
        raise NutritionError("Fecha inválida.") from error


@nutrition_bp.get("/")
@login_required
def today():
    target=date_arg()
    return render("today",target=target,**ni.daily_summary(current_user.id,target))


@nutrition_bp.get("/add")
@login_required
def add():
    return render("add")


@nutrition_bp.get("/foods")
@login_required
def search():
    text=request.args.get("q","")
    return render("search",results=catalog.search(current_user.id,text),text=text,draft=request.args.get("draft"))


@nutrition_bp.get("/foods/<ref>")
@login_required
def detail(ref):
    food=catalog.detail(current_user.id,ref)
    return render("detail",food=food,summary=summarize([ingredient(food,food['basis_amount'],food['basis_unit'])]),draft=request.args.get("draft"),draft_revision=ni.owned_draft(current_user.id,request.args['draft']).revision if request.args.get('draft') else None)


@nutrition_bp.post("/drafts")
@login_required
def create():
    row=ni.create_draft(current_user.id,target=date_arg().isoformat())
    db.session.commit()
    return redirect(url_for('nutrition.review',key=row.public_id))


@nutrition_bp.get("/drafts/<key>")
@login_required
def review(key):
    row=ni.owned_draft(current_user.id,key)
    target=date.fromisoformat(row.snapshot_json['local_date'])
    day=ni.daily_summary(current_user.id,target)['day']
    return render("review",row=row,summary=row.snapshot_json['summary'],pending=ni.pending(row),
                  token=ni.confirmation_token(row),legacy_conflict=day is not None and day.authority is None)


def quantity_fields(data):
    unit=data.get('unit','g')
    if unit.startswith('serving:'):
        data=dict(data,unit='serving',serving_id=unit[8:])
    return data


@nutrition_bp.post("/drafts/<key>/change")
@login_required
def change(key):
    try:
        row=ni.mutate_draft(current_user.id,key,int(request.form['revision']),request.form['action'],quantity_fields(request.form.to_dict()))
    except (KeyError,TypeError,ValueError) as error:
        if isinstance(error,NutritionError): raise
        raise NutritionError("Revisa los campos de la comida.") from error
    db.session.commit()
    return redirect(url_for('nutrition.review',key=row.public_id))


@nutrition_bp.post("/drafts/<key>/confirm")
@login_required
def confirm(key):
    row=ni.owned_draft(current_user.id,key)
    token=request.form.get('token','')
    if token != ni.confirmation_token(row):
        # Timestamped tokens may differ across seconds; verify actual bound claims below.
        try:
            claims=URLSafeTimedSerializer(current_app.secret_key,salt="nutrition-meal-confirm-v2").loads(token,max_age=1800)
        except BadSignature as error:
            raise NutritionError("Confirmación inválida.",409) from error
        if claims.get('draft')!=key:
            raise NutritionError("Confirmación de otra comida.",409)
    log,_=ni.confirm(current_user.id,token,authority=request.form.get('authority'))
    db.session.commit()
    return redirect(url_for('nutrition.today',date=log.local_date.isoformat()))


@nutrition_bp.get("/saved")
@login_required
def saved():
    counts=db.select(MealLog.recipe_id.label('recipe_id'),db.func.count(MealLog.id).label('uses')).where(
        MealLog.user_id==current_user.id).group_by(MealLog.recipe_id).subquery()
    rows=db.session.execute(db.select(Recipe,db.func.coalesce(counts.c.uses,0)).outerjoin(
        counts,counts.c.recipe_id==Recipe.id).where(Recipe.user_id==current_user.id,Recipe.is_active.is_(True)).order_by(
        db.func.coalesce(counts.c.uses,0).desc(),Recipe.updated_at.desc())).all()
    return render("saved",recipes=[r[0] for r in rows],uses={r[0].id:r[1] for r in rows})


@nutrition_bp.post("/saved/<key>/use")
@login_required
def use(key):
    row=ni.template_draft(current_user.id,key,date_arg().isoformat())
    if request.form.get('editing')=='yes':
        recipe=db.session.execute(db.select(Recipe).where(Recipe.user_id==current_user.id,Recipe.public_id==key)).scalar_one()
        row.snapshot_json=dict(row.snapshot_json,save_target=recipe.public_id,save_base_revision=recipe.revision)
    db.session.commit()
    return redirect(url_for('nutrition.review',key=row.public_id))


@nutrition_bp.post("/drafts/<key>/save")
@login_required
def save(key):
    row=ni.owned_draft(current_user.id,key)
    ni.save_template(current_user.id,key,request.form.get('revision'),recipe_key=row.snapshot_json.get('save_target'),base_revision=row.snapshot_json.get('save_base_revision'))
    db.session.commit()
    return redirect(url_for('nutrition.saved'))


@nutrition_bp.post("/logs/<key>/repeat")
@login_required
def repeat(key):
    row=ni.repeat(current_user.id,key,date_arg().isoformat())
    db.session.commit()
    return redirect(url_for('nutrition.review',key=row.public_id))


@nutrition_bp.get("/micronutrients")
@login_required
def micros():
    target=date_arg()
    return render("micros",target=target,**ni.daily_summary(current_user.id,target))


@nutrition_bp.route("/my-food",methods=['GET','POST'])
@login_required
def my_food():
    ni.enabled()
    if request.method=='GET':
        return render('my_food',preview=None)
    serializer=URLSafeTimedSerializer(current_app.secret_key,salt='nutrition-private-food-v2')
    if request.form.get('token'):
        try: document=serializer.loads(request.form['token'],max_age=1800)
        except BadSignature as error: raise NutritionError('Preview vencido.',409) from error
        if document['owner']!=current_user.id: raise NutritionError('Preview no encontrado.',404)
        ni.lock_owner(current_user.id)
        existing=db.session.execute(db.select(FoodProduct).where(FoodProduct.user_id==current_user.id,FoodProduct.public_id==document['public_id'])).scalar_one_or_none()
        if existing is None:
            from app.services.mobile_health import create_food
            payload={'public_id':document['public_id'],'name':document['name']}
            for n,col in PRODUCT.items():
                external=col
                if document['nutrients'].get(n,{}).get('value') is not None:
                    payload[external]=document['nutrients'][n]['value']
            existing=create_food(current_user.id,payload)
            existing.nutrition_json={'nutrients':document['nutrients'],'servings':[],'density_g_ml':None}
            db.session.flush()
        db.session.commit()
        return redirect(url_for('nutrition.detail',ref='user:'+existing.public_id))
    name=request.form.get('name','').strip()
    if not name or len(name)>200: raise NutritionError('Indica un nombre válido.')
    vector={}
    for key,(_,unit,_) in NUTRIENTS.items():
        raw=request.form.get(key,'').strip()
        if raw:
            number=decimal(raw)
            if key in PRODUCT and number.quantize(Decimal('0.001'),rounding=ROUND_HALF_UP)>=Decimal('10000000'):
                raise NutritionError('El valor supera la capacidad del alimento legacy.')
            vector[key]={'state':'known','value':str(number),'unit':unit,'provenance':{'method':'user_declared'}}
    document={'owner':current_user.id,'public_id':str(uuid4()),'name':name,'nutrients':vector}
    return render('my_food',preview=document,token=serializer.dumps(document))
