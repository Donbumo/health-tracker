"""QA only: generate a draft using the exact public #29 parser AND service.

Host: read two known Git blobs. Container: mount those same checked blobs in
QA_LEGACY_CODE. Never execute uploaded data, credentials or production files.
"""
import hashlib
import os
from pathlib import Path
import subprocess
import types

SHA='1cf8d830ba801a8c8121cf594b07a0269a6d6e6f'
FILES={'nutrition_sources.py':('backend/app/services/importers/nutrition_sources.py','d10518411cd200a4b2b9d2ff4a0df0af39fec98825143e4fbe820da4fa1e5e04'),
       'nutrition_import.py':('backend/app/services/nutrition_import.py','db4ed6dc21574ad01ee2bc627d7a913e358ac2e91ecdfa9fe184cc42dcd50955')}


def legacy_modules():
    modules={}
    for name,(path,digest) in FILES.items():
        folder=os.environ.get('QA_LEGACY_CODE')
        code=(Path(folder)/name).read_bytes() if folder else subprocess.check_output(['git','show',SHA+':'+path],cwd=Path(__file__).resolve().parents[2])
        assert hashlib.sha256(code).hexdigest()==digest,'QA predecessor code mismatch'
        module=types.ModuleType('qa_legacy_'+name[:-3])
        exec(compile(code,SHA+'/'+path,'exec'),module.__dict__)
        modules[name]=module
    parser=modules['nutrition_sources.py'];service=modules['nutrition_import.py']
    service.extract=parser.extract
    return parser,service


def legacy_review(user_id,payload,ref):
    from app.extensions import db
    parser,service=legacy_modules()
    row=service.start(user_id,payload,'QA retained text portions.json')
    service.update(user_id,row.public_id,row.revision,'destination',{'destination':'consumed','name':'QA revisión anterior conservada'})
    service.update(user_id,row.public_id,row.revision,'fields',{'index':'1','_section':'identity','name':'QA nombre corregido por usuario','date':'2026-10-26','meal_type':'lunch','brand':'QA marca conservada'})
    service.update(user_id,row.public_id,row.revision,'fields',{'index':'2','_section':'composition','amount':'150','unit':'g'})
    service.update(user_id,row.public_id,row.revision,'bind',{'index':'0','ref':ref,'food_revision':'1','amount':'100','unit':'g'})
    assert row.revision==5 and 'extractor_version' not in row.source_json
    db.session.commit()
    return row
