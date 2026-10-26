"""Read-only micronutrient experience over consumed summaries and snapshots.

No current food vector is used to calculate history. Links resolve identities
only; mutable definitions are explicitly separate from consumed evidence.
"""
from datetime import timedelta
from decimal import Decimal

from app.extensions import db
from app.models import DailyNutrition, FoodProduct, NutritionItem, NutritionMeal, Recipe
from app.models.nutrition_intelligence import CatalogFood, FoodCatalogRevision
from app.services import nutrition_intelligence as ni
from app.services.nutrition_math import LEGACY, NUTRIENTS, NutritionError, precise, summarize
from app.services.nutrition_series import mean


GROUPS = [('energy', 'Energía'), ('macro', 'Macronutrientes'),
          ('vitamin', 'Vitaminas'), ('mineral', 'Minerales'), ('other', 'Otros nutrientes')]


def stored_summary(day):
    """Persisted daily authority; legacy totals never gain invented micros."""
    summary = summarize([])
    if day is None:
        return summary
    if day.nutrition_summary_json:
        summary.update(day.nutrition_summary_json)
        return summary
    for key, field in LEGACY.items():
        value = getattr(day, field)
        summary[key].update(value=str(value) if value is not None else None,
                            state='partial' if value is not None else 'unknown')
    return summary


def identities(user_id, logs):
    """Batch owner checks. Resolve links, never resolve calculation inputs."""
    foods = [entry['food'] for log in logs for entry in log.snapshot_json['ingredients']]
    refs = {food.get('ref') for food in foods}
    catalog = db.session.execute(db.select(CatalogFood.public_id).join(FoodCatalogRevision).where(
        FoodCatalogRevision.state == 'validated',
        CatalogFood.public_id.in_([ref[8:] for ref in refs if ref and ref.startswith('catalog:')])
    )).scalars().all()
    personal = db.session.execute(db.select(FoodProduct.public_id).where(
        FoodProduct.user_id == user_id, FoodProduct.is_active.is_(True),
        FoodProduct.public_id.in_([ref[5:] for ref in refs if ref and ref.startswith('user:')])
    )).scalars().all()
    recipes = db.session.execute(db.select(Recipe.id).where(
        Recipe.user_id == user_id, Recipe.id.in_([log.recipe_id for log in logs if log.recipe_id])
    )).scalars().all()
    return {'foods': {'catalog:' + key for key in catalog} | {'user:' + key for key in personal},
            'recipes': set(recipes)}


def qualifiers(logs):
    """Qualitative composition evidence, independent of effective declarations."""
    result = {key: {'trace': 0, 'below_limit': 0} for key in NUTRIENTS}
    for log in logs:
        for entry in log.snapshot_json['ingredients']:
            for key, value in entry['contribution'].items():
                if key in result and value['state'] in result[key]:
                    result[key][value['state']] += 1
    return result


@precise
def trend(points, key):
    samples = []
    values = [Decimal(p['summary'][key]['value']) for p in points if p['summary'][key]['value'] is not None]
    high = max(values) if values else Decimal(0)
    scale = high if high else Decimal(1)
    paths, segment = [], []
    for index, point in enumerate(points):
        item = point['summary'][key]
        value = item['value']
        x = round(60 + index / max(1, len(points) - 1) * 600, 2)
        y = round(float(180 - Decimal(value) / scale * 150), 2) if value is not None else None
        samples.append(dict(date=point['date'], x=x, y=y, **item))
        if value is not None and item['state'] == 'complete':
            segment.append(f'{x},{y}')
        elif segment:
            paths.append(' '.join(segment))
            segment = []
    if segment:
        paths.append(' '.join(segment))
    complete = [s['value'] for s in samples if s['state'] == 'complete' and s['value'] is not None]
    partial = [s['value'] for s in samples if s['state'] == 'partial' and s['value'] is not None]
    return {'samples': samples, 'paths': paths, 'has_values': bool(values), 'high': high,
            'average': mean(complete), 'valid_days': len(complete),
            'partial_average': mean(partial), 'partial_days': len(partial),
            'unknown_days': len(samples) - len(complete) - len(partial)}


def overview(user_id, target, period=30, nutrient='iron'):
    period = period if period in (7, 30, 90) else 30
    nutrient = nutrient if nutrient in NUTRIENTS else 'iron'
    try:
        start = target - timedelta(days=period - 1)
        previous = target - timedelta(days=1)
        next_date = target + timedelta(days=1)
    except OverflowError as error:
        raise NutritionError('Fecha fuera del período admitido.') from error
    current = ni.daily_summary(user_id, target)
    rows = db.session.execute(db.select(DailyNutrition).where(
        DailyNutrition.user_id == user_id, DailyNutrition.date.between(start, target)
    )).scalars().all()
    by_date = {row.date: row for row in rows}
    points = [{'date': start + timedelta(days=i),
               'summary': stored_summary(by_date.get(start + timedelta(days=i)))} for i in range(period)]
    # Same authority as the daily screen, including reviewed disjoint aggregates.
    points[-1]['summary'] = current['summary']
    legacy = []
    day = current['day']
    if day:
        projections = {log.projection_item_id for log in current['logs']}
        excluded = set((day.authority_baseline_json or {}).get('included_item_ids', [])) if day.authority == 'disjoint_aggregate' else set()
        items = db.session.execute(db.select(NutritionItem).join(NutritionMeal).where(
            NutritionItem.user_id == user_id, NutritionMeal.user_id == user_id,
            NutritionMeal.daily_nutrition_id == day.id
        ).order_by(NutritionMeal.sort_order, NutritionItem.sort_order)).scalars().all()
        legacy = [{'name': item.name, 'quantity': item.quantity, 'unit': item.unit,
                   'summary': summarize([ni.legacy_ingredient(item)]),
                   'included': day.authority == 'derived' and item.id not in excluded}
                  for item in items if item.id not in projections]
    return dict(current, target=target, start=start, period=period, nutrient=nutrient,
                groups=GROUPS, chart=trend(points, nutrient), legacy=legacy,
                links=identities(user_id, current['logs']), qualifiers=qualifiers(current['logs']),
                previous=previous, next=next_date)


def meal(user_id, key):
    log = ni.owned_log(user_id, key)
    return {'log': log, 'groups': GROUPS, 'links': identities(user_id, [log])}
