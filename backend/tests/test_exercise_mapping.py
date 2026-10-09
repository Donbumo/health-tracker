"""Fictional QA only. No real routines, accounts, media downloads or NAS."""
import copy
import re
from urllib.parse import urlencode

import pytest
from app.extensions import db
from app.models import Exercise, ExerciseAlias, ExternalExercise, User, TrainingSet
from app.services.exercise_catalog import external_catalog, sync_catalog
from app.services.exercise_identity import get_or_create_exercise, find_exercise_identity
from app.services.exercise_mapping import candidates, confirm_link, decision_token, review_items, review_target
from app.services.gym_programs import GymError, catalog, resolve_draft
from app.services.gym_media import media_catalog, media_projection
from app.services.gym_sessions import complete_set
from app.services.importers.routine_draft import DeterministicParser
from tests.conftest import login
from tests.test_external_exercise_catalog import app, FixtureSource, sample
from tests.test_gym_training import program, start


@pytest.fixture
def refs(app):
    sync_catalog(source=FixtureSource(entries=[sample('QA_A','QA Machine Press'),sample('QA_B','QA Alternate Press')]))
    return external_catalog()


def review_url(name):
    return '/gym/exercise-links/review?' + urlencode({'name':name})


def test_read_only_summary_candidates_and_none(app,client,user,refs):
    identity,_=get_or_create_exercise(user,'QA personal press')
    login(client)
    assert b'1 pendientes' in client.get('/training-plans').data
    assert client.get('/gym/exercise-links').status_code==200
    response=client.get(review_url(identity.canonical_name)+'&q=QA')
    assert response.status_code==200
    assert response.text.count('name="reference_id"')==2
    assert 'Demostración de QA' in response.text and 'Fictional QA instruction' in response.text
    assert 'Músculos' in response.text and 'Ver ejercicio' in response.text
    assert client.post('/gym/exercise-links/review',data={'name':identity.canonical_name,'action':'none'}).status_code==302
    db.session.refresh(identity)
    assert identity.external_catalog_id is None and db.session.query(ExerciseAlias).count()==0


def test_explicit_change_preserves_history_names_alias_and_future_import(app,client,user,refs):
    draft=DeterministicParser().parse(b'Day,Exercise,Sets,Reps\nQA Day,QA historical press,2,8','qa.csv','QA mapping history')
    draft.days[0]['exercises'][0]['create_new']=True
    plan=program(user,draft)
    session=start(user,plan)
    complete_set(user,session.public_id,1,1,{'load':'10','unit':'kg','reps':'8','rir':'2'})
    db.session.commit()
    identity=catalog(user)[0]
    before=(identity.public_id,identity.canonical_name,copy.deepcopy(plan.versions[0].content),session.exercises[0].name)
    login(client)
    for ref in refs:
        item,_,_=review_target(user,identity.canonical_name)
        token=decision_token(user,item,ref)
        response=client.post('/gym/exercise-links/review',data={'name':item['name'],'action':'link','reference_id':ref.public_id,'token':token,'user_id':'999999'})
        assert response.status_code==302
        db.session.refresh(identity)
        assert identity.external_catalog_id==ref.id
        assert before==(identity.public_id,identity.canonical_name,plan.versions[0].content,session.exercises[0].name)
        assert db.session.query(TrainingSet).count()==1
        assert find_exercise_identity(user,item['name']).id==identity.id
        assert media_projection(catalog(user),media_catalog(),external_catalog())({'exercise_id':identity.public_id})['media_asset_id']=='catalog:'+ref.public_id
        assert client.get('/gym/sessions/'+session.public_id).status_code==200
        assert 'Cambiar vínculo' in client.get('/gym/exercise-links').text
        # Retrying a completed submission neither duplicates aliases nor rewrites history.
        confirm_link(user,item['name'],ref.public_id,token);db.session.commit()
    assert db.session.query(ExerciseAlias).filter_by(user_id=user).count()==1
    imported=DeterministicParser().parse(b'Day,Exercise,Sets,Reps\nQA Day,QA historical press,2,8','qa.csv','QA repeat')
    resolve_draft(imported,user)
    assert imported.days[0]['exercises'][0]['resolved_exercise_id']==identity.public_id


def test_cross_owner_get_post_token_and_reference_tampering(app,client,user,refs):
    mine,_=get_or_create_exercise(user,'QA shared label')
    item,_,_=review_target(user,mine.canonical_name); token=decision_token(user,item,refs[0])
    other=User(username='mapping-other-qa',role='user');other.set_password('fictional-password')
    db.session.add(other);db.session.commit()
    theirs,_=get_or_create_exercise(other.id,'QA private label')
    same,_=get_or_create_exercise(other.id,mine.canonical_name)
    login(client)
    assert client.get(review_url(theirs.canonical_name)).status_code==404
    assert client.post('/gym/exercise-links/review',data={'name':theirs.canonical_name,'action':'none'}).status_code==404
    with pytest.raises(GymError): confirm_link(user,mine.canonical_name,refs[1].public_id,token)
    db.session.rollback()
    with pytest.raises(GymError): confirm_link(other.id,same.canonical_name,refs[0].public_id,token)
    db.session.rollback()
    assert mine.external_catalog_id is None and same.external_catalog_id is None


def test_stale_catalog_link_and_invalid_token_rejected(app,user,refs):
    identity,_=get_or_create_exercise(user,'QA concurrent press')
    item,_,_=review_target(user,identity.canonical_name)
    old=decision_token(user,item,refs[0]);other=decision_token(user,item,refs[1])
    confirm_link(user,item['name'],refs[1].public_id,other);db.session.commit()
    with pytest.raises(GymError,match='cambió'): confirm_link(user,item['name'],refs[0].public_id,old)
    db.session.rollback()
    item,_,_=review_target(user,identity.canonical_name);token=decision_token(user,item,refs[0])
    from app.models import ExerciseCatalogSource
    db.session.get(ExerciseCatalogSource,'free-exercise-db').active_snapshot='b'*40;db.session.commit()
    with pytest.raises(GymError,match='cambió'): confirm_link(user,item['name'],refs[0].public_id,token)
    db.session.rollback()
    with pytest.raises(GymError): confirm_link(user,item['name'],refs[0].public_id,'tampered')
    db.session.rollback()
    refs[0].available=False;db.session.commit()
    with pytest.raises(GymError): confirm_link(user,item['name'],refs[0].public_id,token)


def test_csrf_and_auth_required(app,client,user,refs):
    identity,_=get_or_create_exercise(user,'QA csrf exercise')
    assert client.get('/gym/exercise-links').status_code==302
    login(client)
    app.config['WTF_CSRF_ENABLED']=True
    assert client.post('/gym/exercise-links/review',data={'name':identity.canonical_name,'action':'none'}).status_code==400
    response=client.get(review_url(identity.canonical_name)+'&q=QA')
    csrf=re.search(r'name="csrf_token" value="([^"]+)"',response.text).group(1)
    item,_,_=review_target(user,identity.canonical_name)
    assert client.post('/gym/exercise-links/review',data={'name':item['name'],'action':'link','reference_id':refs[0].public_id,'token':decision_token(user,item,refs[0]),'csrf_token':csrf}).status_code==302


def test_search_hints_are_only_suggestions_and_exclude_calf_press(app,user):
    # Public movement vocabulary in explicitly fictional source fixtures.
    sync_catalog(source=FixtureSource(entries=[sample('QA_Leg','QA Leg Press'), sample('QA_Narrow','QA Narrow Stance Leg Press'),dict(sample('QA_Calf','QA Calf Press On The Leg Press Machine'),primaryMuscles=['calves'])]))
    results=candidates('prensa',[],external_catalog())
    assert len(results)==2 and all('Calf' not in r.name for r in results)
    assert db.session.query(Exercise).count()==0
    assert len(candidates('QA unknown',[],external_catalog(),'QA'))==3


def test_no_catalog_no_match_does_not_write(app,client,user):
    identity,_=get_or_create_exercise(user,'QA unsupported movement')
    login(client)
    assert 'No encontramos' in client.get(review_url(identity.canonical_name)).text
    assert db.session.query(ExternalExercise).count()==0
    assert identity.external_catalog_id is None


def test_imported_name_without_identity_creates_only_on_confirmation(app,client,user,refs):
    from app.services.gym_programs import publish_program_document, standard_document
    draft=DeterministicParser().parse(b'Day,Exercise,Sets,Reps\nQA Day,QA legacy import,2,8','qa.csv','QA legacy routine')
    plan,_=publish_program_document(standard_document(draft,user),user);db.session.commit()
    history=copy.deepcopy(plan.versions[0].content)
    login(client)
    assert 'QA legacy import' in client.get('/gym/exercise-links').text
    assert db.session.query(Exercise).filter_by(user_id=user).count()==0
    item,_,_=review_target(user,'QA legacy import')
    token=decision_token(user,item,refs[0])
    identity=confirm_link(user,item['name'],refs[0].public_id,token);db.session.commit()
    confirm_link(user,item['name'],refs[0].public_id,token);db.session.commit()
    assert db.session.query(Exercise).filter_by(user_id=user).count()==1
    assert db.session.query(ExerciseAlias).filter_by(user_id=user).count()==1
    assert plan.versions[0].content==history
    assert find_exercise_identity(user,item['name']).id==identity.id


def test_none_keeps_existing_link_and_query_is_bounded(app,client,user,refs):
    identity,_=get_or_create_exercise(user,'QA linked')
    identity.external_catalog_id=refs[0].id;db.session.commit();login(client)
    assert client.post('/gym/exercise-links/review',data={'name':identity.canonical_name,'action':'none'}).status_code==302
    db.session.refresh(identity);assert identity.external_catalog_id==refs[0].id
    assert client.get(review_url('<script>QA</script>')).status_code==404


def test_explicit_identity_in_imported_document_keeps_alias_and_progress(app,user,refs):
    from app.services.gym_programs import publish_program_document, standard_document
    identity,_=get_or_create_exercise(user,'QA stable identity')
    draft=DeterministicParser().parse(b'Day,Exercise,Sets,Reps\nQA Day,QA visible alias,2,8','qa.csv','QA explicit identity')
    doc=standard_document(draft,user)
    doc['data']['weeks'][0]['days'][0]['exercises'][0]['exercise_id']=identity.public_id
    plan,_=publish_program_document(doc,user);db.session.commit()
    item,_,_=review_target(user,'QA visible alias')
    assert item['identity'].public_id==identity.public_id
    confirm_link(user,item['name'],refs[0].public_id,decision_token(user,item,refs[0]));db.session.commit()
    assert find_exercise_identity(user,item['name']).public_id==identity.public_id
    assert db.session.query(Exercise).filter_by(user_id=user).count()==1
    assert plan.versions[0].content==doc
