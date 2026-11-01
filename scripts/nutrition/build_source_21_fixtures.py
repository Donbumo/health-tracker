"""Write fictional A-F fixtures; canonical B has a real synthetic source hash."""
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'backend'))
from qa_source_21_fixtures import source21,variant,mixed_quality

out=ROOT/'examples/qa/nutrition-source-21';out.mkdir(parents=True,exist_ok=True)
for name,doc in [('recoverable-21',source21()),('one-conflict',variant('conflict')),
                 ('partial-net',variant('partial')),('malformed',variant('malformed')),('mixed-quality',mixed_quality())]:
    (out/(name+'.json')).write_text(json.dumps(doc,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
# Independent canonical fixture: explicitly fictional g/ml definitions, not
# mass conversions of the nominal portions in the recoverable source.
canonical=source21()
for entry in canonical['data']['entries']:
    entry['composition']={'complete':False,'total_mass_g':None}
    for binding in entry['bindings']:
        if binding['unit'] not in {'g','ml'}:
            binding.update(amount='30',unit='g');binding['new_food']['nutrition'].update(basis_amount='30',basis_unit='g')
seed=json.dumps(canonical,sort_keys=True).encode()
(out/'canonical-source-evidence.json').write_bytes(seed)
sha=hashlib.sha256(seed).hexdigest()
canonical['data'].update(source_sha256=sha,event_key=hashlib.sha256(json.dumps({'file':sha},sort_keys=True,separators=(',',':')).encode()).hexdigest())
(out/'canonical-21.json').write_text(json.dumps(canonical,indent=2)+'\n',encoding='utf-8')
print('Six fictional variants and canonical source evidence written')
