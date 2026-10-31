"""Read-only 2.1 source adapter; the final 2.1 JSON Schema stays strict."""
import copy
import re

from app.services.nutrition_math import NUTRIENTS, NutritionError, decimal

NOMINAL = {'portion','porción','porcion','serving','pieza','piezas','bolsa','bolsas',
           'envase','envases','lata','latas','botella','botellas','sobre','sobres'}
UNCOUNTED = {'biotin':'Biotina','biotina':'Biotina','manganese':'Manganeso','manganeso':'Manganeso',
    'copper':'Cobre','cobre':'Cobre','selenium':'Selenio','selenio':'Selenio',
    'pantothenic_acid':'B5','vitamin_b5':'B5','b5':'B5','ácido pantoténico':'B5','acido pantotenico':'B5',
    'caffeine':'Cafeína','cafeína':'Cafeína','cafeina':'Cafeína'}


def uncounted_warnings(value):
    # Identify unsupported terms, never numbers, units or nutritional amounts.
    text=str(value).casefold().replace('_',' ')
    names=sorted({label for term,label in UNCOUNTED.items() if re.search(r'(?<!\w)'+re.escape(term.replace('_',' '))+r'(?!\w)',text)})
    return ['No contabilizados: '+', '.join(names)+'. Evidencia conservada; no se extraen cantidades de las notas.'] if names else []


def exact_binding(binding):
    ref=binding.get('ref');revision=binding.get('food_revision');unit=binding.get('unit')
    if (not isinstance(ref,str) or not re.fullmatch(r'(catalog|user):[a-f0-9-]{36}',ref) or
            not isinstance(revision,str) or not revision or len(revision)>64):
        raise NutritionError('El vínculo 2.1 necesita identidad y revisión explícitas; no se busca por nombre.')
    if not isinstance(unit,str) or unit not in {'g','ml','serving'}:
        raise NutritionError('La unidad del vínculo 2.1 necesita g, ml o una porción publicada explícita.')
    amount=str(decimal(binding.get('amount'),positive=True))
    result=copy.deepcopy(binding);result['amount']=amount
    return result


def source_rows(document,evidence,*,strict):
    from app.services.importers.nutrition_sources import normalized_row,MAX_ROWS
    data=document.get('data')
    if not isinstance(data,dict):raise NutritionError('El documento 2.1 necesita un objeto data con entradas nutricionales.')
    if data.get('destination')!='consumed':return None
    entries=data.get('entries')
    if not isinstance(entries,list) or not entries or len(entries)>MAX_ROWS:
        raise NutritionError('El documento 2.1 necesita entre 1 y 250 entradas estructuradas.')
    if strict and any(isinstance(e,dict) and e.get('bindings') and e.get('declaration') for e in entries):
        return None  # Preserve canonical compound authority and exact bindings.
    if strict and not any(isinstance(e,dict) and e.get('bindings') and not e.get('declaration') for e in entries):return None
    rows=[]
    document_warnings=uncounted_warnings(data.get('notes'))

    def declaration_row(entry,binding,food,number,child,parent_warnings):
        nutrition=food.get('nutrition')
        if not isinstance(nutrition,dict) or not isinstance(nutrition.get('nutrients'),dict):
            raise NutritionError('Un alimento 2.1 no contiene una declaración nutricional estructurada.')
        vector=nutrition['nutrients'];supported={k:v for k,v in vector.items() if k in NUTRIENTS}
        raw=dict(name=food.get('name'),brand=food.get('brand'),amount=binding.get('amount'),unit=binding.get('unit'),
            basis_amount=nutrition.get('basis_amount'),basis_unit=nutrition.get('basis_unit'),nutrients=supported,
            date=entry.get('date'),meal_type=entry.get('meal_type'),notes=food.get('notes',entry.get('notes','')))
        first=child in (None,0)
        row=normalized_row(raw,dict(evidence,row=len(rows)+1,source_entry=number,source_binding=child,
            source_contract='nutrition_import_2_1',meal_evidence=copy.deepcopy(entry.get('evidence',{})) if first else {'source_entry':number}))
        row['original']=copy.deepcopy(binding)
        # Keep large meal evidence once, linked by file SHA + entry index;
        # never multiply a meal's full notes by its number of ingredients.
        row['original']['source_entry']={k:copy.deepcopy(v) for k,v in entry.items()
            if k!='bindings' and (first or k in {'name','date','meal_type'})}
        row.update(kind_hint='consumed',source_quality='file_declared_unverified')
        provenance=nutrition.get('provenance') or {}
        if isinstance(provenance,dict) and (provenance.get('quality')=='estimated' or 'estimat' in str(provenance).casefold() or 'estimad' in str(provenance).casefold()):
            row['source_quality']='estimated'
        row['warnings'].extend(parent_warnings+uncounted_warnings((nutrition.get('provenance'),food.get('notes'),vector)))
        if set(vector)-NUTRIENTS.keys():row['warnings'].append('Hay nutrientes estructurados no admitidos: se conservan en el original y no se contabilizan.')
        for field,label in [('unit','unit_label'),('basis_unit','basis_label')]:
            original=str(raw.get(field) or '').strip().casefold()
            if original in NOMINAL and row.get(field)!='portion':
                row[field]='portion';row[label]={'bolsas':'bolsa','envases':'envase'}.get(original,original)
        # A nominal portion must refer to the same original label on both sides.
        compatible=(row.get('unit')==row.get('basis_unit') and row.get('unit') in {'g','ml','portion'} and
            (row['unit']!='portion' or row.get('unit_label')==row.get('basis_label')))
        try:decimal(row.get('amount'),positive=True);decimal(row.get('basis_amount'),positive=True)
        except NutritionError:compatible=False
        if not compatible:
            row['basis_conflict']=True
            row['warnings'].append('La cantidad y base no tienen unidades equivalentes verificadas; no se inventa una conversión.')
        else:row['resolution']='declared'
        # Source confirmed/authority/conflict choices never grant user consent.
        return row

    for number,entry in enumerate(entries):
        if not isinstance(entry,dict):raise NutritionError('Cada entrada 2.1 debe ser un objeto nutricional.')
        parent_warnings=document_warnings+uncounted_warnings((entry.get('notes'),entry.get('evidence')))
        bindings=entry.get('bindings',[])
        if not isinstance(bindings,list) or len(bindings)>100:raise NutritionError('Los bindings 2.1 deben ser una lista de hasta 100 alimentos.')
        if bindings and not entry.get('declaration'):
            for child,binding in enumerate(bindings):
                if not isinstance(binding,dict) or bool(binding.get('ref'))==bool(binding.get('new_food')):
                    raise NutritionError('Cada alimento necesita una identidad exacta o una declaración new_food, sin mezclarlas.')
                if binding.get('new_food'):
                    if not isinstance(binding['new_food'],dict):raise NutritionError('new_food debe ser un objeto nutricional.')
                    row=declaration_row(entry,binding,binding['new_food'],number,child,parent_warnings)
                else:
                    verified=exact_binding(binding)
                    row=normalized_row(dict(amount=binding.get('amount'),unit=binding.get('unit'),date=entry.get('date'),meal_type=entry.get('meal_type')),
                        dict(evidence,row=len(rows)+1,source_entry=number,source_binding=child))
                    row.update(ingredients=[verified],source_identity=True,kind_hint='consumed',original=copy.deepcopy(binding))
                    if binding.get('unit')=='serving':
                        row['source_display_quantity']={'amount':binding.get('amount'),'unit':'porción publicada'}
                        row.pop('amount',None);row.pop('unit',None)
                rows.append(row)
        elif entry.get('declaration'):
            # An authoritative parent declaration is one contribution, never
            # counted once as a meal and again as its ingredient children.
            if not isinstance(entry['declaration'],dict):raise NutritionError('La declaración 2.1 debe ser un objeto.')
            nutrition=entry['declaration']
            binding=dict(amount=entry.get('portion_amount'),unit=entry.get('portion_unit'))
            row=declaration_row(entry,binding,dict(name=entry.get('name'),nutrition=nutrition),number,None,parent_warnings)
            if bindings:
                row['original']['bindings']=copy.deepcopy(bindings)
                if all(isinstance(b,dict) and b.get('ref') and not b.get('new_food') for b in bindings):
                    row['ingredients']=[exact_binding(b) for b in bindings];row.pop('resolution',None)
                else:row['warnings'].append('La declaración de la comida es el aporte autoritativo; sus componentes se conservan como evidencia y no se suman otra vez.')
            rows.append(row)
        else:raise NutritionError('La entrada 2.1 no contiene alimentos ni una declaración recuperable.')
        if len(rows)>MAX_ROWS:raise NutritionError('Importación supera 250 alimentos; divide el archivo.')
    return rows
