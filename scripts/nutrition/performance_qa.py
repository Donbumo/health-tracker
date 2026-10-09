"""Reproducible synthetic local benchmark; no NAS or persistent user database."""
from pathlib import Path
from time import perf_counter
from statistics import median
from uuid import uuid4
import copy,json,sys,tempfile
from sqlalchemy import event,insert
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'backend'))
from app import create_app
from app.extensions import db
from app.models import User
from app.models.nutrition_intelligence import FoodCatalogSource,FoodCatalogRevision,CatalogFood
from app.services.food_catalog import search,stage
from app.services.nutrition_intelligence import create_draft
from tests.test_nutrition_intelligence import food

root=Path(tempfile.mkdtemp(prefix='ht-nutrition-perf-qa-'))
app=create_app({'TESTING':True,'SECRET_KEY':'fictional-nutrition-perf-qa-secret-only',
    'SQLALCHEMY_DATABASE_URI':'sqlite:///'+(root/'qa.sqlite').as_posix(),'SQLALCHEMY_ENGINE_OPTIONS':{},
    'DATA_ROOT':root,'UPLOAD_ROOT':root/'raw','GENERATED_UPLOAD_ROOT':root/'generated','PORTABILITY_ROOT':root/'portable',
    'SCHEMA_ROOT':Path(__file__).resolve().parents[2]/'schemas','NUTRITION_INTELLIGENCE_ENABLED':True})
report=[]
with app.app_context():
    db.create_all()
    owner=User(username='QA performance fictitious',role='user');owner.set_password('QA synthetic password');db.session.add(owner);db.session.flush()
    state=FoodCatalogSource(id='qa_fictional',name='QA synthetic',license='QA synthetic',active_revision='1');db.session.add(state);db.session.flush()
    rev=FoodCatalogRevision(source_id=state.id,revision='1',sha256='0'*64,state='validated',manifest_json={'qa':True});db.session.add(rev);db.session.flush()
    queries=[]
    def count(_conn,_cursor,statement,_parameters,_context,_executemany):queries.append(statement.split(None,1)[0])
    event.listen(db.engine,'before_cursor_execute',count)
    for count_rows in [40,10000]:
        db.session.execute(db.delete(CatalogFood));rows=[]
        for i in range(count_rows):
            doc=copy.deepcopy(food());doc['name']=f'QA fictional food {i:05}';doc['source_food_id']=str(i)
            rows.append({'public_id':str(uuid4()),'catalog_revision_id':rev.id,'source_food_id':str(i),'name':doc['name'],'preparation':doc['preparation'],'snapshot_json':doc})
        started=perf_counter();db.session.execute(insert(CatalogFood),rows);db.session.commit();index_ms=(perf_counter()-started)*1000
        latency=[];query_counts=[]
        for term in ['QA','00020','no-match','food']*5:
            queries.clear();started=perf_counter();search(owner.id,term);latency.append((perf_counter()-started)*1000);query_counts.append(len(queries))
        selected=search(owner.id,'QA',limit=40)
        queries.clear();started=perf_counter();draft=create_draft(owner.id,entries=[{'ref':r['ref'],'amount':'100','unit':'g'} for r in selected])
        build_ms=(perf_counter()-started)*1000;build_queries=len(queries);db.session.rollback()
        report.append({'catalog_foods':count_rows,'search_median_ms':round(median(latency),3),'search_max_ms':round(max(latency),3),
            'search_queries_max':max(query_counts),'builder_ingredients':len(selected),'builder_ms':round(build_ms,3),'builder_queries':build_queries,'insert_ms':round(index_ms,3)})
        assert max(query_counts)<=3 and build_queries<=5
    event.remove(db.engine,'before_cursor_execute',count)
    sample=json.loads((Path(__file__).resolve().parents[2]/'examples/qa/nutrition-intelligence/catalog-sample.json').read_text(encoding='utf-8'))
    started=perf_counter();stage(sample);db.session.commit();stage_ms=(perf_counter()-started)*1000
    output={'reviewed_subset_stage_ms':round(stage_ms,3),'reviewed_subset_foods':len(sample['foods']),'engine':'SQLite temporary on Windows','data':'fictional QA only','nas_measured':False,'results':report}
    target=Path(__file__).resolve().parents[2]/'design/nutrition-intelligence-2/production-qa/performance.json'
    target.write_text(json.dumps(output,indent=2),encoding='utf-8');print(json.dumps(output))
