"""B visual QA: ephemeral SQLite, public catalog and fictional owner only."""
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from app import create_app
from app.extensions import db
from app.models import FoodProduct, User
from app.models.nutrition_intelligence import CatalogFood, FoodCatalogRevision
from app.services import food_catalog as catalog

temporary = Path(tempfile.mkdtemp(prefix='ht-ni3-b-qa-'))
out = ROOT / 'design/nutrition-intelligence-3-b/qa'
out.mkdir(parents=True, exist_ok=True)
app = create_app({'TESTING': True, 'SECRET_KEY': 'fictional-equivalents-ui-qa-secret-only',
                  'API_TOKEN_SIGNING_KEY': 'fictional-equivalents-api-key-only-qa',
                  'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + (temporary / 'qa.sqlite').as_posix(),
                  'SQLALCHEMY_ENGINE_OPTIONS': {}, 'DATA_ROOT': temporary,
                  'UPLOAD_ROOT': temporary / 'raw', 'GENERATED_UPLOAD_ROOT': temporary / 'generated',
                  'PORTABILITY_ROOT': temporary / 'portable', 'SCHEMA_ROOT': ROOT / 'schemas',
                  'NUTRITION_INTELLIGENCE_ENABLED': True, 'NUTRITION_QA_LABEL': True,
                  'AI_ENABLED': False, 'NUTRITION_EXTERNAL_LOOKUP_ENABLED': False})
with app.app_context():
    db.create_all()
    owner = User(username='equivalents-qa', role='user', display_name='QA ficticia', timezone='America/Mexico_City')
    owner.set_password('fictional-equivalents-qa-password')
    db.session.add(owner);db.session.flush()
    product = FoodProduct(user_id=owner.id, name='QA pechuga declarada · datos incompletos', source='manual',
                           nutrition_json={'basis_amount': '100', 'basis_unit': 'g', 'nutrients': {
                               'energy': {'state': 'known', 'value': '120', 'unit': 'kcal'},
                               'protein': {'state': 'known', 'value': '25', 'unit': 'g'},
                               'vitamin_d': {'state': 'known', 'value': '0', 'unit': 'ug'},
                               'vitamin_b12': {'state': 'trace', 'value': None, 'unit': 'ug'}}})
    db.session.add(product);db.session.commit()
    for path in sorted((ROOT / 'examples/catalog/nutrition-2-1').glob('*.json')):
        if path.name == 'manifest.json':
            continue
        doc = json.loads(path.read_bytes());catalog.stage(doc);catalog.activate(doc['source'], doc['revision'], 1);db.session.commit()
    food = db.session.execute(catalog.catalog_query().where(CatalogFood.source_food_id == '171477',
                              FoodCatalogRevision.source_id == 'usda_sr_legacy')).scalar_one()
    (out / 'qa-state.json').write_text(json.dumps({'data': 'QA fictional owner only; public catalog',
                                                  'key': product.public_id, 'candidate': 'catalog:' + food.public_id}, indent=2) + '\n', encoding='utf-8')
print('B QA ready on loopback 8032; fictional owner only', flush=True)
app.run(host='127.0.0.1', port=8032, debug=False, use_reloader=False, load_dotenv=False)
