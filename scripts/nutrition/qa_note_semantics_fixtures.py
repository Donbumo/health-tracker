"""Fictional Issue #34 sources; contains no personal values or documents."""
import json
from pathlib import Path


def source(length=5000,conflict=None):
    note=('QA ficticia: observaciones editoriales conservadas. '*110)[:length]
    if conflict:note=note[:max(0,length-len(conflict)-1)]+' '+conflict
    return dict(schema_version='1.0',record_type='daily_nutrition',user_id=999999,source_type='uploaded',
        data=dict(date='2026-02-03',source='QA ficticia Issue34',notes=note,meals=[
            dict(meal_type=meal,items=[dict(name=f'QA alimento ficticio {i+1:02}',quantity=100,unit='g',
                calories_kcal=200,protein_g=10,total_carbs_g=20,net_carbs_g=19,fat_g=8,fiber_g=0,
                notes='QA estimado' if i==1 else 'QA dato ficticio') for i in range(23) if i%4==group])
            for group,meal in enumerate(['breakfast','lunch','dinner','snack'])]))


if __name__=='__main__':
    root=Path(__file__).resolve().parents[2]/'examples/qa/nutrition-note-semantics';root.mkdir(exist_ok=True)
    for name,document in [('long-note-23.json',source()),('conflicting-note-23.json',source(conflict='Los macros son por 100 g.'))]:
        (root/name).write_text(json.dumps(document,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (root/'README.md').write_text('# QA ficticia · notas generales\n\nDos archivos sintéticos de 23 alimentos; ninguna cuenta, nombre o cifra procede de datos personales. `long-note-23.json` contiene una nota editorial de 5.000 caracteres. `conflicting-note-23.json` añade una instrucción general incompatible con inferir aportes consumidos.\n',encoding='utf-8')
