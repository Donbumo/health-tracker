"""Progressive Flask/Jinja UI. Forms call official services in one transaction."""
from datetime import date, datetime
from zoneinfo import ZoneInfo
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4
from flask import render_template, request, redirect, url_for, abort, current_app, flash
from flask_login import login_required, current_user
from itsdangerous import URLSafeTimedSerializer, BadSignature
from sqlalchemy.exc import IntegrityError
from app.services.mobile_health import MobileSyncError
from app.nutrition import nutrition_bp
from app.extensions import db
from app.models import Recipe, FoodProduct
from app.models.nutrition_intelligence import MealLog, NutritionPlan, NutritionImportReceipt
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


@nutrition_bp.app_template_filter('nutrition_source_label')
def source_label(source):
    return {'usda_sr_legacy':'USDA SR Legacy','usda_foundation':'USDA Foundation',
            'usda_fndds':'USDA FNDDS','open_food_facts':'Open Food Facts','user':'Tu declaración privada'}.get(source,source)


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
    return render_template("nutrition/experience.html" if view in {'history','import_upload','import_review','import_result','library','external'} else "nutrition/page.html",view=view,nutrients=NUTRIENTS,
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
    from app.services.nutrition_history import history
    try:period=int(request.args.get('period',30))
    except ValueError:period=30
    return render("history",**history(current_user.id,target,period))


@nutrition_bp.get("/add")
@login_required
def add():
    return render("add")


@nutrition_bp.get("/foods")
@login_required
def search():
    text=request.args.get("q","")
    filters={key:request.args.get(key) for key in ('source','state','food_type','brand','barcode')}
    try:offset=max(0,int(request.args.get('offset',0)))
    except ValueError:offset=0
    return render("search",results=catalog.search(current_user.id,text,**filters,offset=offset),text=text,draft=request.args.get("draft"),filters=filters,offset=offset,sources=catalog.status())


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
@nutrition_bp.route("/my-food/<key>",methods=['GET','POST'])
@login_required
def my_food(key=None):
    ni.enabled()
    if request.method=='GET':
        food=catalog.detail(current_user.id,'user:'+key) if key else None
        proposal = request.args.get('proposal')
        if proposal:
            if key: raise NutritionError('Una propuesta externa crea un alimento nuevo; no reemplaza otra identidad.',409)
            try: claims=URLSafeTimedSerializer(current_app.secret_key,salt='nutrition-off-proposal-v21').loads(proposal,max_age=1800)
            except BadSignature as error: raise NutritionError('La propuesta cambió o venció. Consulta de nuevo.',409) from error
            if claims.get('owner')!=current_user.id:raise NutritionError('Propuesta no encontrada.',404)
            food=claims['food']
        return render('my_food',preview=None,form_food=food,is_edit=bool(key),external_proposal=bool(proposal))
    serializer=URLSafeTimedSerializer(current_app.secret_key,salt='nutrition-private-food-v2')
    if request.form.get('token'):
        try: document=serializer.loads(request.form['token'],max_age=1800)
        except BadSignature as error: raise NutritionError('Preview vencido.',409) from error
        if document['owner']!=current_user.id: raise NutritionError('Preview no encontrado.',404)
        if key and key!=document['public_id']:raise NutritionError('Preview de otro producto.',409)
        if bool(key)!=(document.get('base_revision') is not None):raise NutritionError('La acción del preview cambió.',409)
        existing=catalog.save_personal_definition(current_user.id,document)
        db.session.commit()
        return redirect(url_for('nutrition.detail',ref='user:'+existing.public_id))
    name=request.form.get('name','').strip()
    if not name or len(name)>200: raise NutritionError('Indica un nombre válido.')
    vector={}
    for nutrient_key,(_,unit,_) in NUTRIENTS.items():
        raw=request.form.get(nutrient_key,'').strip()
        if raw:
            number=decimal(raw)
            if nutrient_key in PRODUCT and number.quantize(Decimal('0.001'),rounding=ROUND_HALF_UP)>=Decimal('10000000'):
                raise NutritionError('El valor supera la capacidad del alimento legacy.')
            vector[nutrient_key]={'state':'known','value':str(number),'unit':unit,'provenance':{'method':'user_declared'}}
    basis_amount=str(decimal(request.form.get('basis_amount','100'),positive=True))
    basis_unit=request.form.get('basis_unit','g')
    if basis_unit not in {'g','ml'}:raise NutritionError('Base inválida; usa g o ml explícitos.')
    document={'owner':current_user.id,'public_id':str(uuid4()),'name':name,'nutrients':vector,'basis_amount':basis_amount,'basis_unit':basis_unit,
        'brand':request.form.get('brand','').strip()[:200] or None,'barcode':request.form.get('barcode','').strip()[:32] or None,
        'net_content_text':request.form.get('net_content_text','').strip()[:200]}
    if request.args.get('proposal'):
        try:claims=URLSafeTimedSerializer(current_app.secret_key,salt='nutrition-off-proposal-v21').loads(request.args['proposal'],max_age=1800)
        except BadSignature as error:raise NutritionError('Propuesta externa vencida.',409) from error
        if claims.get('owner')!=current_user.id or key:raise NutritionError('Propuesta no encontrada.',404)
        proposal=claims['food']
        document['provenance']={'method':'user_confirmed_external_proposal','source':'open_food_facts',
            'source_food_id':proposal['source_food_id'],'source_revision':proposal['revision'],
            'license':'ODbL-1.0','attribution':'Open Food Facts contributors',
            'original_proposal':proposal}
    if key:
        food=catalog.detail(current_user.id,'user:'+key)
        try:base_revision=int(request.form.get('base_revision',''))
        except ValueError as error:raise NutritionError('Revisión del producto inválida.',409) from error
        if base_revision!=int(food['revision']):raise NutritionError('El producto cambió. Reabre y revisa.',409)
        document.update(public_id=key,base_revision=base_revision)
    return render('my_food',preview=document,token=serializer.dumps(document))


@nutrition_bp.route('/import',methods=['GET','POST'])
@login_required
def import_upload():
    ni.enabled()
    if request.method=='GET':
        from app.services.importers.registry import ImportAdapterRegistry
        return render('import_upload',adapter=ImportAdapterRegistry().get('nutrition_sources'))
    from app.services import nutrition_import as imports
    file=request.files.get('file')
    if not file:raise NutritionError('Selecciona un archivo.')
    row=imports.start(current_user.id,file.stream.read(10*1024*1024+1),file.filename,file.mimetype)
    db.session.commit()
    return redirect(url_for('nutrition.import_review',key=row.public_id))


@nutrition_bp.get('/import/<key>')
@login_required
def import_review(key):
    from app.services import nutrition_import as imports
    from app.services.importers.standard_import_executor import StandardImportExecutor
    row=imports.owned(current_user.id,key);review=row.review_json
    document=None;plan=None;token=None;blocking=[]
    pending=sum(not item.get('confirmed') for item in review['rows'] if not item.get('skip'))
    if not pending:
        try:
            document=imports.canonical(row)
            executor=StandardImportExecutor();plan=executor.plan_documents([document],user_id=current_user.id,target_type='nutrition_import')
            blocking=plan['errors']
            if not plan['invalid'] and not plan['conflicts']:
                token=executor.build_confirmation_token(user_id=current_user.id,target_type='nutrition_import',payload=document,plan=plan)
        except ValueError as error:blocking=[str(error)]
    matches=catalog.search(current_user.id,request.args.get('q',''),limit=20) if request.args.get('q') else []
    previews={}
    binding_info={}
    for index,item in enumerate(review['rows']):
        if item.get('skip'):continue
        binding_info[index]={}
        for part,binding in enumerate(item.get('ingredients',[])):
            if binding.get('ref'):
                try:binding_info[index][part]=catalog.detail(current_user.id,binding['ref'],binding.get('food_revision'))
                except NutritionError:pass
        try:previews[index]=imports.row_preview(row,index)
        except (ValueError,KeyError,TypeError):pass
    try: step=max(1,min(4,int(request.args.get('step',1))))
    except ValueError:step=1
    return render('import_review',row=row,review=review,pending=pending,document=document,plan=plan,token=token,blocking=blocking,matches=matches,query=request.args.get('q',''),previews=previews,step=step,original_policy=imports.original_policy(row),binding_info=binding_info)


@nutrition_bp.post('/import/<key>/change')
@login_required
def import_change(key):
    from app.services import nutrition_import as imports
    try:row=imports.update(current_user.id,key,request.form['revision'],request.form['action'],request.form.to_dict())
    except (KeyError,ValueError,TypeError) as error:
        if isinstance(error,NutritionError):raise
        raise NutritionError('Revisa los campos de la importación.') from error
    db.session.commit()
    return redirect(url_for('nutrition.import_review',key=row.public_id,step=request.form.get('step',1)))


@nutrition_bp.post('/import/<key>/delete-original')
@login_required
def delete_original(key):
    from app.services import nutrition_import as imports
    row, path = imports.delete_original(current_user.id,key,request.form.get('revision'),confirmed=request.form.get('confirmed')=='yes')
    db.session.commit()
    if path:
        try:path.unlink(missing_ok=True)
        except OSError as error:
            raise NutritionError('La revisión está cerrada, pero no se pudo eliminar físicamente el original. Requiere limpieza de almacenamiento autorizada.',503) from error
    flash('Original eliminado. La evidencia de revisión se conserva; no se modificó ningún snapshot.', 'success')
    return redirect(url_for('nutrition.import_review',key=row.public_id,step=4))


@nutrition_bp.post('/import/<key>/confirm')
@login_required
def import_confirm(key):
    from app.services import nutrition_import as imports
    from app.services.importers.standard_import_executor import StandardImportExecutor
    ni.enabled();ni.lock_owner(current_user.id);row=imports.owned(current_user.id,key,True)
    imports.assert_pending(row,request.form['revision'])
    document=imports.canonical(row);executor=StandardImportExecutor();plan=executor.plan_documents([document],user_id=current_user.id,target_type='nutrition_import')
    try:executor.verify_confirmation_token(request.form.get('token',''),user_id=current_user.id,target_type='nutrition_import',payload=document,plan=plan)
    except ValueError as error:raise NutritionError('La confirmación cambió o venció; revisa de nuevo.',409) from error
    result=executor.commit_documents([document],user_id=current_user.id,target_type='nutrition_import',confirmed=True,audit_metadata={'nutrition_review':row.public_id,'source_sha256':row.source_sha256})
    if result['committed']:
        row=imports.owned(current_user.id,key,True);row.state='completed';db.session.commit()
    receipt=db.session.execute(db.select(NutritionImportReceipt).where(NutritionImportReceipt.user_id==current_user.id,NutritionImportReceipt.event_key==document['data']['event_key'])).scalar_one_or_none()
    return render('import_result',result=result,receipt=receipt,row=row,original_policy=imports.original_policy(row)),200 if result['committed'] else 409


@nutrition_bp.get('/library')
@login_required
def library():
    text=request.args.get('q','').strip()[:100];kind=request.args.get('kind','all')
    if kind not in {'all','products','recipes','plans'}:kind='all'
    sections=[]
    for key,model,label in [('plans',NutritionPlan,'Planes importados'),('products',FoodProduct,'Productos privados'),('recipes',Recipe,'Recetas')]:
        if kind not in {'all',key}:continue
        query=db.select(model).where(model.user_id==current_user.id,model.is_active.is_(True))
        if text:
            pattern=catalog.like_pattern(text)
            predicate=model.name.ilike(pattern,escape='\\')
            if key=='products':predicate=db.or_(predicate,model.brand.ilike(pattern,escape='\\'))
            query=query.where(predicate)
        total=db.session.scalar(db.select(db.func.count()).select_from(query.subquery()))
        pages=max(1,(total+23)//24)
        try:page=max(1,min(pages,int(request.args.get(key+'_page',1))))
        except ValueError:page=1
        rows=db.session.execute(query.order_by(model.name,model.id).offset((page-1)*24).limit(24)).scalars().all()
        params={k:v for k,v in request.args.items() if k in {'plans_page','products_page','recipes_page'}}|{'q':text,'kind':kind}
        sections.append({'key':key,'label':label,'rows':rows,'total':total,'page':page,'pages':pages,
                         'previous':url_for('nutrition.library',**(params|{key+'_page':page-1})) if page>1 else None,
                         'next':url_for('nutrition.library',**(params|{key+'_page':page+1})) if page<pages else None})
    return render('library',sections=sections,text=text,kind=kind)


@nutrition_bp.post('/plans/<key>/<int:index>/use')
@login_required
def use_plan(key,index):
    from app.services.nutrition_import import use_plan as create_plan_draft
    row=create_plan_draft(current_user.id,key,index,date_arg().isoformat());db.session.commit()
    return redirect(url_for('nutrition.review',key=row.public_id))


@nutrition_bp.post('/plans/<key>/edit')
@login_required
def edit_plan(key):
    from app.services.nutrition_import import edit_plan as create_plan_review
    row=create_plan_review(current_user.id,key);db.session.commit()
    return redirect(url_for('nutrition.import_review',key=row.public_id))


@nutrition_bp.route('/external',methods=['GET','POST'])
@login_required
def external():
    results=[]
    if request.method=='POST':
        ni.enabled()
        if not current_app.config.get('NUTRITION_EXTERNAL_LOOKUP_ENABLED',False):raise NutritionError('Consulta externa no habilitada.',404)
        from app.services.nutrition_sources import public_lookup
        results=public_lookup.lookup(request.form.get('q',''),consent=request.form.get('consent')=='yes')
    serializer=URLSafeTimedSerializer(current_app.secret_key,salt='nutrition-off-proposal-v21')
    return render('external',results=[dict(food,proposal_token=serializer.dumps({'owner':current_user.id,'food':food})) for food in results])


@nutrition_bp.post('/external/proposal')
@login_required
def external_proposal():
    ni.enabled()
    # The next GET verifies the signature, expiry and owner. This POST never writes a food.
    return redirect(url_for('nutrition.my_food',proposal=request.form.get('proposal','')))
