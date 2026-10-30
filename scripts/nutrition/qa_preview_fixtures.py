"""Public fictional fixtures for Issue #32; no account or health data."""
import copy
import csv
import io
import json
from pathlib import Path


def source(count=21, ambiguous=False):
    rows = [dict(name=f'QA alimento ficticio {index+1:02}', brand='Marca demo inventada',
        date='2026-01-15',meal_type='breakfast' if index<10 else 'lunch',
        amount='100',unit='g',basis_amount='100',basis_unit='g',
        calories_kcal='200',protein_g='10',total_carbs_g='20',fat_g='8',fiber_g='0',iron_mg='2')
        for index in range(count)]
    if ambiguous:
        rows[25]['calories_per_100ml']=rows[25].pop('calories_kcal')
    return {'destination':'consumed','records':rows}


def table(document, delimiter=','):
    rows=copy.deepcopy(document['records'])
    for row in rows:
        for old,new in [('date','Date'),('meal_type','Meal'),('name','Food Name'),('calories_kcal','Calories')]:
            row[new]=row.pop(old)
        # Absolute units are explicit even for the application-specific header.
        row['Calories']+=' kcal'
    output=io.StringIO();writer=csv.DictWriter(output,fieldnames=list(rows[0]),delimiter=delimiter)
    writer.writeheader();writer.writerows(rows)
    return output.getvalue().encode()


if __name__=='__main__':
    root=Path(__file__).resolve().parents[2]/'examples/qa/nutrition-import-preview'
    root.mkdir(parents=True,exist_ok=True)
    for name,document in [('clean-21',source()),('one-error-51',source(51,True))]:
        (root/(name+'.json')).write_text(json.dumps(document,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (root/'clean-21.csv').write_bytes(table(source()))
