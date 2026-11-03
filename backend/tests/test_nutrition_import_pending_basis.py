"""Issue #38: fictional source annotations, never private production records."""
import copy
import json
import sys
from pathlib import Path
from decimal import Decimal
from datetime import date,timedelta

import pytest
from sqlalchemy import event

from app.extensions import db
from app.models import MealLog,FoodProduct,NutritionImportReceipt,User
from app.services import nutrition_import as imports,nutrition_import_review as review
from app.services.nutrition_math import NUTRIENTS,NutritionError
from app.services.validation import validate_json_document
from tests.conftest import login
from tests.test_nutrition_import_summary import token
from tests.test_nutrition_import_source_21 import app  # Same guarded disposable MariaDB fixture.

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/nutrition'))
from qa_pending_basis_fixtures import source18


def start(app,user,document=None):
    app.config['NUTRITION_INTELLIGENCE_ENABLED']=True
    document=document or source18();validate_json_document(document,'nutrition_import_2_1')
    row=imports.start(user,json.dumps(document).encode(),'QA fictional basis 18.json');db.session.commit()
    return row


def group(client,row):
    return client.post('/nutrition/import/'+row.public_id+'/decisions',data=dict(revision=row.revision,accept_declared_bases='yes'))


def test_declared_values_visible_then_one_group_accepts_without_domain_writes(app,client,user):
    from app.services.nutrition_intelligence import daily_summary
    row=start(app,user);login(client);before=copy.deepcopy(row.review_json);source=copy.deepcopy(row.source_json);revision=row.revision
    no_dml=lambda conn,cursor,stmt,params,context,many: (_ for _ in ()).throw(AssertionError('GET wrote')) if stmt.lstrip().split()[0].upper() in {'INSERT','UPDATE','DELETE','CREATE','ALTER','DROP'} else None
    event.listen(db.engine,'before_cursor_execute',no_dml)
    try:
        view=review.overview(row);page=client.get('/nutrition/import/'+row.public_id)
        assert view['counts']==dict(ready=0,decision=18,invalid=0,omitted=0)
        assert view['declared_basis_count']==18 and view['legacy_total_count']==0
        assert all(r['preview'] is None and len(r['declared_values'])==30 for r in view['records'])
        assert view['quality_counts']['unknown']==0 and view['quality_counts']['declared_pending']==18
        assert all(n['value'] is None for n in view['batch_summary'].values())
        assert all(n['value'] is None for n in daily_summary(user,date(2026,2,14))['summary'].values())
    finally:event.remove(db.engine,'before_cursor_execute',no_dml)
    assert page.status_code==200 and page.text.count('name="accept_declared_bases"')==1
    assert page.text.count('Declarado:')==72 and 'Pendiente de base' in page.text
    assert 'Aportes pendientes de base; aún no contabilizados.' in page.text
    assert row.review_json==before and row.source_json==source
    db.session.rollback()
    assert group(client,row).status_code==302
    fresh=imports.owned(user,row.public_id);view=review.overview(fresh)
    assert view['counts']==dict(ready=18,decision=0,invalid=0,omitted=0)
    assert fresh.revision==revision+1 and len(fresh.source_json['semantic_actions'])==1
    assert fresh.source_json['semantic_actions'][0]['count']==18
    assert all(a['original']==b['original'] and a['declaration']==b['declaration'] for a,b in zip(before['rows'],fresh.review_json['rows']))
    assert all(not r['confirmed'] for r in fresh.review_json['rows'])
    for key in NUTRIENTS:
        total=sum(Decimal(r['item']['declaration'][key]['value']) for r in view['records'])
        assert Decimal(view['batch_summary'][key]['value'])==total
        assert sum(Decimal(g['summary'][key]['value']) for g in view['groups'])==total
    assert view['quality_counts']['estimated']==9
    document=review.document(fresh);validate_json_document(document,'nutrition_import_2_1')
    assert [e['declaration']['original_values'] for e in document['data']['entries']]==[r['original'] for r in before['rows']]
    assert db.session.query(MealLog).count()==db.session.query(FoodProduct).count()==db.session.query(NutritionImportReceipt).count()==0
    page=client.get('/nutrition/import/'+fresh.public_id)
    assert 'name="token" value=""' not in page.text and 'required checked' not in page.text
    assert client.post('/nutrition/import/'+fresh.public_id+'/decisions',data=dict(revision=revision,accept_declared_bases='yes')).status_code==409
    assert group(client,fresh).status_code==422


@pytest.mark.parametrize('exception',['annotation_quantity','annotation_unit','contradiction','edited_basis','binding','ambiguous_carbs','forged_control'])
def test_group_accepts_only_verified_rows_and_preserves_exception(app,client,user,exception):
    document=source18();entry=document['data']['entries'][-1];annotation=entry['declaration']['provenance']['basis_interpretation']
    if exception=='annotation_quantity':annotation['consumed_quantity']='999'
    if exception=='annotation_unit':annotation['basis_unit']='ml'
    if exception=='contradiction':entry['declaration']['provenance']['notes']='Los valores son por 100 g.'
    if exception=='forged_control':annotation.update(kind='explicit_basis',status='proposed',origin='nutrition_import_2_1',source_inputs={})
    row=start(app,user,document);login(client)
    if exception in {'edited_basis','binding','ambiguous_carbs'}:
        data=copy.deepcopy(row.review_json);item=data['rows'][-1]
        if exception=='edited_basis':item['basis_amount']='100'
        if exception=='binding':item['ingredients']=[dict(ref='catalog:00000000-0000-0000-0000-000000000000',amount='1',unit='g',food_revision='1')]
        if exception=='ambiguous_carbs':item['carbohydrate_proposal']={'state':'known','value':'1','unit':'g'}
        row.review_json=data;db.session.commit()
    exception_before=copy.deepcopy(row.review_json['rows'][-1])
    view=review.overview(row);assert view['declared_basis_count']==17
    db.session.rollback();assert group(client,row).status_code==302
    assert row.review_json['rows'][-1]==exception_before
    view=review.overview(row);assert view['counts']['ready']==17 and view['counts']['decision']==1
    assert view['records'][-1]['declared_values'] and view['records'][-1]['preview'] is None


def test_zero_unknown_trace_limit_and_canonical_snapshots_roundtrip(app,client,user):
    from app.services.nutrition_portability import export_bundle,semantic_snapshot
    from app.services.exporters.user_data import build_user_data_document
    from app.services.account_restore import AccountRestoreService
    document=source18()
    for entry in document['data']['entries']:
        vector=entry['declaration']['nutrients'];vector['energy']['value']='0'
        vector['vitamin_d'].update(state='unknown',value=None)
        vector['iron'].update(state='trace',value=None)
        vector['zinc'].update(state='below_limit',value=None,limit='0.1')
    row=start(app,user,document);login(client)
    page=client.get('/nutrition/import/'+row.public_id)
    assert 'Declarado: 0' in page.text and review.overview(row)['records'][0]['declared_values']['energy']['value']=='0'
    assert 'Declaraciones pendientes · no contabilizado' in page.text
    db.session.rollback();assert group(client,row).status_code==302
    view=review.overview(row);assert view['batch_summary']['energy']['value']=='0'
    assert all(view['batch_summary'][k]['value'] is None for k in ['vitamin_d','iron','zinc'])
    before=copy.deepcopy(view['batch_summary']);canonical=review.document(row)
    signed=token(client,row);assert client.post('/nutrition/import/'+row.public_id+'/confirm',data=dict(revision=row.revision,token=signed)).status_code==422
    assert client.post('/nutrition/import/'+row.public_id+'/confirm',data=dict(revision=row.revision,token=signed,consent_consumed='yes')).status_code==200
    from app.services.nutrition_intelligence import daily_summary
    from app.services.nutrition_micros import overview
    assert daily_summary(user,date(2026,2,14))['summary']==before
    assert overview(user,date(2026,2,14),7,'iron')['qualifiers']['iron']['trace']==18
    logs=db.session.scalars(db.select(MealLog).where(MealLog.user_id==user).order_by(MealLog.id)).all()
    assert len(logs)==18
    assert all(log.snapshot_json['declared_nutrition']['nutrients']==entry['declaration']['nutrients'] for log,entry in zip(logs,canonical['data']['entries']))
    target=User(username='QA pending basis restore',role='user');target.set_password('QA only');db.session.add(target);db.session.commit()
    payload=build_user_data_document(db.session.get(User,user),user);restore=AccountRestoreService();plan=restore.preview(payload,user_id=target.id)
    assert restore.commit(payload,user_id=target.id,confirmation_token=plan['confirmation_token'])['committed']
    assert [semantic_snapshot(r['snapshot']) for r in export_bundle(user)['logs']]==[semantic_snapshot(r['snapshot']) for r in export_bundle(target.id)['logs']]


def test_mixed_current_and_editorial_preserves_existing_decision_and_audit(app,client,user):
    document=source18();document['data']['entries'][0]['declaration']['provenance']['basis_interpretation']=dict(
        kind='explicit_basis',status='explicit',origin='nutrition_import_2_1',quality='estimated')
    row=start(app,user,document);login(client)
    data=copy.deepcopy(row.review_json);data['rows'][1]['name']='QA already reviewed identity'
    data['rows'][1]['corrections']=[dict(kind='QA retained decision',revision=1)];row.review_json=data;db.session.commit()
    before=copy.deepcopy(row.review_json)
    view=review.overview(row);assert view['counts']['ready']==1 and view['declared_basis_count']==17
    db.session.rollback();assert group(client,row).status_code==302
    assert review.overview(row)['counts']['ready']==18
    assert row.review_json['rows'][0]==before['rows'][0]
    assert row.review_json['rows'][1]['name']==before['rows'][1]['name']
    assert row.review_json['rows'][1]['corrections']==before['rows'][1]['corrections']
    assert row.source_json['semantic_actions']==[dict(action='accept_declared_bases',count=17,revision=2)]


def test_one_changed_basis_invalidates_only_that_row_and_old_signature(app,client,user):
    row=start(app,user);login(client);assert group(client,row).status_code==302
    view=review.overview(row);old_preview=copy.deepcopy(view['records']);old_revision=row.revision;signed=token(client,row)
    assert client.post('/nutrition/import/'+row.public_id+'/decisions',data=dict(revision=row.revision,edit_index='1',r1_basis_amount='100')).status_code==302
    view=review.overview(row)
    assert view['counts']['ready']==17 and view['counts']['decision']==1
    assert view['records'][1]['declared_values'] and view['records'][1]['preview'] is None
    assert all(a['preview']==b['preview'] for i,(a,b) in enumerate(zip(view['records'],old_preview)) if i!=1)
    assert client.post('/nutrition/import/'+row.public_id+'/confirm',data=dict(revision=old_revision,token=signed,consent_consumed='yes')).status_code==409
    assert group(client,row).status_code==422
    assert db.session.query(MealLog).count()==0


@pytest.mark.parametrize('expired',[False,True])
def test_editorial_source_fork_preserves_prior_revision_and_ttl(app,client,user,expired):
    from app.services.nutrition_import_reprocess import reprocess
    row=start(app,user);login(client)
    row.source_json=dict(row.source_json,extractor_version='nutrition-source-21-v6');db.session.commit()
    if expired:row.created_at-=timedelta(days=2);db.session.commit()
    frozen=copy.deepcopy(row.review_json);source=copy.deepcopy(row.source_json);created=row.created_at;revision=row.revision
    if expired:assert group(client,row).status_code==409
    fresh=reprocess(user,row.public_id,row.revision);db.session.commit()
    assert fresh.id!=row.id and fresh.source_sha256==row.source_sha256
    assert row.review_json==frozen and row.source_json==source and row.created_at==created and row.revision==revision
    assert fresh.source_json['reprocess_pending']
    assert client.post('/nutrition/import/'+fresh.public_id+'/decisions',data=dict(revision=fresh.revision,accept_previous='yes')).status_code==302
    assert review.overview(fresh)['declared_basis_count']==18
    assert group(client,fresh).status_code==302 and review.overview(fresh)['counts']['ready']==18


def test_owner_csrf_revision_and_final_consent_are_separate(app,client,user):
    row=start(app,user);login(client);revision=row.revision
    app.config['WTF_CSRF_ENABLED']=True
    assert group(client,row).status_code==400
    app.config['WTF_CSRF_ENABLED']=False
    assert client.post('/nutrition/import/'+row.public_id+'/decisions',data=dict(revision=revision+1,accept_declared_bases='yes')).status_code==409
    assert group(client,row).status_code==302
    signed=token(client,row)
    assert client.post('/nutrition/import/'+row.public_id+'/confirm',data=dict(revision=row.revision,token='bad',consent_consumed='yes')).status_code==409
    assert client.post('/nutrition/import/'+row.public_id+'/confirm',data=dict(revision=row.revision,token=signed)).status_code==422
    other=User(username='QA basis other',role='user');other.set_password('QA only');db.session.add(other);db.session.commit()
    from flask import g
    g.pop('_login_user',None);foreign=app.test_client();login(foreign,username=other.username,password='QA only')
    assert foreign.get('/nutrition/import/'+row.public_id).status_code==404 and group(foreign,row).status_code==404
    assert db.session.query(MealLog).count()==db.session.query(FoodProduct).count()==db.session.query(NutritionImportReceipt).count()==0


@pytest.mark.parametrize('problem',['tampered_original','file_conflict','changed_label'])
def test_unverified_source_cannot_gain_group_authority(app,client,user,problem):
    row=start(app,user);login(client)
    if problem=='tampered_original':
        from app.models import UploadedFile
        upload=db.session.get(UploadedFile,row.source_json['upload_id'])
        path=Path(app.config['UPLOAD_ROOT'])/f'user_{user}'/upload.stored_filename
        path.write_bytes(path.read_bytes()+b' ')
    elif problem=='file_conflict':row.source_json=dict(row.source_json,file_issues=['QA contradictory source basis']);db.session.commit()
    else:
        data=copy.deepcopy(row.review_json)
        for item in data['rows']:item['unit_label']='QA changed unit label'
        row.review_json=data;db.session.commit()
    before=copy.deepcopy(row.review_json);revision=row.revision
    assert review.overview(row)['declared_basis_count']==0
    db.session.rollback();assert group(client,row).status_code==422
    assert row.review_json==before and row.revision==revision


def test_pending_annotation_survives_other_official_draft_post(app,client,user):
    row=start(app,user);login(client)
    assert client.post('/nutrition/import/'+row.public_id+'/decisions',data=dict(revision=row.revision,edit_index='1',r1_name='QA owner edited name')).status_code==302
    assert review.overview(row)['declared_basis_count']==18
    before=copy.deepcopy(row.review_json['rows'][1]['corrections'])
    assert group(client,row).status_code==302 and review.overview(row)['counts']['ready']==18
    assert row.review_json['rows'][1]['name']=='QA owner edited name' and row.review_json['rows'][1]['corrections']==before


def test_current_extractor_expired_draft_uses_official_recovery(app,client,user):
    row=start(app,user);row.created_at-=timedelta(days=2);db.session.commit();login(client)
    before=copy.deepcopy(row.review_json);created=row.created_at
    assert group(client,row).status_code==409
    response=client.post('/nutrition/import/'+row.public_id+'/recover',data=dict(revision=row.revision))
    assert response.status_code==302 and row.review_json==before and row.created_at==created
    fresh=imports.owned(user,response.location.rsplit('/',1)[-1])
    assert fresh.id!=row.id and review.overview(fresh)['declared_basis_count']==18
    assert group(client,fresh).status_code==302 and review.overview(fresh)['counts']['ready']==18


def test_group_cannot_mix_edits_or_preapprove_an_existing_day(app,client,user):
    from app.models import DailyNutrition
    document=source18()
    for entry in document['data']['entries']:entry.update(conflict_action='keep_and_add',authority='disjoint_aggregate')
    row=start(app,user,document);login(client)
    day=DailyNutrition(user_id=user,date=date(2026,2,14),source='QA existing day',calories=5)
    db.session.add(day);db.session.commit();before=copy.deepcopy(row.review_json);revision=row.revision
    for extra in [dict(r0_amount='999'),dict(destination='consumed'),dict(accept_previous='yes'),{'day_2026-02-14_conflict_action':'keep_and_add'}]:
        assert client.post('/nutrition/import/'+row.public_id+'/decisions',data=dict(revision=revision,accept_declared_bases='yes',**extra)).status_code==422
        assert row.review_json==before and row.revision==revision
    assert group(client,row).status_code==302
    view=review.overview(row);assert view['counts']['ready']==0 and view['counts']['decision']==18
    assert all(not r.get('conflict_action') and not r.get('authority') for r in row.review_json['rows'])
    with pytest.raises(NutritionError):review.document(row)
    assert db.session.get(DailyNutrition,day.id).calories==5
    assert db.session.query(MealLog).count()==db.session.query(FoodProduct).count()==db.session.query(NutritionImportReceipt).count()==0
