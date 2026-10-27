"""Reviewed nutrition adapter; canonical planning is read-only, writes atomic.

Extraction never imports. Domain writes run exclusively inside the existing
StandardImportExecutor transaction and persist one owner-local receipt.
"""
import copy
import io
from pathlib import Path
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo
from werkzeug.datastructures import FileStorage
from flask import current_app
from app.extensions import db
from app.models import FoodProduct, Recipe, DailyNutrition, NutritionImportDraft, NutritionImportReceipt, NutritionPlan, UploadedFile
from app.services import food_catalog, nutrition_intelligence as ni
from app.services.nutrition_math import NutritionError, NUTRIENTS, PRODUCT, LEGACY, decimal, validate_vector, ingredient, summarize, snapshot_summary, precise
from app.services.importers.nutrition_sources import extract, MAX_BYTES
from app.services.validation import validate_json_document


DESTINATIONS={'plan','consumed','products','recipes','daily_aggregate'}


def owned(user_id,key,lock=False):
    query=db.select(NutritionImportDraft).where(NutritionImportDraft.user_id==user_id,NutritionImportDraft.public_id==key)
    if lock:query=query.with_for_update().execution_options(populate_existing=True)
    row=db.session.execute(query).scalar_one_or_none()
    if not row:raise NutritionError('Revisión no encontrada.',404)
    return row


def start(user_id,payload,filename,mime=None):
    ni.enabled()
    if len(payload)>MAX_BYTES:raise NutritionError('Archivo mayor de 10 MiB.')
    try:found=extract(payload,filename,mime)
    except NutritionError:raise
    except Exception as error:raise NutritionError('No se pudo extraer el documento; revisa su formato y límites.') from error
    # Reuse the official owner-isolated original upload store only AFTER parse.
    from app.services.files import store_uploaded_file
    source,_=store_uploaded_file(FileStorage(stream=io.BytesIO(payload),filename=filename,content_type=mime),user_id)
    found['source']['file']=source.original_filename
    for item in found['rows']:
        if item['evidence'].get('sha256')==source.sha256:
            item['evidence']['file']=source.original_filename
    review={'name':source.original_filename[:200],'destination':found['classification_hint'] if found['classification_hint'] in DESTINATIONS else '',
            'rows':found['rows']}
    prior=db.session.execute(db.select(NutritionImportReceipt).where(NutritionImportReceipt.user_id==user_id,
        NutritionImportReceipt.event_key==ni.hash_document({'file':source.sha256}))).scalar_one_or_none()
    if found.get('standard'):
        document=found['standard']; validate_json_document(document,'nutrition_import_2_1')
        review.update(name=document['data']['name'],destination=document['data']['destination'],rows=[])
        for entry in document['data']['entries']:
            review['rows'].append(dict(copy.deepcopy(entry),original=copy.deepcopy(entry),declaration=(entry.get('declaration') or {}).get('nutrients',{}),
                basis_amount=(entry.get('declaration') or {}).get('basis_amount'),basis_unit=(entry.get('declaration') or {}).get('basis_unit'),
                ingredients=entry['bindings'],confirmed=False,skip=entry.get('skip',False),warnings=[],
                composition_complete=entry['composition']['complete'],total_mass_g=entry['composition'].get('total_mass_g')))
    row=NutritionImportDraft(user_id=user_id,source_sha256=source.sha256,
        source_json={'upload_id':source.id,'profile':found['profile'],'classification_hint':found['classification_hint'],
            'warnings':found['warnings'],'text':found['text'],'evidence':found['source']},review_json=review)
    if prior:
        row.source_json=dict(row.source_json,already_imported=True)
        row.state='completed'
    else:
        existing=db.session.execute(db.select(NutritionImportDraft).where(
            NutritionImportDraft.user_id==user_id,NutritionImportDraft.source_sha256==source.sha256,
            NutritionImportDraft.state=='pending').order_by(NutritionImportDraft.id.desc())).scalars()
        for pending in existing:
            try:assert_pending(pending,pending.revision)
            except NutritionError:continue
            return pending
    db.session.add(row);db.session.flush();return row


def assert_pending(row,revision):
    created=row.created_at.replace(tzinfo=timezone.utc) if row.created_at.tzinfo is None else row.created_at
    try:revision=int(revision)
    except (ValueError,TypeError) as error:raise NutritionError('Revisión inválida; reabre el resumen.',409) from error
    if row.state!='pending' or row.revision!=revision or datetime.now(timezone.utc)-created>timedelta(hours=24):
        raise NutritionError('La revisión cambió o venció. Reabre el archivo.',409)
    upload_id=(row.source_json or {}).get('upload_id')
    if upload_id and not db.session.scalar(db.select(UploadedFile.id).where(UploadedFile.id==upload_id,UploadedFile.user_id==row.user_id)):
        raise NutritionError('El original ya no está disponible. Reabre el archivo antes de confirmar.',409)


def original_policy(row):
    """Conservative retention: confirmed or shared references retain the raw file."""
    upload_id=(row.source_json or {}).get('upload_id')
    source=db.session.execute(db.select(UploadedFile).where(UploadedFile.id==upload_id,
        UploadedFile.user_id==row.user_id)).scalar_one_or_none() if upload_id else None
    if not source:return {'available':False,'can_delete':False,'reason':'Original eliminado o no adjunto. La evidencia extraída permanece en la revisión.'}
    confirmed=db.session.scalar(db.select(db.func.count()).select_from(NutritionImportReceipt).where(
        NutritionImportReceipt.user_id==row.user_id,NutritionImportReceipt.source_sha256==row.source_sha256))
    if confirmed or row.state=='completed' or source.import_status=='imported':
        return {'available':True,'can_delete':False,'reason':'Original retenido: respalda una importación confirmada y su auditoría. Esta política no elimina originales de registros confirmados.'}
    if source.detected_type not in {'unknown','nutrition_sources','nutrition_import'}:
        return {'available':True,'can_delete':False,'reason':'Otro importador identificó este original. Se conserva hasta comprobar su política de referencias y auditoría.'}
    shared=db.session.scalar(db.select(db.func.count()).select_from(NutritionImportDraft).where(
        NutritionImportDraft.user_id==row.user_id,NutritionImportDraft.public_id!=row.public_id,
        NutritionImportDraft.source_json['upload_id'].as_integer()==upload_id,NutritionImportDraft.state=='pending'))
    if shared:return {'available':True,'can_delete':False,'reason':'Otra revisión pendiente utiliza el original. Cancélala antes de eliminar el archivo compartido.'}
    # Include all official domain FK references, even ones introduced in future.
    for table in db.metadata.tables.values():
        for column in table.columns:
            if any(fk.target_fullname=='uploaded_files.id' for fk in column.foreign_keys):
                if db.session.scalar(db.select(db.func.count()).select_from(table).where(column==upload_id)):
                    return {'available':True,'can_delete':False,'reason':'Otro registro o proceso referencia el archivo. Se conserva el original para evitar pérdida de evidencia.'}
    return {'available':True,'can_delete':True,'reason':'Eliminar cierra esta revisión. Se borra el archivo físico; texto extraído, decisiones y evidencia de revisión se conservan. No se modifica el historial.'}


def delete_original(user_id,key,revision,*,confirmed=False):
    ni.enabled();ni.lock_owner(user_id);row=owned(user_id,key,True)
    try:valid_revision=int(revision)==row.revision
    except (ValueError,TypeError):valid_revision=False
    if not valid_revision:raise NutritionError('La revisión cambió. Reabre antes de eliminar.',409)
    if not confirmed:raise NutritionError('Confirma explícitamente la eliminación del original.')
    source=db.session.execute(db.select(UploadedFile).where(UploadedFile.user_id==user_id,
        UploadedFile.id==row.source_json.get('upload_id')).with_for_update()).scalar_one_or_none()
    policy=original_policy(row)
    if not policy['can_delete']:raise NutritionError(policy['reason'],409)
    from app.services.backups import resolve_uploaded_download, BackupError
    root=Path(current_app.config['UPLOAD_ROOT']).resolve();folder=root/f'user_{user_id}'
    candidate=Path(current_app.config['DATA_ROOT'])/source.storage_path
    if folder.is_symlink() or candidate.is_symlink():raise NutritionError('El original no admite eliminación segura.',409)
    try:
        path=resolve_uploaded_download(source,user_id=user_id)
        path.resolve().relative_to(folder.resolve())
    except (BackupError,ValueError) as error:raise NutritionError('El original no está disponible o no supera la validación de integridad.',409) from error
    related=db.session.execute(db.select(NutritionImportDraft).where(NutritionImportDraft.user_id==user_id,
        NutritionImportDraft.source_json['upload_id'].as_integer()==source.id).with_for_update()).scalars().all()
    for review in related:
        review.state='cancelled'
        review.source_json=dict(review.source_json,upload_id=None,original_deleted_at=datetime.now(timezone.utc).isoformat(),
                                original_deletion_policy='unconfirmed_only_v1')
        review.revision+=1
    db.session.delete(source);db.session.flush()
    # Route commits the metadata first; filesystem cleanup cannot run after a
    # rejected transaction. Confirmed records never reach this path.
    return row,path


def update(user_id,key,revision,action,data):
    ni.enabled();ni.lock_owner(user_id);row=owned(user_id,key,True);assert_pending(row,revision)
    review=copy.deepcopy(row.review_json)
    if action=='cancel':row.state='cancelled'
    elif action=='destination':
        destination=data.get('destination')
        if destination not in DESTINATIONS:raise NutritionError('Selecciona el destino.')
        name=data.get('name','').strip()
        if not name or len(name)>200:raise NutritionError('Nombre de importación inválido.')
        review.update(destination=destination,name=name)
        for item in review['rows']:item['confirmed']=False
    else:
        index=int(data['index'])
        if index<0 or index>=len(review['rows']):raise NutritionError('Fila no encontrada.')
        item=review['rows'][index]
        if action=='fields':
            section=data.get('_section','all')
            fields={'identity':('name','date','planned_for','meal_type','brand','barcode'),
                    'composition':('amount','unit','total_mass_g','yield_factor','authority','conflict_action'),
                    'declaration':('basis_amount','basis_unit')}
            if section not in {*fields,'all'}:raise NutritionError('Etapa de revisión inválida.')
            selected=tuple(field for group in fields.values() for field in group) if section=='all' else fields[section]
            for field in selected:
                value=str(data.get(field,'')).strip()
                if value:item[field]=value[:200]
                else:item.pop(field,None)
            if section in {'all','composition'}:item['composition_complete']=data.get('composition_complete')=='yes'
            if section in {'all','declaration'}:
                vector={}
                for nutrient,(_,unit,_) in NUTRIENTS.items():
                    raw=str(data.get('nutrient_'+nutrient,'')).strip()
                    if raw:vector[nutrient]={'state':'known','value':str(decimal(raw)),'unit':unit,'provenance':{'method':'user_confirmed','original':item['original'].get(nutrient)}}
                if item.get('carbohydrate_proposal'):
                    choice=data.get('carbohydrate_classification')
                    if choice not in {'total','net','unknown'}:raise NutritionError('Clasifica los carbohidratos extraídos o confirma que no son clasificables.')
                    previous=item.get('carbohydrate_classification')
                    if previous in {'total','net'} and previous!=choice:
                        vector.pop('carbohydrate_total' if previous=='total' else 'net_carbs',None)
                    if choice!='unknown':
                        key='carbohydrate_total' if choice=='total' else 'net_carbs'
                        if key not in vector:
                            if item['carbohydrate_proposal'].get('unit') not in {None,'g'}:
                                raise NutritionError('La unidad original no es g: introduce un valor absoluto verificado. No se convierten porcentajes de referencia.')
                            proposed=copy.deepcopy(item['carbohydrate_proposal']);proposed['unit']='g'
                            proposed['provenance']['method']='user_confirmed_carbohydrate_classification';vector[key]=proposed
                    item['carbohydrate_reviewed']=True
                    item['carbohydrate_classification']=choice
                item['declaration']=vector
            item['confirmed']=False
            if any(part.get('new_food') for part in item['ingredients']):
                # An edited label cannot silently save the previous proposal.
                item['ingredients']=[]
        elif action=='bind':
            food=food_catalog.detail(user_id,data['ref'],data.get('food_revision'))
            amount=data.get('amount');unit=data['unit']
            if data.get('percent'):
                if amount:raise NutritionError('Indica gramaje o porcentaje explícito, no ambos.')
                percent=decimal(data['percent'],positive=True)
                if percent>100 or not item.get('total_mass_g'):raise NutritionError('Porcentaje requiere masa total explícita en g y un valor hasta 100.')
                amount=decimal(item['total_mass_g'],positive=True)*percent/100;unit='g'
            part={'ref':food['ref'],'food_revision':str(food['revision']),'amount':str(decimal(amount,positive=True)),'unit':unit}
            if data.get('serving_id'):part['serving_id']=data['serving_id']
            ingredient(food,part['amount'],part['unit'],part.get('serving_id'))
            if len(item['ingredients'])>=100:raise NutritionError('Máximo 100 ingredientes por fila.')
            item['ingredients'].append(part);item['confirmed']=False
        elif action=='unbind':
            part=int(data['part'])
            if not 0<=part<len(item['ingredients']):raise NutritionError('Vínculo no encontrado.')
            item['ingredients'].pop(part);item['confirmed']=False;item['composition_complete']=False
        elif action=='private':
            # Explicit proposal, never synthetic IDs or automatic catalog matches.
            vector=validate_vector(item['declaration'])
            if not item.get('name'):raise NutritionError('Revisa nombre y base explícita primero; datos ausentes permanecerán desconocidos.')
            nutrition={'basis_amount':str(decimal(item.get('basis_amount'),positive=True)),'basis_unit':item.get('basis_unit'),
                'nutrients':vector,'servings':[],'density_g_ml':None,'barcode':item.get('barcode'),
                'provenance':{'method':'user_confirmed_label','evidence':item['evidence']}}
            if nutrition['basis_unit'] not in {'g','ml'}:raise NutritionError('Producto requiere base explícita en g o ml.')
            amount=str(decimal(item.get('amount'),positive=True));unit=item.get('unit')
            if unit not in {'g','ml'}:raise NutritionError('Confirma una cantidad explícita en g o ml; no se inventa porción.')
            nutrition['servings']=[{'id':'reviewed-portion','label':'Porción explícita revisada','amount':amount,'unit':unit}]
            nutrition['metadata']={'brand':item.get('brand'),'barcode':item.get('barcode'),'quality':'user_confirmed_label',
                'net_content_text':item.get('net_content_text',''),
                'ingredient_text':'\n'.join(line for line in item.get('notes','').splitlines() if line.lower().startswith(('ingredientes','ingredients')))}
            item['ingredients']=[{'new_food':{'name':item['name'],'brand':item.get('brand'),'nutrition':nutrition},'amount':amount,'unit':unit}]
            item['confirmed']=False
        elif action=='skip':item['skip']=not item.get('skip');item['confirmed']=False
        elif action=='confirm':
            document=canonical(row,review,only_index=index)
            validate_document(document,user_id)
            item['confirmed']=True
        else:raise NutritionError('Acción inválida.')
    row.review_json=review;row.revision+=1;db.session.flush();return row


def canonical(row,review=None,only_index=None):
    review=review or row.review_json
    if review['destination'] not in DESTINATIONS:raise NutritionError('Clasifica el destino de la importación.')
    entries=[]
    for index,item in enumerate(review['rows']):
        if only_index is not None and index!=only_index:continue
        if item.get('skip'):continue
        if only_index is None and not item.get('confirmed'):raise NutritionError('Hay filas pendientes de identidad, cantidad o destino.')
        vector=validate_vector(item['declaration'])
        if item.get('carbohydrate_proposal') and not item.get('carbohydrate_reviewed'):
            raise NutritionError('Hay carbohidratos extraídos sin clasificar: confirma total, neto o desconocido.')
        declaration=None
        if vector:
            declaration={'basis_amount':str(decimal(item.get('basis_amount') or item.get('amount'),positive=True)),
                'basis_unit':item.get('basis_unit') or item.get('unit'),'nutrients':vector,'confirmed':True,
                'provenance':{'method':'user_confirmed_file','evidence':item['evidence']},'original_values':copy.deepcopy(item['original'])}
        entry={'name':item.get('name',''),'bindings':copy.deepcopy(item['ingredients']), 'declaration':declaration,
               'composition':{'complete':item.get('composition_complete',False),'total_mass_g':item.get('total_mass_g') or (item.get('amount') if item.get('unit')=='g' else None)},
               'evidence':dict(item['evidence'],review_row=index,original_fields=copy.deepcopy(item['original'])),'confirmed':True}
        if not item.get('name') and review['destination']=='daily_aggregate':entry.pop('name')
        if item.get('yield_factor'):
            entry['composition'].update(yield_factor=str(decimal(item['yield_factor'],positive=True)),
                notes='Rendimiento declarado conservado; no implica retención de nutrientes ni equivalencia crudo/cocido.')
        for field in ('date','planned_for','meal_type','authority','conflict_action'):
            if item.get(field):entry[field]=item[field]
        if item.get('amount') and item.get('unit'):
            entry.update(portion_amount=str(decimal(item['amount'],positive=True)),portion_unit=item['unit'])
        entries.append(entry)
    if not entries:raise NutritionError('No quedan filas para guardar.')
    document={'schema_version':'2.1','type':'nutrition_import','user_id':row.user_id,'source_type':'uploaded',
        'data':{'name':review['name'],'source_sha256':row.source_sha256,'event_key':ni.hash_document({'file':row.source_sha256}),
                'destination':review['destination'],'entries':entries}}
    if row.source_json.get('plan_identity'):
        if review['destination']!='plan':raise NutritionError('La edición de un plan conserva el destino prescrito; consumir exige usar y revisar por separado.')
        document['data'].update(plan_identity=row.source_json['plan_identity'],plan_revision=row.source_json['plan_revision'])
        document['data']['event_key']=ni.hash_document({'plan':row.source_json['plan_identity'],'revision':row.source_json['plan_revision']})
    document['data']['omitted_count']=sum(bool(item.get('skip')) for item in review['rows'])
    from app.services.importers.standard_json_generator import StandardJsonGenerator
    generated=StandardJsonGenerator().generate(document,{'target_type':'nutrition_import','path':'$','suggested_mapping':{}},user_id=row.user_id)
    if any(not r['valid'] for r in generated['validated_documents']):
        raise NutritionError('Completa los campos requeridos y las unidades antes de confirmar.')
    document=generated['generated_documents'][0]
    from app.services.importers.assisted_import_service import AssistedImportService
    if AssistedImportService().preview(document,user_id=row.user_id,requested_type='nutrition_import',generate_standard_json=False)['mode']!='standard_ready':
        raise NutritionError('El documento revisado no coincide con el contrato público.')
    return document


def proposed_food(proposal):
    n=proposal['nutrition'];validate_vector(n.get('nutrients',{}));decimal(n.get('basis_amount'),positive=True)
    if n.get('basis_unit') not in {'g','ml'}:raise NutritionError('Producto sin base explícita.')
    return {'name':proposal['name'],'preparation':proposal.get('brand') or 'Declaración revisada',
        'source':'user','revision':'1',**n}


def resolved_entries(entry,user_id,persist=False):
    output=[]
    for binding in entry['bindings']:
        if binding.get('new_food'):
            proposal=binding['new_food'];food=proposed_food(proposal)
            if persist:
                from app.services.mobile_health import create_food
                payload={'name':proposal['name'],'brand':proposal.get('brand')}
                if food['basis_unit']=='g':
                    for key,column in PRODUCT.items():
                        value=food['nutrients'].get(key,{})
                        if value.get('state')=='known':payload[column]=str(Decimal(value['value'])*100/Decimal(food['basis_amount']))
                product=create_food(user_id,payload);product.nutrition_json=copy.deepcopy(proposal['nutrition']);db.session.flush()
                food=food_catalog.detail(user_id,'user:'+product.public_id)
        else:food=food_catalog.detail(user_id,binding['ref'],binding['food_revision'])
        output.append(ingredient(food,binding['amount'],binding['unit'],binding.get('serving_id')))
    return output


@precise
def meal_snapshot(entry,entries,timezone_name):
    snapshot={'schema_version':'2.1' if any(part['food'].get('metadata') for part in entries) else '2.0','calculation_method':'decimal_scaled_v1','name':entry['name'],
              'meal_type':entry.get('meal_type'),'ingredients':entries,'summary':summarize(entries)}
    if entry.get('date'):snapshot.update(local_date=entry['date'],timezone=timezone_name)
    if entry['declaration']:
        declared=copy.deepcopy(entry['declaration'])
        if entry.get('portion_amount') and declared['basis_unit']!='portion':
            if declared['basis_unit']!=entry.get('portion_unit'):
                raise NutritionError('Porción y base declarada tienen unidades distintas; sin equivalencia explícita no se convierten.')
            factor=decimal(entry['portion_amount'],positive=True)/decimal(declared['basis_amount'],positive=True)
            declared['provenance']['original_basis']={'amount':declared['basis_amount'],'unit':declared['basis_unit'],'nutrients':copy.deepcopy(declared['nutrients'])}
            from app.services.nutrition_sources import finite_source_number
            for value in declared['nutrients'].values():
                if value['state']=='known':value['value']=finite_source_number(Decimal(value['value'])*factor)
                if value.get('limit') is not None:value['limit']=finite_source_number(Decimal(value['limit'])*factor)
            declared['basis_amount']=entry['portion_amount']
        snapshot.update(schema_version='2.1',calculation_method='decimal_declared_composition_v1',
            declared_nutrition=declared,composition=copy.deepcopy(entry['composition']),
            portion_factor='1',composition_summary=summarize(entries))
        snapshot['summary']=snapshot_summary(snapshot)
    else:
        snapshot.update(schema_version='2.1',composition=copy.deepcopy(entry['composition']),portion_factor='1',composition_summary=summarize(entries))
        snapshot['summary']=snapshot_summary(snapshot)
    return snapshot


def validate_document(document,user_id):
    ni.enabled();validate_json_document(document,'nutrition_import_2_1')
    if document['user_id']!=user_id:raise NutritionError('Documento de otra cuenta.',404)
    owner=db.session.get(__import__('app.models',fromlist=['User']).User,user_id)
    data=document['data'];destination=data['destination']
    prior=db.session.execute(db.select(NutritionImportReceipt).where(NutritionImportReceipt.user_id==user_id,NutritionImportReceipt.event_key==data['event_key'])).scalar_one_or_none()
    # The executor compares any existing receipt before choosing skip/conflict;
    # do not reclassify a different review as a newly invalid date instead.
    if prior:return
    if data.get('plan_identity'):
        plan=db.session.execute(db.select(NutritionPlan).where(NutritionPlan.user_id==user_id,NutritionPlan.public_id==data['plan_identity'])).scalar_one_or_none()
        if not plan:raise NutritionError('Plan no encontrado.',404)
        if destination!='plan' or plan.revision!=data['plan_revision']:raise NutritionError('El plan cambió; revisa su revisión actual.',409)
    seen_products=set()
    for entry in data['entries']:
        if entry.get('date'):
            try:date.fromisoformat(entry['date'])
            except ValueError as error:raise NutritionError('Fecha inválida.') from error
        for binding in entry['bindings']:
            proposal=binding.get('new_food')
            if proposal:
                identity=(proposal['name'].strip().casefold(),(proposal.get('brand') or '').strip().casefold())
                existing=db.session.execute(db.select(FoodProduct).where(FoodProduct.user_id==user_id,db.func.lower(FoodProduct.name)==identity[0],db.func.coalesce(db.func.lower(FoodProduct.brand),'')==identity[1])).scalar_one_or_none()
                if existing or identity in seen_products:raise NutritionError('Producto privado duplicado; vincula su identidad existente.',409)
                seen_products.add(identity)
        if destination=='products':
            if not entry['bindings'] or any(not b.get('new_food') for b in entry['bindings']):raise NutritionError('Productos requiere una propuesta privada revisada.')
            resolved_entries(entry,user_id);continue
        if destination=='daily_aggregate':
            if not entry.get('date') or not entry['declaration'] or entry['declaration']['basis_unit']!='portion' or entry['declaration']['basis_amount']!='1':raise NutritionError('Agregado diario requiere fecha y base explícita de 1 día (portion).')
            day=db.session.execute(db.select(DailyNutrition).where(DailyNutrition.user_id==user_id,DailyNutrition.date==date.fromisoformat(entry['date']))).scalar_one_or_none()
            if day:raise NutritionError('Ya existe registro en esta fecha. No se sobrescribe un agregado; omite la fila o revisa comidas distintas.',409)
            continue
        if not entry.get('meal_type') or not entry['bindings']:raise NutritionError('Revisa momento y al menos una identidad/ingrediente; no se inventa composición.')
        if destination in {'consumed','recipes'} and not entry.get('date'):raise NutritionError('Selecciona una fecha explícita para el evento o la referencia de receta.')
        snapshot=meal_snapshot(entry,resolved_entries(entry,user_id),owner.timezone or 'UTC')
        if destination=='recipes':ni.validate_recipe_projection(snapshot)
        if destination=='consumed':
            day=db.session.execute(db.select(DailyNutrition).where(DailyNutrition.user_id==user_id,DailyNutrition.date==date.fromisoformat(entry['date']))).scalar_one_or_none()
            if day and entry.get('conflict_action')!='keep_and_add':raise NutritionError('La fecha contiene datos: confirma que es otro consumo u omite esta fila.',409)
            if day and day.authority is None and entry.get('authority') not in {'derive_items','disjoint_aggregate'}:raise NutritionError('Resuelve el solapamiento del agregado legacy explícitamente.',409)


def apply_document(document,user_id):
    """Official adapter, no internal commit. Caller locks transaction and audits."""
    ni.lock_owner(user_id);validate_document(document,user_id)
    data=document['data'];prior=db.session.execute(db.select(NutritionImportReceipt).where(NutritionImportReceipt.user_id==user_id,NutritionImportReceipt.event_key==data['event_key']).with_for_update()).scalar_one_or_none()
    if prior:
        if prior.raw_payload_json!=document:raise NutritionError('Conflicto de evento; no sobrescribir.',409)
        prior._nutrition_import_replay=True
        return prior
    owner=ni.lock_owner(user_id);counts={'foods':0,'linked_foods':0,'plans':0,'recipes':0,'logs':0,'daily_aggregates':0,'omitted':data.get('omitted_count',0),'rejected':0};planned=[]
    for index,entry in enumerate(data['entries']):
        destination=data['destination'];entries=resolved_entries(entry,user_id,True)
        counts['foods']+=sum('new_food' in b for b in entry['bindings'])
        counts['linked_foods']+=sum('ref' in b for b in entry['bindings'])
        if destination=='products':continue
        if destination=='daily_aggregate':
            from app.services.importers.standard_import_executor import StandardImportExecutor
            values={('calories_kcal' if column=='calories' else column):float(entry['declaration']['nutrients'][n]['value']) for n,column in LEGACY.items() if entry['declaration']['nutrients'].get(n,{}).get('state')=='known'}
            canonical_day={'schema_version':'1.0','record_type':'daily_nutrition','user_id':user_id,'source_type':'uploaded','data':dict(date=entry['date'],**values)}
            validate_json_document(canonical_day,'daily_nutrition')
            day=StandardImportExecutor()._apply_daily_nutrition(canonical_day,user_id,None)
            day.nutrition_summary_json=snapshot_summary({'ingredients':[],'declared_nutrition':entry['declaration'],'composition':{'complete':False},'portion_factor':'1'})
            counts['daily_aggregates']+=1;continue
        snapshot=meal_snapshot(entry,entries,owner.timezone or 'UTC')
        if destination=='plan':
            snapshot.pop('local_date',None);snapshot.pop('timezone',None)
            planned.append({'snapshot':snapshot,**({'planned_for':entry.get('planned_for') or entry.get('date')} if entry.get('planned_for') or entry.get('date') else {})});continue
        if destination=='recipes':
            if db.session.execute(db.select(Recipe.id).where(Recipe.user_id==user_id,Recipe.name==entry['name'])).first():raise NutritionError('Receta con mismo nombre; no actualizar por nombre.',409)
            ni.restore_recipe_snapshot(user_id,entry['name'],snapshot,1);counts['recipes']+=1;continue
        draft=ni.create_draft(user_id,target=entry['date'],name=entry['name'],meal_type=entry['meal_type'])
        draft.public_id=str(uuid5(NAMESPACE_URL,f'health-tracker/nutrition-import/{user_id}/{data["event_key"]}/{index}'))
        draft.snapshot_json=snapshot;draft.accepted_json=list(range(len(entries)));db.session.flush()
        ni.confirm(user_id,ni.confirmation_token(draft),authority=entry.get('authority'));counts['logs']+=1
    if planned:
        snapshot={'schema_version':'2.1','name':data['name'],'meals':planned,'provenance':{'source_sha256':data['source_sha256']}}
        if data.get('plan_identity'):
            plan=db.session.execute(db.select(NutritionPlan).where(NutritionPlan.user_id==user_id,NutritionPlan.public_id==data['plan_identity']).with_for_update().execution_options(populate_existing=True)).scalar_one()
            if plan.revision!=data['plan_revision']:raise NutritionError('El plan cambió; no sobrescribir.',409)
            plan.name=data['name'];plan.snapshot_json=snapshot;plan.revision+=1
        else:db.session.add(NutritionPlan(user_id=user_id,name=data['name'],snapshot_json=snapshot))
        counts['plans']=1
    receipt=NutritionImportReceipt(user_id=user_id,event_key=data['event_key'],source_sha256=data['source_sha256'],raw_payload_json=copy.deepcopy(document),result_json=counts)
    source=db.session.execute(db.select(UploadedFile).where(UploadedFile.user_id==user_id,UploadedFile.sha256==data['source_sha256']).with_for_update()).scalar_one_or_none()
    if source:source.import_status='imported';source.detected_type='nutrition_import';source.error_message=None
    db.session.add(receipt);db.session.flush();return receipt


def use_plan(user_id,key,index,target):
    ni.enabled();ni.lock_owner(user_id)
    plan=db.session.execute(db.select(NutritionPlan).where(NutritionPlan.user_id==user_id,NutritionPlan.public_id==key,NutritionPlan.is_active.is_(True))).scalar_one_or_none()
    if not plan or not 0<=index<len(plan.snapshot_json['meals']):raise NutritionError('Comida del plan no encontrada.',404)
    source=copy.deepcopy(plan.snapshot_json['meals'][index]['snapshot'])
    draft=ni.create_draft(user_id,target=target,name=source['name'],meal_type=source['meal_type'])
    source.update(local_date=draft.snapshot_json['local_date'],timezone=draft.snapshot_json['timezone'])
    draft.snapshot_json=source;draft.accepted_json=[];db.session.flush();return draft


def aggregate_summary(user_id,target):
    receipts=db.session.execute(db.select(NutritionImportReceipt).where(NutritionImportReceipt.user_id==user_id,
        NutritionImportReceipt.raw_payload_json['data']['destination'].as_string()=='daily_aggregate')).scalars()
    for receipt in receipts:
        for entry in receipt.raw_payload_json['data']['entries']:
            if entry.get('date')==target.isoformat():
                return snapshot_summary({'ingredients':[],'declared_nutrition':entry['declaration'],'composition':{'complete':False},'portion_factor':'1'})
    return None


def edit_plan(user_id,key):
    ni.enabled();ni.lock_owner(user_id)
    plan=db.session.execute(db.select(NutritionPlan).where(NutritionPlan.user_id==user_id,NutritionPlan.public_id==key,NutritionPlan.is_active.is_(True))).scalar_one_or_none()
    if not plan:raise NutritionError('Plan no encontrado.',404)
    rows=[]
    for index,meal in enumerate(plan.snapshot_json['meals']):
        snap=meal['snapshot'];declaration=snap.get('declared_nutrition') or {};composition=snap.get('composition') or {}
        evidence=copy.deepcopy(declaration.get('provenance',{}).get('evidence',{'file':plan.name,'plan_revision':plan.revision,'row':index+1}))
        rows.append({'name':snap['name'],'meal_type':snap['meal_type'],'planned_for':meal.get('planned_for',''),'confirmed':False,'skip':False,'warnings':[],
            'evidence':evidence,'original':copy.deepcopy(declaration.get('original_values',{'name':snap['name']})),
            'declaration':copy.deepcopy(declaration.get('nutrients',{})), 'basis_amount':declaration.get('basis_amount'),
            'basis_unit':declaration.get('basis_unit'),'amount':declaration.get('basis_amount') or composition.get('total_mass_g'),
            'unit':declaration.get('basis_unit') or ('g' if composition.get('total_mass_g') else None),
            'composition_complete':composition.get('complete',True),'total_mass_g':composition.get('total_mass_g'),
            'ingredients':[{'ref':part['food']['ref'],'food_revision':str(part['food']['revision']),'amount':part['amount'],'unit':part['unit'],
                 **({'serving_id':part['serving_id']} if part.get('serving_id') else {})} for part in snap['ingredients']]})
    source=plan.snapshot_json['provenance'].get('source_sha256') or ni.hash_document(plan.snapshot_json)
    draft=NutritionImportDraft(user_id=user_id,source_sha256=source,source_json={'profile':'reviewed_plan_revision','classification_hint':'plan','warnings':[],
        'plan_identity':plan.public_id,'plan_revision':plan.revision},review_json={'name':plan.name,'destination':'plan','rows':rows})
    db.session.add(draft);db.session.flush();return draft


def row_preview(row,index):
    """Read-only comparison; never changes a row's human confirmation state."""
    document=canonical(row,only_index=index);entry=document['data']['entries'][0]
    entries=resolved_entries(entry,row.user_id)
    if document['data']['destination'] in {'products','daily_aggregate'}:
        return {'summary':summarize(entries),'composition':summarize(entries),'declared':entry['declaration']['nutrients'] if entry['declaration'] else {},'ingredients':entries}
    from app.models import User
    owner=db.session.get(User,row.user_id)
    snapshot=meal_snapshot(entry,entries,owner.timezone or 'UTC')
    return {'summary':snapshot['summary'],'composition':snapshot.get('composition_summary',snapshot['summary']),
            'declared':snapshot.get('declared_nutrition',{}).get('nutrients',{}),'ingredients':entries}
