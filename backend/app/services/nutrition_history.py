"""Owner-only longitudinal nutrition, including the original legacy records.

This is a read model: never recalculates or rewrites a historical day.
"""
import calendar
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import selectinload
from app.extensions import db
from app.models import DailyNutrition, DailyEnergy, NutritionMeal, NutritionItem
from app.services.nutrition_intelligence import comparison_value, daily_summary
from app.services.dashboard.nutrition import effective_energy_value

METRICS = (
    ('calories', 'Energía', 'kcal'), ('protein_g', 'Proteína', 'g'),
    ('total_carbs_g', 'Carbohidratos totales', 'g'), ('net_carbs_g', 'Carbohidratos netos', 'g'),
    ('fat_g', 'Grasas', 'g'), ('fiber_g', 'Fibra', 'g'),
)


def mean(values):
    known = [Decimal(v) for v in values if v is not None]
    return sum(known, Decimal(0)) / len(known) if known else None


def energy_charts(points):
    """SVG coordinates derived from actual values, preserving gaps and signs."""
    charts = []
    for key, label in [('intake', 'Ingesta registrada'), ('expended', 'Gasto registrado'), ('balance', 'Balance calculable')]:
        values = [p['values']['calories'] if key == 'intake' else p[key] for p in points]
        rolling = [p['rolling_energy'][key] for p in points]
        known = [Decimal(v) for v in values + rolling if v is not None]
        low = min([Decimal(0), *known]); high = max([Decimal(0), *known])
        if low == high: high = low + 1
        padding = (high - low) / 10
        if low < 0: low -= padding
        if high > 0:high += padding
        def y(value): return round(float(Decimal(180) - (Decimal(value) - low) / (high - low) * 160), 2)
        samples = []; paths = {'daily': [], 'rolling': []}
        for index, point in enumerate(points):
            x = round(124 + index / max(1, len(points) - 1) * 552, 2)
            state = point['states']['calories'] if key == 'intake' else 'complete' if values[index] is not None else 'unknown'
            samples.append({'date': point['date'], 'x': x, 'y': y(values[index]) if values[index] is not None else None,
                            'value': values[index], 'state': state, 'rolling': rolling[index],
                            'rolling_days': point['rolling_energy_days'][key]})
        for series, sequence in [('daily', values), ('rolling', rolling)]:
            segment = []
            for index, value in enumerate(sequence):
                # A partial subtotal is a separate marker, never a complete-day line.
                allowed = value is not None and (series == 'rolling' or samples[index]['state'] == 'complete')
                if allowed: segment.append(f"{samples[index]['x']},{y(value)}")
                elif segment: paths[series].append(' '.join(segment)); segment = []
            if segment: paths[series].append(' '.join(segment))
        charts.append({'key': key, 'label': label, 'samples': samples, 'paths': paths, 'zero_y': y(0), 'has_values':bool(known),
                       'low': low, 'high': high, 'average': mean(v for i, v in enumerate(values) if v is not None and
                           (key != 'intake' or samples[i]['state'] == 'complete')),
                       'known_days': sum(p['state'] == 'complete' for p in samples),
                       'partial_days': sum(p['state'] == 'partial' for p in samples)})
    return charts


def history(user_id, target, period=30):
    if period not in (7, 30, 90):
        period = 30
    start = target - timedelta(days=period - 1)
    window_start = start - timedelta(days=6)
    # The range and recent queries are bounded separately: an empty today must
    # still expose older history even when it lies outside the selected range.
    rows = db.session.execute(db.select(DailyNutrition).where(
        DailyNutrition.user_id == user_id, DailyNutrition.date.between(window_start, target)
    ).order_by(DailyNutrition.date)).scalars().all()
    recent = db.session.execute(db.select(DailyNutrition).where(
        DailyNutrition.user_id == user_id).order_by(DailyNutrition.date.desc()).limit(12)).scalars().all()
    day = db.session.execute(db.select(DailyNutrition).where(
        DailyNutrition.user_id == user_id, DailyNutrition.date == target
    ).options(selectinload(DailyNutrition.meals).selectinload(NutritionMeal.items))).scalar_one_or_none()
    energy_rows = db.session.execute(db.select(DailyEnergy).where(
        DailyEnergy.user_id == user_id, DailyEnergy.date.between(window_start, target)
    ).order_by(DailyEnergy.updated_at.desc(), DailyEnergy.id.desc())).scalars().all()
    energy_by_day = defaultdict(list)
    for row in energy_rows:
        energy_by_day[row.date].append(row)
    by_day = {row.date: row for row in rows}
    points = []
    for offset in range(period + 6):
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
    points = points[6:]
    summary = [{'field': field, 'label': label, 'unit': unit,
                'average': mean(p['comparisons'][field] for p in points),
                'known_subtotal': sum((p['values'][field] for p in points if p['values'][field] is not None), Decimal(0))
                                  if any(p['values'][field] is not None for p in points) else None,
                'complete_days': sum(p['comparisons'][field] is not None for p in points),
                'partial_days': sum(p['states'][field] == 'partial' for p in points)} for field, label, unit in METRICS]
    month_start = target.replace(day=1)
    month_end = target.replace(day=calendar.monthrange(target.year, target.month)[1])
    month_rows=db.session.execute(db.select(DailyNutrition).where(DailyNutrition.user_id==user_id,
        DailyNutrition.date.between(month_start,month_end))).scalars().all()
    week_start=target-timedelta(days=target.weekday())
    week_rows=db.session.execute(db.select(DailyNutrition).where(DailyNutrition.user_id==user_id,
        DailyNutrition.date.between(week_start,week_start+timedelta(days=6)))).scalars().all()
    calendar_summaries=[{'label':label,'start':start_date,'end':end_date,'days':len(records),
        'energy':mean(comparison_value(record,'calories') for record in records)}
        for label,start_date,end_date,records in [('Semana',week_start,week_start+timedelta(days=6),week_rows),('Mes',month_start,month_end,month_rows)]]
    recorded = set(db.session.execute(db.select(DailyNutrition.date).where(
        DailyNutrition.user_id == user_id, DailyNutrition.date.between(month_start, month_end))).scalars())
    weeks = [[{'date': date(target.year, target.month, number), 'recorded': date(target.year, target.month, number) in recorded}
              if number else None for number in week] for week in calendar.Calendar(firstweekday=0).monthdayscalendar(target.year, target.month)]
    current = daily_summary(user_id, target)
    projection_ids = {log.projection_item_id for log in current['logs']}
    # Keep the legacy meals in this screen. A canonical projection is displayed
    # through its full MealLog and must not appear as an extra meal/item.
    legacy_meals = [{'meal': meal, 'items': [item for item in meal.items if item.id not in projection_ids]}
                    for meal in (day.meals if day else []) if any(item.id not in projection_ids for item in meal.items)]
    return {'target': target, 'period': period, 'start': start, 'points': points, 'metrics': summary,
            'day': day, 'current': current, 'recent': recent, 'latest': recent[0].date if recent else None, 'charts': energy_charts(points),
            'calendar_weeks': weeks, 'calendar_summaries':calendar_summaries,'legacy_meals': legacy_meals,
            'previous': target - timedelta(days=1), 'next': target + timedelta(days=1),
            'mean_expended': mean(p['expended'] for p in points), 'mean_balance': mean(p['balance'] for p in points)}
