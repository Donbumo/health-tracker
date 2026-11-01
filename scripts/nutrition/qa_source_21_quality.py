"""Compare the reviewed adapter and its correction using fictional data only."""
import copy
import json
import subprocess
import sys
import types
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
from app.services.importers.nutrition_source_21 import source_rows
from qa_source_21_fixtures import mixed_quality

baseline='8358dcf57dc746272d916fd99c6bc1ec82828dbd'
path='backend/app/services/importers/nutrition_source_21.py'
old=types.ModuleType('qa_reviewed_source21')
exec(compile(subprocess.check_output(['git','show',baseline+':'+path]),path,'exec'),old.__dict__)
document=mixed_quality()
before=old.source_rows(copy.deepcopy(document),{'method':'fictional_qa'},strict=False)
after=source_rows(copy.deepcopy(document),{'method':'fictional_qa'},strict=False)
assert len(before)==len(after)==21
fields=('name','brand','date','meal_type','amount','unit','basis_amount','basis_unit','declaration','original')
assert all(all(a.get(k)==b.get(k) for k in fields) for a,b in zip(before,after))
assert [r['source_quality'] for r in after]==['estimated']*4+['mixed']+['verified']*16
assert after[4]['nutrient_quality']['fiber']=='estimated'
assert after[4]['nutrient_quality']['protein']=='verified'
assert all(len(r['declaration'])==30 for r in after)
assert all(r['source_provenance']==r['original']['new_food']['nutrition']['provenance'] for r in after)
report=dict(status='PASS',data='entirely fictional',fixture='mixed-quality.json',
    records=len(after),groups=len({(r['date'],r['meal_type']) for r in after}),nutrients=len(after[0]['declaration']),
    before_estimate_badges=sum(r['source_quality']=='estimated' for r in before),
    after_estimate_badges=sum(r['source_quality'] in {'estimated','mixed'} for r in after),
    fully_estimated=sum(r['source_quality']=='estimated' for r in after),
    mixed=sum(r['source_quality']=='mixed' for r in after),
    verified_source_labels_preserved=sum(r['source_quality']=='verified' for r in after),
    mixed_fiber='estimated',mixed_protein='verified',
    all_nutrient_vectors_and_quantities_exactly_unchanged=True,
    original_and_per_nutrient_provenance_unchanged=True,production_access=False)
out=ROOT/'design/nutrition-source-21/qa/quality-review'
out.mkdir(parents=True,exist_ok=True)
(out/'classification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report))
