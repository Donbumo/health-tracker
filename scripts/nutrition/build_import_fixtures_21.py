"""Generate exclusively fictional, clearly marked nutrition import evidence."""
import csv
import io
import json
import zipfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from openpyxl import Workbook
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

ROOT=Path(__file__).resolve().parents[2]/'examples/nutrition-2-1/fixtures'


def write_json(name,value):
    (ROOT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    text=['QA FICTICIA - SIN DATOS PERSONALES','PLAN ALIMENTARIO PRESCRITO - NO CONSUMIDO',
          'Pollo cocido QA - 150 g; proteina: 35 g; kcal: 250 kcal',
          'Arroz cocido QA - 150 g; proteina: 4 g; kcal: 200 kcal',
          'Revisar cantidades y vincular identidades antes de guardar.']
    pdf=canvas.Canvas(str(ROOT/'diet-prescribed.pdf'),pagesize=(612,792));pdf.setTitle('QA synthetic prescribed plan')
    for i,line in enumerate(text):pdf.setFont('Helvetica',12);pdf.drawString(40,740-i*36,line)
    pdf.save()
    image=Image.new('RGB',(1500,1100),'white');draw=ImageDraw.Draw(image)
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',38)
    for i,line in enumerate(text):draw.text((45,50+i*140),line,font=font,fill='black')
    scanned=canvas.Canvas(str(ROOT/'diet-scanned.pdf'),pagesize=(750,550));scanned.setTitle('QA synthetic scanned prescribed plan');scanned.drawImage(ImageReader(image),0,0,width=750,height=550);scanned.save()
    label=Image.new('RGB',(1200,1300),'white');draw=ImageDraw.Draw(label)
    for i,line in enumerate(['QA FICTICIA - ETIQUETA DE PRUEBA','Producto: Bebida QA avena','Marca: QA Demo','Contenido neto: 500 ml',
                            'Valores por 100 ml','Porcion: 250 ml','Kcal: 45 kcal','Proteina: 1 g','Carbohidratos totales: 7 g','Grasa: 1.5 g','Sodio: 30 mg','Barcode: 0000000000001']):
        draw.text((45,45+i*95),line,font=font,fill='black')
    for name,format in [('label.png','PNG'),('label.jpg','JPEG'),('label.webp','WEBP')]:label.save(ROOT/name,format=format)
    wb=Workbook();sheet=wb.active;sheet.title='QA dieta';sheet.append(['Nombre','Cantidad','Unidad','Fecha','meal_type','kcal','protein_g'])
    sheet.append(['Arroz con pollo QA',300,'g','2026-10-05','lunch',450,35]);wb.save(ROOT/'diet.xlsx')
    (ROOT/'app.csv').write_text('Date,Meal,Food Name,Calories,Protein (g),Carbs (g),Fat (g),Cantidad,Unidad\n2026-10-05,Lunch,Arroz con pollo QA,450,35,40,12,300,g\n',encoding='utf-8')
    (ROOT/'table.tsv').write_text('Nombre\tCantidad\tUnidad\tkcal\tprotein_g\nQA tortilla\t50\tg\t100\t2\n',encoding='utf-8')
    row={'name':'Arroz con pollo QA','amount':'300','unit':'g','date':'2026-10-05','meal_type':'lunch','kcal':450,'protein_g':35}
    write_json('compound-macros.json',{'records':[row]})
    write_json('external.json',{'registros':[dict(row,marca='QA Demo')]})
    write_json('missing-brand.json',{'products':[{'name':'QA producto no catalogado','amount':'30','unit':'g','calories_per_100g':100,'protein_g_per_100g':0}]})
    write_json('ambiguous-unit.json',{'records':[{'name':'QA taza de arroz','amount':'1','unit':'cup','protein':3}]})
    write_json('prescribed-no-consumption.json',{'plan':[dict(row,date='Lunes prescrito')],'classification':'prescribed'})
    write_json('date-conflict.json',{'records':[dict(row,date='2026-10-01')]})
    write_json('internal.json',{'schema_version':'1.0','record_type':'daily_nutrition','user_id':1,'source_type':'uploaded','data':{'date':'2026-10-05','calories_kcal':450,'protein_g':35,'meals':[{'meal_type':'lunch','items':[{'name':row['name'],'quantity':300,'unit':'g','calories_kcal':450,'protein_g':35}]}]}})
    (ROOT/'duplicate.json').write_bytes((ROOT/'compound-macros.json').read_bytes())
    with zipfile.ZipFile(ROOT/'nutrition-export.zip','w',zipfile.ZIP_DEFLATED) as archive:
        archive.write(ROOT/'external.json','nutrition/records.json');archive.write(ROOT/'table.tsv','nutrition/table.tsv')
    manifest=[{'file':p.name,'fixture':'QA synthetic','scenario':p.stem} for p in sorted(ROOT.iterdir()) if p.is_file() and p.name!='manifest.json']
    write_json('manifest.json',manifest)
    print(json.dumps({'fixtures':len(manifest),'root':str(ROOT)},ensure_ascii=True))


if __name__=='__main__':main()
