"""Canonical Nutrition/Energy daily series, shared by read-only facades.

Callers supply owner-scoped rows including six warm-up days. No queries/writes.
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from app.services.nutrition_intelligence import comparison_value

METRICS = (
    ('calories', 'Energía', 'kcal'), ('protein_g', 'Proteína', 'g'),
    ('total_carbs_g', 'Carbohidratos totales', 'g'), ('net_carbs_g', 'Carbohidratos netos', 'g'),
    ('fat_g', 'Grasas', 'g'), ('fiber_g', 'Fibra', 'g'),
)


def mean(values):
    known = [Decimal(v) for v in values if v is not None]
    return sum(known, Decimal(0)) / len(known) if known else None


def effective_energy_value(rows, field: str):
    if not rows:
        return None, None
    if hasattr(rows[0], 'conflicts'):
        selected = rows[0]
    else:
        from app.services.energy_days import project
        selected = project(rows)
    if selected is None or getattr(selected, field) is None:
        return None, None
    return getattr(selected, field), selected.field_sources.get(field) or selected



def build_points(rows, energy_rows, start, target):
    window_start = start - timedelta(days=6)
    energy_by_day = defaultdict(list)
    for row in energy_rows:
        energy_by_day[row.date].append(row)
    by_day = {row.date: row for row in rows}
    points = []
    for offset in range((target - window_start).days + 1):
        current = window_start + timedelta(days=offset)
        row = by_day.get(current)
        values = {field: getattr(row, field) if row else None for field, _, _ in METRICS}
        comparisons = {field: comparison_value(row, field) for field, _, _ in METRICS}
        expended, _ = effective_energy_value(energy_by_day[current], 'total_calories')
        consumed = comparisons['calories']
        balance = consumed - expended if consumed is not None and expended is not None else None
        states = {}
        nutrient_ids = {'calories': 'energy', 'protein_g': 'protein', 'total_carbs_g': 'carbohydrate_total',
                       'net_carbs_g': 'net_carbs', 'fat_g': 'fat', 'fiber_g': 'fiber'}
        for field, nutrient in nutrient_ids.items():
            detail = (row.nutrition_summary_json or {}).get(nutrient, {}) if row else {}
            states[field] = detail.get('state', 'complete' if values[field] is not None else 'unknown')
        point = {'date': current, 'values': values, 'comparisons': comparisons, 'states': states,
                 'expended': expended, 'balance': balance, 'legacy': bool(row and row.authority is None)}
        points.append(point)
        window = points[max(0, len(points) - 7):]
        point['rolling'] = {field: mean(p['comparisons'][field] for p in window) for field, _, _ in METRICS}
        point['rolling_days'] = sum(p['comparisons']['calories'] is not None for p in window)
        point['rolling_energy'] = {'intake': mean(p['comparisons']['calories'] for p in window),
                                   'expended': mean(p['expended'] for p in window), 'balance': mean(p['balance'] for p in window)}
        point['rolling_energy_days'] = {'intake': point['rolling_days'],
                                        'expended': sum(p['expended'] is not None for p in window),
                                        'balance': sum(p['balance'] is not None for p in window)}
    # Warm-up affects only moving windows, never the visible range or its totals.
    points = [p for p in points if p["date"] >= start]
    return points
