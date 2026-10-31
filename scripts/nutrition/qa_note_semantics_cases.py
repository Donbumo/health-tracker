"""Issue #34 fictional fixtures/cases shared by SQLite and isolated MariaDB."""
import copy
import hashlib
import json
import os
import re
import subprocess
import types
from datetime import timedelta
from decimal import Decimal
from html import unescape
from pathlib import Path
from unittest.mock import patch

from app.extensions import db
from app.models import FoodProduct,MealLog,NutritionImportDraft,NutritionImportReceipt
from app.services import nutrition_import as imports,nutrition_import_review as review
from app.services.importers import nutrition_legacy_semantics as semantics
from app.services.nutrition_import_reprocess import reprocess
from app.services.nutrition_math import NutritionError
from app.services.validation import validate_json_document
from qa_review_closeout_cases import roundtrip
from qa_note_semantics_fixtures import source


def count(model,uid):
    return db.session.scalar(db.select(db.func.count(model.id)).where(model.user_id==uid))


def fields(row,data,csrf):
    return dict(revision=row.revision,**data,**({'csrf_token':csrf} if csrf else {}))


def start(uid,document):
    payload=json.dumps(document,ensure_ascii=False,sort_keys=True).encode()
    row=imports.start(uid,payload,'QA note semantics fictional.json');db.session.commit()
    assert row.user_id==uid and row.source_sha256==hashlib.sha256(payload).hexdigest()
    assert row.source_json['document_notes']==[document['data']['notes']]
    return row,payload


def case(uid,client,length=5000,csrf=None):
    document=source(length);row,payload=start(uid,document)
    frozen=copy.deepcopy(row.review_json);source_before=copy.deepcopy(row.source_json)
    try:validate_json_document(document,'daily_nutrition')
    except ValueError:assert length>2000
    else:assert length<=2000
    for _ in range(2):
        state=review.overview(row)
        assert state['legacy_total_count']==23 and not state['file_issues']
        assert state['counts']==dict(ready=0,decision=23,invalid=0,omitted=0)
        page=client.get('/nutrition/import/'+row.public_id)
        assert page.status_code==200 and page.text.count('name="accept_legacy_totals"')==1
        assert 'name="consent_consumed" value="yes" required checked' not in page.text
    assert row.review_json==frozen and row.source_json==source_before
    assert not count(MealLog,uid) and not count(FoodProduct,uid) and not count(NutritionImportReceipt,uid)
    posted=client.post('/nutrition/import/'+row.public_id+'/decisions',data=fields(row,{'accept_legacy_totals':'yes'},csrf))
    assert posted.status_code==302;db.session.rollback()
    row=imports.owned(uid,row.public_id)
    assert review.overview(row)['counts']==dict(ready=23,decision=0,invalid=0,omitted=0)
    standard=review.document(row);validate_json_document(standard,'nutrition_import_2_1')
    assert all(Decimal(e['portion_amount'])==Decimal(e['declaration']['basis_amount']) for e in standard['data']['entries'])
    assert imports.verified_original(row)[0].sha256==hashlib.sha256(payload).hexdigest()
    assert row.source_json['document_notes']==[document['data']['notes']]
    # Release the observer's FOR UPDATE lock on the original before the
    # independent HTTP session verifies/locks that same upload at confirmation.
    db.session.rollback()
    page=client.get('/nutrition/import/'+row.public_id)
    signature=unescape(re.search(r'name="token" value="([^"]+)"',page.text)[1])
    data=fields(row,{'token':signature},csrf)
    assert client.post('/nutrition/import/'+row.public_id+'/confirm',data=data).status_code==422
    data['consent_consumed']='yes'
    response=client.post('/nutrition/import/'+row.public_id+'/confirm',data=data)
    assert response.status_code==200,(response.status_code,re.findall(r'<(?:p|div)[^>]*role="alert"[^>]*>([^<]+)',response.text))
    db.session.rollback()
    logs=db.session.scalars(db.select(MealLog).where(MealLog.user_id==uid).order_by(MealLog.id)).all()
    assert len(logs)==23 and count(FoodProduct,uid)==0 and count(NutritionImportReceipt,uid)==1
    assert sum(Decimal(log.snapshot_json['summary']['energy']['value']) for log in logs)==4600
    assert all(Decimal(log.snapshot_json['summary']['fiber']['value'])==0 for log in logs)
    assert all(log.snapshot_json['summary']['vitamin_c']['value'] is None for log in logs)
    assert any(log.snapshot_json['declared_nutrition']['nutrients']['energy']['provenance']['quality']=='estimated' for log in logs)
    assert client.post('/nutrition/import/'+row.public_id+'/confirm',data=data).status_code==200
    roundtrip(uid,'QA note roundtrip '+str(uid))
    assert row.source_json['document_notes']==[document['data']['notes']]
    return dict(notes_length=length,records=23,grouped_proposals=23,group_POSTs=1,ready_after_group=23,
        row_corrections=0,products=0,receipts=1,original_sha_and_notes_preserved=True,roundtrip=True)


def conflicting_case(uid,client,phrase,csrf=None,length=5000):
    document=source(length,phrase);row,payload=start(uid,document)
    state=review.overview(row)
    assert len(state['file_issues'])==1 and state['legacy_total_count']==0
    assert all(not record['item'].get('basis_amount') and not record['item']['basis_interpretation'].get('source_basis') for record in state['records'])
    assert state['counts']==dict(ready=0,decision=0,invalid=0,omitted=0,blocked=23)
    assert all(not record['issues'] and record['state']=='blocked' for record in state['records'])
    page=client.get('/nutrition/import/'+row.public_id)
    assert page.status_code==200 and page.text.count('id="file-basis-title"')==1
    assert 'name="accept_legacy_totals"' not in page.text and 'class="ni-row-problem"' not in page.text
    assert re.search(r'name="token" value=""',page.text)
    assert client.post('/nutrition/import/'+row.public_id+'/decisions',data=fields(row,{'accept_legacy_totals':'yes'},csrf)).status_code==302
    db.session.rollback();row=imports.owned(uid,row.public_id)
    for build in [lambda:review.document(row),lambda:imports.canonical(row)]:
        try:build()
        except NutritionError as error:assert 'nota general' in str(error)
        else:raise AssertionError('General-note conflict bypassed')
    assert not count(MealLog,uid) and not count(FoodProduct,uid) and not count(NutritionImportReceipt,uid)
    assert row.source_sha256==hashlib.sha256(payload).hexdigest() and row.source_json['document_notes']==[document['data']['notes']]
    return dict(records=23,file_blocks=1,row_errors=0,grouped_proposals=0,domain_writes=0)


def prior_v4():
    sha='6ff1e9a1b43a4ec50431ef7afbf64f72784dcefc';modules={}
    for kind,name in [('parser','nutrition_sources.py'),('service','nutrition_import.py'),('semantics','nutrition_legacy_semantics.py')]:
        if os.environ.get('QA_PRIOR_CODE'):
            root=Path(os.environ['QA_PRIOR_CODE']);manifest=json.loads((root/'manifest.json').read_text())['33']
            assert manifest['commit']==sha
            code=(root/'33'/name).read_bytes();assert hashlib.sha256(code).hexdigest()==manifest[kind]
        else:
            path='backend/app/services/'+('importers/' if kind!='service' else '')+name
            code=subprocess.check_output(['git','show',sha+':'+path],cwd=Path(__file__).resolve().parents[2])
        module=types.ModuleType('QA_prior_v4_'+kind);exec(compile(code,sha+'/'+name,'exec'),module.__dict__);modules[kind]=module
    service=modules['service'];service.extract=modules['parser'].extract;service.EXTRACTOR_VERSION=modules['parser'].EXTRACTOR_VERSION
    return service,modules['semantics']


def reprocess_case(uid,client,expired=False,csrf=None):
    service,old_semantics=prior_v4();document=source();payload=json.dumps(document,sort_keys=True).encode()
    with patch.object(semantics,'annotate',old_semantics.annotate):
        old=service.start(uid,payload,'QA v4 retained fictional.json')
    assert old.source_json['extractor_version']=='nutrition-editable-preview-v4'
    assert not review.overview(old)['legacy_total_count']
    service.update(uid,old.public_id,old.revision,'fields',{'index':'0','_section':'identity','name':'QA prior reviewed name'})
    if expired:old.created_at-=timedelta(days=2)
    db.session.commit()
    before=(copy.deepcopy(old.review_json),copy.deepcopy(old.source_json),old.revision,old.created_at)
    # A same-SHA upload does not replace the v4 review or its decisions.
    if not expired:
        again=imports.start(uid,payload,'QA same original reupload.json');db.session.commit();assert again.id==old.id
    result=client.post('/nutrition/import/'+old.public_id+'/reprocess',data=fields(old,{},csrf))
    assert result.status_code==302;db.session.rollback()
    fresh=imports.owned(uid,result.location.rsplit('/',1)[1]);old=imports.owned(uid,old.public_id)
    assert fresh.id!=old.id and fresh.source_json['extractor_version']==imports.EXTRACTOR_VERSION
    assert fresh.source_json['reprocess_pending'] and fresh.source_json['reprocessed_from']==old.public_id
    assert fresh.review_json['rows'][0]['name']=='QA prior reviewed name'
    assert review.overview(fresh)['legacy_total_count']==23
    assert fresh.source_sha256==old.source_sha256==hashlib.sha256(payload).hexdigest()
    assert fresh.source_json['upload_id']==old.source_json['upload_id']
    assert (old.review_json,old.source_json,old.revision,old.created_at)==before
    try:review.document(fresh)
    except NutritionError as error:assert 'campos conservados' in str(error)
    else:raise AssertionError('Retained-fields review bypassed')
    posted=client.post('/nutrition/import/'+fresh.public_id+'/decisions',data=fields(fresh,{'r1_name':'QA later fork name'},csrf))
    assert posted.status_code==302;db.session.rollback();fresh=imports.owned(uid,fresh.public_id)
    assert reprocess(uid,old.public_id,old.revision).id==fresh.id
    assert fresh.review_json['rows'][1]['name']=='QA later fork name'
    review.save_decisions(uid,fresh.public_id,fresh.revision,{'accept_previous':'yes','accept_legacy_totals':'yes'});db.session.commit()
    assert review.overview(fresh)['counts']==dict(ready=23,decision=0,invalid=0,omitted=0)
    assert not count(MealLog,uid) and not count(FoodProduct,uid) and not count(NutritionImportReceipt,uid)
    assert count(NutritionImportDraft,uid)==2 and (old.review_json,old.source_json,old.revision,old.created_at)==before
    return dict(expired=expired,previous_unchanged=True,records=23,grouped_proposals=23,ready_after_group=23,
        original_sha_preserved=True,later_fork_edits_preserved=True,domain_writes=0)
