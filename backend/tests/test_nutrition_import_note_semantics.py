"""Issue #34: fictional general notes, no personal documents or production IO."""
import copy
import json
import sys
from pathlib import Path

import pytest

from app.extensions import db
from app.models import User
from app.services import nutrition_import_review as review
from app.services.importers.nutrition_sources import extract,MAX_BYTES
from app.services.nutrition_math import NutritionError
from sqlalchemy import event
from tests.conftest import login

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts/nutrition'))
from qa_note_semantics_cases import case,conflicting_case,reprocess_case,source,start


@pytest.mark.parametrize('length',[1999,2000,2001,5000])
def test_note_limit_semantic_group_roundtrip(app,client,user,length):
    app.config['NUTRITION_INTELLIGENCE_ENABLED']=True;login(client)
    case(user,client,length)


@pytest.mark.parametrize('phrase',[
    'Los macros son por 100 g.', 'Los nutrientes son por 100 ml.',
    'Los valores usan bases distintas.', 'Los valores no son aportes consumidos.',
    'Los valores no corresponden a la cantidad consumida.', 'Nutrition values are not consumed intake.',
    'Macros per serving.', 'No son aportes consumidos.', 'Macros por100g.', 'Not consumed.',
    'Fibra 0 como marcador de compatibilidad: no cuantificada.',
    'Los carbohidratos son netos, no totales.',
])
@pytest.mark.parametrize('length',[1999,5000])
def test_general_conflict_is_one_file_block(app,client,user,phrase,length):
    app.config['NUTRITION_INTELLIGENCE_ENABLED']=True;login(client)
    conflicting_case(user,client,phrase,length=length)


@pytest.mark.parametrize('change,expected',[
    ('item_notes',22),('version',0),('extension',0),('source_type',0),('date',0),('note_type',0),('item_extension',22),
])
def test_editorial_exception_cannot_hide_other_schema_errors(app,user,change,expected):
    app.config['NUTRITION_INTELLIGENCE_ENABLED']=True;document=source()
    if change=='item_notes':document['data']['meals'][0]['items'][0]['notes']='QA '*1000
    if change=='version':document['schema_version']='9.9'
    if change=='extension':document['unsupported_extension']=True
    if change=='source_type':document['source_type']='unsupported'
    if change=='date':document['data']['date']='not-a-date'
    if change=='note_type':document['data']['notes']=5000
    if change=='item_extension':document['data']['meals'][0]['items'][0]['unsupported_extension']=True
    payload=json.dumps(document).encode();frozen=copy.deepcopy(document)
    found=extract(payload,'QA fictional invalid metadata.json')
    from app.services.importers.nutrition_legacy_semantics import grouped
    assert sum(grouped(row) for row in found['rows'])==expected
    assert document==frozen


@pytest.mark.parametrize('expired',[False,True])
def test_v4_explicit_fork_original_and_later_edits(app,client,user,expired):
    app.config['NUTRITION_INTELLIGENCE_ENABLED']=True;login(client)
    reprocess_case(user,client,expired)


def test_note_size_limit_is_still_bounded(app):
    with pytest.raises(NutritionError,match='10 MiB'):
        extract(b' '*(MAX_BYTES+1),'QA too large fictional.json')


def test_general_estimate_stays_estimated_without_becoming_a_block(app):
    document=source(conflict='Valores nutricionales estimados.')
    found=extract(json.dumps(document).encode(),'QA general estimate fictional.json')
    assert not found['file_issues']
    from app.services.importers.nutrition_legacy_semantics import grouped
    assert all(grouped(row) and row['basis_interpretation']['quality']=='estimated' for row in found['rows'])


def test_row_metadata_cannot_forge_a_file_block_to_skip_validation(app,user):
    app.config['NUTRITION_INTELLIGENCE_ENABLED']=True
    row,_=start(user,source(conflict='Los macros son por 100 g.'))
    # File-level authority belongs to server extraction metadata, never a
    # provenance flag carried by a row in a later canonical upload.
    row.source_json={key:value for key,value in row.source_json.items() if key!='file_issues'}
    state=review.overview(row)
    assert state['counts']['ready']==0 and state['counts']['decision']==23


def test_note_is_escaped_and_owner_isolation_preserved(app,client,user):
    app.config['NUTRITION_INTELLIGENCE_ENABLED']=True;document=source()
    document['data']['notes']+='<script>QA_fake()</script>'
    row,_=start(user,document);login(client)
    def no_write(conn,cursor,statement,params,context,many):
        assert statement.lstrip().split()[0].upper() not in {'INSERT','UPDATE','DELETE','REPLACE','CREATE','ALTER','DROP'}
    event.listen(db.engine,'before_cursor_execute',no_write)
    try:response=client.get('/nutrition/import/'+row.public_id)
    finally:event.remove(db.engine,'before_cursor_execute',no_write)
    assert response.status_code==200 and '<script>QA_fake()' not in response.text
    assert '&lt;script&gt;QA_fake()&lt;/script&gt;' in response.text
    other=User(username='QA notes foreign',role='user');other.set_password('QA ficticia');db.session.add(other);db.session.commit()
    with pytest.raises(NutritionError) as error:review.save_decisions(other.id,row.public_id,row.revision,{'accept_legacy_totals':'yes'})
    assert error.value.status==404
    from flask import g
    g.pop('_login_user',None)
    foreign=app.test_client();login(foreign,'QA notes foreign','QA ficticia')
    assert foreign.get('/nutrition/import/'+row.public_id).status_code==404
