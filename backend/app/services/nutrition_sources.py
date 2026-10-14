"""Read-only public product lookup; no uploads, private diet text or AI calls.

OFF remains an attributed, separate source. Responses are proposals to review,
not catalog writes or authoritative certification of a commercial label.
"""
import copy
import json
import re
import threading
import time
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
import urllib.parse
import urllib.request
from app.services.nutrition_math import NUTRIENTS, NutritionError

OFF_FIELDS = 'code,product_name,product_name_es,brands,quantity,serving_size,nutrition_data_per,nutriments,categories_tags,last_modified_t,ingredients_text'
OFF_KEYS = {'energy-kcal':'energy', 'proteins':'protein', 'carbohydrates':'carbohydrate_total',
            'fat':'fat', 'fiber':'fiber', 'sugars':'sugar', 'sodium':'sodium', 'potassium':'potassium',
            'calcium':'calcium', 'iron':'iron', 'magnesium':'magnesium', 'phosphorus':'phosphorus',
            'zinc':'zinc', 'vitamin-c':'vitamin_c', 'vitamin-d':'vitamin_d', 'vitamin-b6':'vitamin_b6',
            'vitamin-b12':'vitamin_b12', 'vitamin-b1':'thiamin', 'vitamin-b2':'riboflavin'}


def finite_source_number(value):
    number = Decimal(str(value))
    if not number.is_finite() or number < 0 or number > Decimal('100000000'):
        raise NutritionError('Valor publicado fuera de rango.')
    if number.as_tuple().exponent < -12:
        if 0 < number < Decimal('0.0000000000005'):
            raise NutritionError('Valor positivo por debajo de la precisión admitida; no se convierte en cero.')
        number = number.quantize(Decimal('0.000000000001'), rounding=ROUND_HALF_UP)
    return format(number,'f')


def off_food(product):
    if not isinstance(product,dict):raise NutritionError('Respuesta sin producto estructurado.')
    name = product.get('product_name_es') or product.get('product_name')
    code = str(product.get('code') or '')
    basis = product.get('nutrition_data_per')
    if not isinstance(name,str) or not name.strip() or not re.fullmatch(r'\d{8,14}', code) or basis not in {'100g','100ml'}:
        raise NutritionError('Producto sin nombre, código o base explícita; revisa su etiqueta.')
    vector = {};ambiguous={}
    nutrients = product.get('nutriments') or {}
    if not isinstance(nutrients,dict):raise NutritionError('Tabla externa no estructurada.')
    for external, internal in OFF_KEYS.items():
        raw = nutrients.get(external+'_100g')
        if raw in (None, ''):
            continue
        if internal=='carbohydrate_total':
            # The normalized OFF key is not evidence of total vs available/net
            # carbohydrate on a particular label/country. Preserve, don't sum.
            ambiguous['carbohydrates']={'value':str(raw),'unit':'g','basis':basis,'classification':'unconfirmed_total_vs_net'}
            continue
        original_unit=str(nutrients.get(external+'_unit') or '')
        if '%' in original_unit or 'percent' in original_unit.lower():
            ambiguous[internal]={'value':str(raw),'original_unit':original_unit,'classification':'reference_basis_required'}
            continue
        # OFF's normalized _100g fields use grams for nutrient masses, even
        # when *_unit carries the original label unit. Preserve that evidence.
        factor = Decimal(1) if NUTRIENTS[internal][1] in {'g','kcal'} else Decimal(1000) if NUTRIENTS[internal][1]=='mg' else Decimal(1000000)
        try:
            value = finite_source_number(Decimal(str(raw))*factor)
        except (ValueError, ArithmeticError, NutritionError):
            continue
        modifier = nutrients.get(external+'_modifier')
        entry = {'state':'known','value':value,'unit':NUTRIENTS[internal][1],
                 'provenance':{'method':'label_declared_unverified','source_key':external+'_100g',
                    'original_value':str(raw),'original_unit':str(nutrients.get(external+'_unit') or ''),
                    'normalization':'OFF normalized mass in grams; converted to registry unit; at most 12 decimals'}}
        if modifier == '<' and Decimal(value)>0:
            entry.update(state='below_limit',value=None,limit=value)
        elif modifier in {'~','>','<=','>='}:
            entry.update(state='unknown',value=None)
        vector[internal] = entry
    servings = []
    serving = product.get('serving_size') or ''
    matches = re.findall(r'(\d+(?:[.,]\d+)?)\s*(ml|g)\b', serving, flags=re.I)
    if len(matches)==1 and Decimal(matches[0][0].replace(',','.'))>0:
        servings.append({'id':'label-serving','label':serving[:200],
                         'amount':matches[0][0].replace(',','.'),'unit':matches[0][1].lower()})
    return {'source':'open_food_facts','source_food_id':code,'revision':str(product.get('last_modified_t') or 'undated'),
            'name':str(name)[:200],'source_name':str(product.get('product_name') or name)[:1000],
            'preparation':'Producto comercial · revisar etiqueta','basis_amount':'100',
            'basis_unit':'ml' if basis=='100ml' else 'g','density_g_ml':None,'nutrients':vector,'servings':servings,
            'provenance':{'method':'published_community_label','ambiguous_fields':ambiguous},
            'metadata':{'aliases':[str(product.get('product_name') or name)[:1000]],'brand':str(product.get('brands') or '')[:200] or None,
                'barcode':code,'food_type':'commercial','preparation_state':'unspecified','language':'es/en',
                'quality':'label_declared_unverified','net_content_text':str(product.get('quantity') or '')[:200],
                'ingredient_text':str(product.get('ingredients_text') or '')[:10000],
                'limitations':'Datos comunitarios: confirma producto, unidad y distinción total/netos con su etiqueta.',
                'license':'ODbL-1.0','attribution':'Open Food Facts contributors'}}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


class OpenFoodFactsLookup:
    """Explicit lookup, bounded cache and conservative per-worker rate limit.

At most one upstream request / 30 s / worker. With the default two workers this
stays below both OFF's search (10/min) and product (15/min) limits.
"""
    def __init__(self):
        self.lock = threading.Lock()
        self.cache = {}
        self.last_request = 0

    def lookup(self, text, *, consent=False):
        if not consent:
            raise NutritionError('Confirma la consulta pública externa; no se envía tu documento.')
        query = str(text).strip()[:80]
        if not query:
            raise NutritionError('Escribe una marca o código de barras.')
        with self.lock:
            now = time.monotonic()
            cached = self.cache.get(query)
            if cached and now-cached[0]<3600:
                return copy.deepcopy(cached[1])
            if now-self.last_request<30:
                raise NutritionError('Espera antes de otra consulta externa. La búsqueda local sigue disponible.',429)
            self.last_request = now
            if re.fullmatch(r'\d{8,14}',query):
                suffix = '/api/v2/product/'+query+'?'+urllib.parse.urlencode({'fields':OFF_FIELDS})
            else:
                # v2 supports structured brands, not arbitrary full-text search.
                suffix = '/api/v2/search?'+urllib.parse.urlencode({'brands_tags':query,'countries_tags_en':'mexico',
                    'page_size':12,'fields':OFF_FIELDS})
            request = urllib.request.Request('https://world.openfoodfacts.org'+suffix,
                headers={'User-Agent':'HealthTrackerNutrition/2.1 (https://github.com/Donbumo/health-tracker)'})
            try:
                with urllib.request.build_opener(_NoRedirect).open(request,timeout=8) as response:
                    raw = response.read(1_000_001)
                if len(raw)>1_000_000:
                    raise ValueError('Bound exceeded')
                document = json.loads(raw)
                if not isinstance(document,dict):raise ValueError('Unstructured public response')
            except Exception as error:
                raise NutritionError('La fuente externa no está disponible; puedes crear un producto privado.',503) from error
            products = document.get('products') or ([document['product']] if document.get('status')==1 and document.get('product') else [])
            if not isinstance(products,list):raise NutritionError('La fuente externa devolvió un formato no compatible.',503)
            proposals = []
            for product in products[:12]:
                try:
                    proposals.append(off_food(product))
                except NutritionError:
                    continue
            if len(self.cache)>=128:
                self.cache.pop(next(iter(self.cache)))
            self.cache[query]=(now,proposals)
            return copy.deepcopy(proposals)


public_lookup = OpenFoodFactsLookup()
