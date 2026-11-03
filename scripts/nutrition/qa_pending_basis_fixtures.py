"""Independent fictional canonical 2.1 source with editorial basis metadata."""
import hashlib
import json
from decimal import Decimal

from app.services.nutrition_math import NUTRIENTS


def source18():
    entries=[]
    for i in range(18):
        unit='ml' if i in {2,6,10,14} else 'g';amount=str(10+3*i)
        quality='estimated' if i%2 else 'label_or_operational_reference'
        vector={k:dict(state='known',value=str(Decimal(i+1)/10+Decimal(n+1)/100),unit=d[1])
                for n,(k,d) in enumerate(NUTRIENTS.items())}
        for key,value in dict(energy=80+i*5,protein='2.5',carbohydrate_total='7.25',net_carbs='6.25',fat='1.5',fiber='1').items():
            vector[key]['value']=str(value)
        annotation=dict(consumed_quantity=amount,basis_unit=unit,quality=quality)
        entries.append(dict(name=f'QA fictional basis food {i+1:02}',date='2026-02-14',
            meal_type=('breakfast' if i<5 else 'lunch' if i<10 else 'snack' if i<14 else 'dinner'),
            portion_amount=amount,portion_unit=unit,bindings=[],confirmed=True,
            composition=dict(complete=False,total_mass_g=amount if unit=='g' else None),
            evidence={'method':'fictional_qa_only'},declaration=dict(basis_amount=amount,basis_unit=unit,
                nutrients=vector,confirmed=True,provenance=dict(method='fictional_label',quality=quality,basis_interpretation=annotation))))
    data=dict(name='QA fictional declared basis 18',destination='consumed',entries=entries)
    seed=json.dumps(data,sort_keys=True,separators=(',',':')).encode()
    sha=hashlib.sha256(seed).hexdigest()
    data.update(source_sha256=sha,event_key=hashlib.sha256(json.dumps({'file':sha},sort_keys=True,separators=(',',':')).encode()).hexdigest())
    return dict(schema_version='2.1',type='nutrition_import',user_id=999999,source_type='uploaded',data=data)


if __name__=='__main__':
    import sys
    from pathlib import Path
    path=Path(sys.argv[1]);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(source18(),indent=2)+'\n',encoding='utf-8')
    print('Entirely fictional source18 written')
