"""Entirely fictional Issue #36 inputs; no private source data or identifiers."""
import copy
from decimal import Decimal

from app.services.nutrition_math import NUTRIENTS


def source21():
    entries=[]
    index=0
    for meal,size in zip(('breakfast','lunch','snack','dinner'),(5,5,5,6)):
        bindings=[]
        for _ in range(size):
            unit={0:'bolsa',7:'envase',14:'pieza'}.get(index,'ml' if index%4==0 else 'g')
            amount='1' if unit not in {'g','ml'} else str(20+index*5)
            nutrients={key:dict(state='known',value=str(Decimal(index+1)/10+Decimal(n+1)/100),unit=definition[1])
                for n,(key,definition) in enumerate(NUTRIENTS.items())}
            for key,value in dict(energy=100+index*3,protein=3,carbohydrate_total=10,net_carbs=8,fiber=2,fat=2,sugar=1).items():
                nutrients[key]['value']=str(value)
            nutrition=dict(basis_amount=amount,basis_unit=unit,servings=[],density_g_ml=None,nutrients=nutrients,
                provenance=dict(method='fictional_qa',quality='estimated' if index%2==0 else 'file_declared_unverified',
                    notes='QA only: caffeine 99 mg and selenium 7 ug are prose, not verified nutrient amounts.',
                    additional_nutrients={'caffeine':{'value':'99','unit':'mg'},'selenium':{'value':'7','unit':'ug'}}))
            bindings.append(dict(amount=amount,unit=unit,new_food=dict(name=f'QA synthetic food {index+1:02}',
                brand='QA fictional brand',nutrition=nutrition)))
            index+=1
        entries.append(dict(name='QA fictional '+meal,date='2026-01-15',meal_type=meal,confirmed=True,
            conflict_action='block',composition={'complete':True,'total_mass_g':None},declaration=None,
            evidence={'method':'synthetic_qa_only','notes':'No personal data. Additional prose is not counted.'},bindings=bindings))
    return dict(type='nutrition_import',schema_version='2.1',source_type='uploaded',user_id=999999,
        data=dict(name='QA synthetic four meals and 21 foods',destination='consumed',entries=entries))


def variant(case):
    doc=copy.deepcopy(source21())
    if case=='conflict':
        n=doc['data']['entries'][0]['bindings'][1]['new_food']['nutrition']
        n['basis_unit']='ml'  # g consumed / ml declared; no verified equivalence.
    elif case=='partial':
        for entry in doc['data']['entries']:
            for binding in entry['bindings']:
                n=binding['new_food']['nutrition']['nutrients']
                n['vitamin_d']={'state':'unknown','value':None,'unit':'ug'}
                n['iron']={'state':'trace','value':None,'unit':'mg'}
                n['zinc']={'state':'below_limit','value':None,'limit':'0.1','unit':'mg'}
                n.pop('carbohydrate_total')
    elif case=='malformed':doc['data']['entries']={'not':'a list'}
    elif case!='clean':raise ValueError('Unknown fictional case')
    return doc


def mixed_quality():
    """All amounts match source21; only fictional quality metadata differs."""
    doc=source21()
    foods=[b['new_food']['nutrition'] for entry in doc['data']['entries'] for b in entry['bindings']]
    for nutrition in foods:
        nutrition['provenance'].update(method='nutrition_label',quality='label_verified',limitations='QA: sin aproximación; no se estimó.')
    for nutrition,limitation in zip(foods,('QA: valor aproximado.','QA: referencia provisional.',
            'QA: valor de proxy.','QA: incertidumbre nutricional.')):
        nutrition['provenance'].update(quality='file_declared_unverified',limitations=limitation)
    # A verified label stays verified for every other nutrient.
    foods[4]['nutrients']['fiber']['provenance']={'method':'composition_proxy','limitations':'QA: fibra aproximada.'}
    foods[5]['provenance']['limitations']='QA: fecha provisional; etiqueta verificada.'
    return doc
