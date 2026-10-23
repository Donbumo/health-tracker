"""Bounded owner-only consultation over 0046; no writes or new persistence.

Nutrition remains the authority for intake, comparable balance and seven-day
means. Evidence is projected by energy_days, never summed by this facade.
"""
import calendar
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.extensions import db
from app.models import DailyEnergy, EnergyDay
from app.services import energy_days
from app.services.nutrition_history import history as nutrition_history, mean


METRICS = (
    ('total_calories', 'Calorías totales', 'kcal'),
    ('active_calories', 'Calorías activas', 'kcal'),
    ('resting_calories', 'Calorías de reposo', 'kcal'),
    ('steps', 'Pasos', 'pasos'),
    ('distance_meters', 'Distancia', 'm'),
)
STATES = {'known': 'Conocido', 'zero': 'Cero conocido', 'unknown': 'Sin dato',
          'conflict': 'Conflicto pendiente', 'partial': 'Subtotal conocido · parcial'}
MIN_DAY, MAX_DAY = date(1900, 1, 1), date(9998, 12, 31)


def supported_day(target):
    return target is not None and MIN_DAY <= target <= MAX_DAY


def local_today(owner, fallback='UTC', now=None):
    """Dates already stored are never reinterpreted when timezone changes."""
    try:
        zone = ZoneInfo(owner.timezone or fallback)
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo(fallback)
    return (now or datetime.now(timezone.utc)).astimezone(zone).date(), str(zone)


def field_state(row, field):
    if row is not None and field in row.conflicts:
        return 'conflict'
    value = getattr(row, field, None)
    return 'unknown' if value is None else 'zero' if value == 0 else 'known'


def field_source(row, field):
    if row is None or getattr(row, field, None) is None:
        return 'Sin fuente comparable'
    if row.registry and field in (row.registry.resolutions_json or {}):
        return 'Resolución confirmada'
    source = row.field_sources.get(field)
    return source.source if source else 'Resolución confirmada'


def day_state(row):
    if row is None:
        return 'unknown'
    if row.conflicts:
        return 'conflict'
    if row.total_calories is not None:
        return 'zero' if row.total_calories == 0 else 'known'
    return 'partial' if any(getattr(row, key) is not None for key, _, _ in METRICS) else 'unknown'


def chart(key, label, unit, samples):
    """Display geometry only. Never interpolate daily observations."""
    values = [Decimal(v) for p in samples for v in (p['value'], p['rolling']) if v is not None]
    low, high = min([Decimal(0), *values]), max([Decimal(0), *values])
    if low == high:
        high = low + 1
    def y(value):
        return round(float(180 - (Decimal(value) - low) / (high - low) * 150), 2)
    zero = y(0)
    paths, segment = [], []
    width = round(min(32, 480 / max(1, len(samples))), 2)
    for index, sample in enumerate(samples):
        x = round(116 + (index + .5) / len(samples) * 548, 2)
        sample.update(x=x, width=width)
        sample['y'] = y(sample['value']) if sample['value'] is not None else None
        sample['bar_y'] = min(zero, sample['y']) if sample['y'] is not None else None
        sample['bar_height'] = max(2, abs(zero - sample['y'])) if sample['y'] is not None else None
        if sample['rolling'] is not None:
            segment.append(f"{x},{y(sample['rolling'])}")
        elif segment:
            paths.append(' '.join(segment)); segment = []
    if segment:
        paths.append(' '.join(segment))
    return {'key': key, 'label': label, 'unit': unit, 'samples': samples,
            'paths': paths, 'zero_y': zero, 'low': low, 'high': high,
            'known_days': sum(p['state'] in ('known', 'zero') for p in samples),
            'partial_days': sum(p['state'] == 'partial' for p in samples),
            'has_values': bool(values)}


def consultation(user_id, target, period=30):
    if period not in (7, 30, 90):
        period = 30
    # Reuse the exact Nutrition read model (including its six warm-up days).
    nutrition = nutrition_history(user_id, target, period)
    start = nutrition['start']
    warmup = start - timedelta(days=6)
    rows = {row.date: row for row in energy_days.views(user_id, start=warmup, end=target)}
    selected = rows.get(target)
    fields = [{'key': key, 'label': label, 'unit': unit,
               'value': getattr(selected, key, None), 'state': field_state(selected, key),
               'source': field_source(selected, key)} for key, label, unit in METRICS]
    charts = []
    for key, label, unit in [('expended', 'Gasto total', 'kcal'), ('intake', 'Ingesta · contexto Nutrition', 'kcal'), ('balance', 'Balance comparable', 'kcal')]:
        samples = []
        for p in nutrition['points']:
            value = p['values']['calories'] if key == 'intake' else p[key]
            state = (('partial' if p['states']['calories'] == 'partial' else 'unknown' if value is None else 'zero' if value == 0 else 'known')
                     if key == 'intake' else field_state(rows.get(p['date']), 'total_calories') if key == 'expended'
                     else 'unknown' if value is None else 'zero' if value == 0 else 'known')
            source = field_source(rows.get(p['date']), 'total_calories') if key == 'expended' else 'Nutrition 2.1' if key == 'intake' else 'Ingesta comparable − gasto canónico'
            samples.append({'date': p['date'], 'value': value, 'state': state, 'source': source,
                            'rolling': p['rolling_energy'][key], 'rolling_days': p['rolling_energy_days'][key]})
        charts.append(chart(key, label, unit, samples))
    trends = []
    for key, label, unit in METRICS:
        samples = []
        for p in nutrition['points']:
            day = p['date']; row = rows.get(day)
            window = [getattr(rows.get(day - timedelta(days=offset)), key, None) for offset in range(7)]
            samples.append({'date': day, 'value': getattr(row, key, None), 'state': field_state(row, key),
                            'source': field_source(row, key), 'rolling': mean(window),
                            'rolling_days': sum(value is not None for value in window)})
        # Known observations (including zero) or a known warm-up mean only.
        if any(p['value'] is not None or p['rolling'] is not None for p in samples):
            trends.append(chart(key, label, unit, samples))
    month_start = target.replace(day=1)
    month_end = target.replace(day=calendar.monthrange(target.year, target.month)[1])
    month_rows = {row.date: row for row in energy_days.views(user_id, start=month_start, end=month_end)}
    weeks = [[{'date': date(target.year, target.month, day), 'state': day_state(month_rows.get(date(target.year, target.month, day)))}
              if day else None for day in week] for week in calendar.Calendar().monthdayscalendar(target.year, target.month)]
    # A single date aggregate can find older history without materializing it.
    latest_date = db.session.scalar(db.select(db.func.max(DailyEnergy.date)).outerjoin(EnergyDay, db.and_(
        EnergyDay.user_id == DailyEnergy.user_id, EnergyDay.date == DailyEnergy.date)).where(
            DailyEnergy.user_id == user_id, DailyEnergy.date.between(MIN_DAY, MAX_DAY),
            DailyEnergy.deleted_at.is_(None), EnergyDay.deleted_at.is_(None)))
    latest = energy_days.view(user_id, latest_date) if latest_date else None
    return {'target': target, 'period': period, 'start': start, 'selected': selected,
            'day_state': day_state(selected), 'fields': fields, 'charts': charts, 'trends': trends,
            'calendar_weeks': weeks, 'month_start': month_start, 'month_end': month_end,
            'previous_month': month_start - timedelta(days=1) if month_start > MIN_DAY else None,
            'next_month': month_end + timedelta(days=1) if month_end < MAX_DAY else None,
            'previous': target - timedelta(days=1) if target > MIN_DAY else None,
            'next': target + timedelta(days=1) if target < MAX_DAY else None,
            'latest': latest, 'states': STATES, 'nutrition_point': nutrition['points'][-1]}
