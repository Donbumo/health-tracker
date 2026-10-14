"""Build separate, attributed local sources from bounded public archives.

Original archives remain in OS TEMP; no health data or API keys. Never stages a
database or merges nutrients across sources. Run explicitly, not on app startup.
"""
import csv
import hashlib
import io
import json
from decimal import Decimal
from pathlib import Path
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from app.services.nutrition_math import NUTRIENTS
from app.services.nutrition_sources import finite_source_number, off_food
from evaluate_sources import USDA_NUTRIENTS

OUT = ROOT / 'examples/catalog/nutrition-2-1'
SOURCES = {
    'usda_sr_legacy': ('2018-04-full-ni21-v1', 'https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_sr_legacy_food_csv_2018-04.zip', 15_000_000),
    'usda_foundation': ('2026-04-30-ni21-v1', 'https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_foundation_food_json_2026-04-30.zip', 3_000_000),
    'usda_fndds': ('2021-2023-ni21-v1', 'https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_survey_food_json_2024-10-31.zip', 15_000_000),
}
# Search vocabulary only, never an assertion of nutritional equivalence.
VOCABULARY = {'rice':'arroz', 'chicken':'pollo', 'beans':'frijoles frijol', 'beef':'res carne',
    'milk':'leche', 'yogurt':'yogur yogurt', 'cheese':'queso', 'egg':'huevo', 'eggs':'huevos',
    'oats':'avena', 'corn':'maiz elote', 'tortillas':'tortilla tortillas', 'bread':'pan',
    'apple':'manzana', 'apples':'manzanas', 'avocado':'aguacate', 'avocados':'aguacates',
    'tomatoes':'tomate jitomate', 'tuna':'atun', 'salmon':'salmon', 'potatoes':'papa patata',
    'banana':'platano', 'bananas':'platano', 'lentils':'lentejas', 'chickpeas':'garbanzos',
    'onions':'cebolla', 'spinach':'espinaca', 'peanuts':'cacahuate', 'pork':'cerdo',
    'nopales':'nopal', 'carrots':'zanahoria', 'squash':'calabaza', 'zucchini':'calabacita',
    'peppers':'chile pimiento', 'cucumber':'pepino', 'orange':'naranja', 'oranges':'naranja',
    'strawberries':'fresas', 'pineapple':'pina piña', 'mangos':'mango', 'fish':'pescado',
    'raw':'crudo cruda', 'cooked':'cocido cocida', 'roasted':'asado asada', 'boiled':'hervido hervida',
    'oil':'aceite', 'olive':'oliva', 'sugar':'azucar azúcar', 'butter':'mantequilla', 'water':'agua',
    'protein':'proteina proteína', 'shake':'batido', 'chocolate':'chocolate', 'coffee':'cafe café'}
VOCABULARY.update({'white':'blanco blanca','brown':'integral','black':'negro negra negros negras','pinto':'pinto pintos',
    'breast':'pechuga','whole':'entero entera integral','wheat':'trigo','flour':'harina','fried':'frito frita',
    'turkey':'pavo','broccoli':'brocoli brócoli','papaya':'papaya','guava':'guayaba','guavas':'guayaba',
    'quinoa':'quinoa','almonds':'almendras','walnuts':'nueces','chili':'chile','tortilla':'tortilla',
    'sweet':'dulce','potato':'papa patata','potatoes':'papas patatas','canned':'enlatado enlatada',
    'shrimp':'camaron camarón','cabbage':'col repollo','lettuce':'lechuga','garlic':'ajo','lemon':'limon limón',
    'limes':'limon limón','lime':'limon limón','melon':'melon melón','watermelon':'sandia sandía',
    'carrot':'zanahoria','onion':'cebolla','strawberry':'fresa','bean':'frijol','tomato':'tomate jitomate'})


def download(url, name, limit):
    path = Path(tempfile.gettempdir()) / ('ht-ni21-' + name)
    if not path.exists():
        request = urllib.request.Request(url, headers={'User-Agent': 'HealthTrackerNutrition/2.1 (https://github.com/Donbumo/health-tracker)'})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError('Public source exceeds reviewed download bound')
        path.write_bytes(data)
    if path.stat().st_size > limit:
        raise ValueError('Cached source exceeds bound')
    return path


def archive_entries(path):
    archive = zipfile.ZipFile(path)
    if sum(item.file_size for item in archive.infolist()) > 250_000_000:
        raise ValueError('Public archive exceeds reviewed expanded bound')
    return archive


def metadata(name, food_type):
    import re
    words = set(re.findall(r'[a-z]+', name.lower()))
    aliases = sorted({value for key, value in VOCABULARY.items() if key in words})
    state = 'mixed' if {'raw','cooked'} <= words else 'raw' if 'raw' in words else 'cooked' if words & {'cooked','roasted','boiled','fried'} else 'unspecified'
    return {'aliases': aliases, 'food_type': food_type, 'preparation_state': state,
            'brand': None, 'barcode': None, 'language': 'en', 'quality': 'published_dataset'}


def base(source, revision, identity, name, food_type):
    return {'source': source, 'source_food_id': str(identity), 'revision': revision,
            'name': name[:200], 'source_name': name, 'preparation': name[:200],
            'basis_amount': '100', 'basis_unit': 'g', 'density_g_ml': None,
            'nutrients': {}, 'servings': [], 'metadata': metadata(name, food_type)}


def value(food, key, raw, unit, nutrient_id):
    if raw in (None, ''):
        return
    number = Decimal(str(raw))
    if not number.is_finite() or number < 0:
        return
    original = str(unit).lower().replace('μ','u').replace('µ','u')
    expected = NUTRIENTS[key][1]
    if original != expected:
        return  # Never conflate IU, RE/RAE, folate forms or incompatible units.
    food['nutrients'][key] = {'value': finite_source_number(number), 'state': 'known', 'unit': expected,
        'provenance': {'source_nutrient_id': str(nutrient_id), 'method': 'published_dataset',
                       'original_value':str(raw)}}


def sr_legacy(path):
    source, revision = 'usda_sr_legacy', SOURCES['usda_sr_legacy'][0]
    with archive_entries(path) as archive:
        def rows(name):
            item = next(n for n in archive.namelist() if n.endswith('/'+name) or n == name)
            return csv.DictReader(io.TextIOWrapper(archive.open(item), encoding='utf-8-sig'))
        foods = {row['fdc_id']: base(source, revision, row['fdc_id'], row['description'], 'sr_legacy') for row in rows('food.csv')}
        units = {row['id']: row['unit_name'] for row in rows('nutrient.csv')}
        for row in rows('food_nutrient.csv'):
            identifier = int(row['nutrient_id'])
            if row['fdc_id'] in foods and identifier in USDA_NUTRIENTS:
                value(foods[row['fdc_id']], USDA_NUTRIENTS[identifier], row['amount'], units[str(identifier)], identifier)
        for row in rows('food_portion.csv'):
            food = foods.get(row['fdc_id'])
            if food and row.get('gram_weight') and Decimal(row['gram_weight']) > 0:
                label = ' '.join(str(row.get(k) or '') for k in ['amount','modifier','portion_description']).strip()
                if label:
                    food['servings'].append({'id':row['id'], 'label':label[:200], 'amount':finite_source_number(row['gram_weight']), 'unit':'g'})
    reviewed = json.loads((ROOT/'examples/qa/nutrition-intelligence/catalog-sample.json').read_text(encoding='utf-8'))
    names = {f['source_food_id']: f['name'] for f in reviewed['foods']}
    for identity, food in foods.items():
        if identity in names:
            food['name'] = names[identity]
            food['metadata']['aliases'].append(food['source_name'])
            food['metadata']['language'] = 'es/en'
    return list(foods.values())


def usda_json(path, source, revision):
    with archive_entries(path) as archive:
        name = next(n for n in archive.namelist() if n.endswith('.json'))
        raw = json.loads(archive.read(name), parse_float=Decimal)
    rows = max((v for v in raw.values() if isinstance(v, list)), key=len)
    foods = []
    for row in rows:
        if not isinstance(row, dict) or not row.get('fdcId') or not row.get('description'):
            continue  # Published null/tombstone rows cannot invent identities.
        food = base(source, revision, row['fdcId'], row['description'], row['dataType'])
        for nutrient in row.get('foodNutrients', []):
            definition = nutrient.get('nutrient', {}); identifier = definition.get('id')
            key = USDA_NUTRIENTS.get(identifier)
            if identifier in (2047,2048) and 'energy' not in food['nutrients']:
                key = 'energy'
            if key:
                value(food, key, nutrient.get('amount'), definition.get('unitName'), identifier)
        for portion in row.get('foodPortions', []):
            mass = portion.get('gramWeight')
            if mass is None or Decimal(str(mass)) <= 0:
                continue
            label = portion.get('portionDescription') or ' '.join(str(x) for x in [portion.get('amount',''),portion.get('measureUnit',{}).get('name',''),portion.get('modifier','')] if x != '')
            if label and label != 'undetermined':
                food['servings'].append({'id':str(portion['id']), 'label':label[:200], 'amount':finite_source_number(mass), 'unit':'g'})
                food.setdefault('provenance',{}).setdefault('original_servings',[]).append({'id':str(portion['id']),'gram_weight':str(mass),'description':label})
        foods.append(food)
    return foods


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {'retrieved': '2026-10-13', 'sources': []}
    for source, (revision, url, limit) in SOURCES.items():
        path = download(url, source+'.zip', limit)
        foods = sr_legacy(path) if source == 'usda_sr_legacy' else usda_json(path, source, revision)
        document = {'schema_version':'2.0', 'source':source, 'revision':revision, 'license':'CC0-1.0',
                    'url':url, 'attribution':'USDA FoodData Central', 'foods':foods}
        output = OUT/(source+'.json')
        encoded = json.dumps(document, ensure_ascii=False, separators=(',',':'), sort_keys=True).encode()
        assert len(encoded) < 50_000_000
        output.write_bytes(encoded)
        entry = {'source':source, 'revision':revision, 'foods':len(foods), 'file':output.name,
                 'normalized_bytes':len(encoded), 'normalized_sha256':hashlib.sha256(encoded).hexdigest(),
                 'original_bytes':path.stat().st_size, 'original_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                 'url':url, 'license':'CC0-1.0', 'nutrient_values':sum(len(f['nutrients']) for f in foods),
                 'servings':sum(len(f['servings']) for f in foods), 'empty_vectors':sum(not f['nutrients'] for f in foods)}
        manifest['sources'].append(entry)
        print(json.dumps(entry))
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    # One bounded public Mexico sample; source/license remains separate from USDA.
    cached = Path(tempfile.gettempdir())/'ht-ni21-off-mx.json'
    if cached.exists():
        products = json.loads(cached.read_bytes()).get('products', [])
        foods, rejected = [], 0
        for product in products:
            try:
                foods.append(off_food(product))
            except ValueError:
                rejected += 1
        document = {'schema_version':'2.0','source':'open_food_facts','revision':'2026-10-13-mx100-ni21-v2',
                    'license':'ODbL-1.0','attribution':'Open Food Facts contributors','foods':foods}
        encoded=json.dumps(document,ensure_ascii=False,separators=(',',':'),sort_keys=True).encode()
        (OUT/'open_food_facts.json').write_bytes(encoded)
        manifest['sources'].append({'source':'open_food_facts','revision':document['revision'],'foods':len(foods),
            'file':'open_food_facts.json','normalized_bytes':len(encoded),'normalized_sha256':hashlib.sha256(encoded).hexdigest(),
            'license':'ODbL-1.0','attribution':'Open Food Facts contributors','requested_products':len(products),
            'rejected_missing_identity_or_basis':rejected,'original_sha256':hashlib.sha256(cached.read_bytes()).hexdigest(),
            'url':'https://world.openfoodfacts.org/api/v2/search?countries_tags_en=mexico&page_size=100'})
        (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
        print('OFF attributed sample foods:',len(foods),'rejected missing identity/basis:',rejected)


if __name__ == '__main__':
    main()
