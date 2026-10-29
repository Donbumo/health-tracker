"""Small, anchored portion grammar. Parsed weights are unverified proposals."""
import re
import unicodedata
from decimal import Decimal

from app.services.nutrition_math import NutritionError, decimal

NUMBER = r'\d+(?:[.,]\d+)?'
NOUNS = {'piezas':'pieza','pieces':'pieza','piece':'pieza','latas':'lata','cans':'lata','can':'lata',
         'botellas':'botella','bottles':'botella','bottle':'botella','barras':'barra','bars':'barra','bar':'barra',
         'sobres':'sobre','sachets':'sobre','sachet':'sobre','tortillas':'tortilla',
         'porciones':'porcion','portions':'porcion','portion':'porcion','servings':'porcion','serving':'porcion'}
for noun in list(NOUNS.values()):NOUNS[noun]=noun


def folded(text):
    return ''.join(c for c in unicodedata.normalize('NFKD',str(text)).casefold() if not unicodedata.combining(c)).strip()


def numeric(text):
    if re.fullmatch(r'\d+,\d{3}',text):raise NutritionError('Separador decimal/miles ambiguo.')
    return str(decimal(text.replace(',','.'),positive=True))


def parse(text):
    match=re.fullmatch(r'(?:(?P<count>'+NUMBER+r')\s+)?(?P<noun>'+ '|'.join(sorted(NOUNS,key=len,reverse=True)) +
        r')(?P<size>\s+(?:grandes?|pequenas?|medianas?|large|small|medium))?(?P<tail>.*)',folded(text))
    if not match:return None
    label=NOUNS[match['noun']]
    if match['size']:label+=' '+{'grandes':'grande','pequenas':'pequena','medianas':'mediana'}.get(match['size'].strip(),match['size'].strip())
    result={'label':label,'amount':numeric(match['count']) if match['count'] else None,'text':str(text)}
    tail=match['tail'].strip()
    if not tail:return result
    per=re.fullmatch(r'de\s+('+NUMBER+r')\s*(g|ml)(?:\s*\(\s*(~|aprox\.?\s*)?('+NUMBER+r')\s*(g|ml)\s*\))?',tail)
    bracket=re.fullmatch(r'\(\s*(~|aprox\.?\s*)?('+NUMBER+r')\s*(g|ml)\s*(c/u|cada una|cada uno|each)?\s*\)',tail)
    if per:
        result['equivalence']={'amount':numeric(per[1]),'unit':per[2],'approximate':False,'text':str(text)}
        if per[4]:result['total_note']={'amount':numeric(per[4]),'unit':per[5],'approximate':bool(per[3])}
    elif bracket and (bracket[4] or result['amount'] in (None,'1')):
        result['equivalence']={'amount':numeric(bracket[2]),'unit':bracket[3],'approximate':bool(bracket[1]),'text':str(text)}
    else:result['unparsed_note']=tail
    return result


def normalize(row, raw_amount, raw_unit, raw_basis):
    """Keep nominal quantities and source text even when a note is ambiguous."""
    amount=parse(raw_amount) if raw_amount is not None else None
    unit=parse(raw_unit) if raw_unit is not None else None
    basis=parse(raw_basis) if raw_basis is not None else None
    if basis:
        row['basis_unit']='portion';row['basis_label']=basis['label']
    proposed=amount or unit
    if not proposed:return
    row.update(unit='portion',unit_label=proposed['label'],portion_text=proposed['text'])
    if amount and amount['amount']:
        row['amount']=amount['amount']
        row['warnings']=[w for w in row['warnings'] if w!='Cantidad ilegible o ambigua.']
    elif unit and unit['amount']:
        if row.get('amount') is None:row['amount']=unit['amount']
        elif Decimal(row['amount'])!=Decimal(unit['amount']):row['portion_conflict']='La cantidad y el descriptor de unidad discrepan.'
    if amount and unit and amount['label']!=unit['label']:
        row['portion_conflict']='Las dos descripciones de porción no son iguales.'
    equivalent=(amount or {}).get('equivalence') or (unit or {}).get('equivalence')
    if equivalent:
        previous=row.get('equivalence')
        if previous and (str(previous.get('amount')),previous.get('unit'))!=(equivalent['amount'],equivalent['unit']):
            row['portion_conflict']='La equivalencia estructurada y el texto no coinciden.'
        row['equivalence']=equivalent;row['equivalence_confirmed']=False
    for part in [amount,unit]:
        if not part:continue
        if part.get('total_note'):
            row['portion_total_note']=part['total_note']
            note=part['total_note']
            if equivalent and row.get('amount') and (note['unit']!=equivalent['unit'] or
                    Decimal(note['amount'])!=Decimal(row['amount'])*Decimal(equivalent['amount'])):
                row['portion_conflict']='El total escrito no coincide con cantidad por equivalencia. Revisa cuál es correcto.'
        if part.get('unparsed_note'):
            row['warnings'].append('Nota de porción sin equivalencia inequívoca: '+part['unparsed_note'])
            row['portion_note_pending']=True
