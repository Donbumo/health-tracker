"""Focal real Flask/canonical parity checks, exclusively synthetic accounts."""
import copy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import event

from app.extensions import db
from app.models import DailyNutrition, DailyEnergy, User
from app.services.dashboard import DashboardDateRange, DashboardSummaryService
from app.services.daily_balance import daily_balance
from app.services.energy_history import consultation
from app.services.nutrition_history import history
from tests.conftest import login
from tests.test_energy_experience import DAY, seed
from tests.test_nutrition_intelligence import enabled, ready


def dashboard(owner, target=DAY, period=7):
    selected = DashboardDateRange.from_query({'as_of': target.isoformat(), 'period': str(period)}, 'UTC')
    return DashboardSummaryService().build(owner, selected, 'kg')


@pytest.mark.parametrize('period', [7, 30, 90])
def test_exact_canonical_parity_and_warmup(app, user, period):
    seed(user)
    result = dashboard(user, period=period)
    nutrition = history(user, DAY, period)
    energy = consultation(user, DAY, period)
    assert len(result['trends']['energy']) == period
    for index, (p, n) in enumerate(zip(result['trends']['energy'], nutrition['points'])):
        for key, value in [('intake', n['values']['calories']), ('consumed', n['comparisons']['calories']),
                           ('expended', n['expended']), ('balance', n['balance'])]:
            assert (Decimal(p[key]) if p[key] is not None else None) == value
        assert (Decimal(p['balance']) if p['balance'] is not None else None) == daily_balance(user, n['date'])['balance']
        for alias, key, chart_index in [('consumed', 'intake', 1), ('expended', 'expended', 0), ('balance', 'balance', 2)]:
            v = p[alias + '_rolling_7d']
            assert (Decimal(v) if v is not None else None) == n['rolling_energy'][key] == energy['charts'][chart_index]['samples'][index]['rolling']
            assert p[alias + '_rolling_7d_days'] == n['rolling_energy_days'][key]
    assert result['trends']['energy'][0]['consumed_rolling_7d_days'] == 7


def test_partial_conflict_unknown_and_known_zero(app, user):
    seed(user)
    day = DAY - timedelta(days=3)
    row = db.session.scalar(db.select(DailyNutrition).where(DailyNutrition.user_id == user, DailyNutrition.date == day))
    row.calories = 0
    db.session.commit()
    points = {p['date']: p for p in dashboard(user)['trends']['energy']}
    partial = points[(DAY - timedelta(days=2)).isoformat()]
    assert partial['intake_state'] == 'partial' and Decimal(partial['intake']) == 2200
    assert partial['consumed'] is None and partial['balance'] is None
    assert partial['expenditure_state'] == 'conflict' and partial['expended'] is None
    zero = points[day.isoformat()]
    assert zero['intake_state'] == zero['expenditure_state'] == 'zero'
    assert Decimal(zero['balance']) == 0
    empty = dashboard(user, date(2041, 1, 1))['trends']['energy'][-1]
    assert empty['intake_state'] == empty['expenditure_state'] == 'unknown'
    assert empty['intake'] is empty['expended'] is empty['balance'] is None
    assert empty['balance_rolling_7d_days'] == 0


def test_balance_mean_uses_pairs_not_difference_of_means(app, user):
    # Disjoint coverage: mean balance = -100, mean intake - mean expense = -850.
    db.session.add_all([
        DailyNutrition(user_id=user, date=DAY, source='QA', calories=100),
        DailyNutrition(user_id=user, date=DAY-timedelta(days=1), source='QA', calories=400),
        DailyEnergy(user_id=user, date=DAY, source='QA', total_calories=200),
        DailyEnergy(user_id=user, date=DAY-timedelta(days=2), source='QA', total_calories=2000),
    ])
    db.session.commit()
    p = dashboard(user)['trends']['energy'][-1]
    assert Decimal(p['balance_rolling_7d']) == -100
    assert p['balance_rolling_7d_days'] == 1
    assert Decimal(p['balance_rolling_7d']) != Decimal(p['consumed_rolling_7d']) - Decimal(p['expended_rolling_7d'])


def test_meallog_projection_once_snapshot_and_flags_unchanged(app, user, enabled):
    from app.services import nutrition_intelligence as ni
    from app.models import MealLog
    draft = ready(user, enabled, DAY.isoformat())
    log, _ = ni.confirm(user, ni.confirmation_token(draft))
    db.session.add(DailyEnergy(user_id=user, date=DAY, source='QA legacy energy', total_calories=400))
    db.session.commit()
    frozen = copy.deepcopy(log.snapshot_json)
    app.config['NUTRITION_INTELLIGENCE_ENABLED'] = False
    p = dashboard(user)['trends']['energy'][-1]
    assert Decimal(p['intake']) == Decimal(p['consumed']) == 297
    assert Decimal(p['balance']) == -103
    assert log.snapshot_json == frozen
    assert db.session.query(MealLog).count() == 1
    assert app.config['NUTRITION_INTELLIGENCE_ENABLED'] is False


def test_custom_range_comparison_and_warmup_share_same_series(app, user):
    seed(user)
    selected = DashboardDateRange.from_query({'from':'2040-01-01', 'to':DAY.isoformat(), 'compare':'previous'}, 'UTC')
    result = DashboardSummaryService().build(user, selected, 'kg')
    assert len(result['trends']['energy']) == 34  # Jan 1 through Feb 3 inclusive.
    old = history(user, selected.previous_end, 30)
    previous = result['previous_period']['summary']['energy']
    assert previous['nutrition_days'] == selected.days
    assert Decimal(previous['consumed_average']) == old['metrics'][0]['average'] == 2200


def test_effective_owner_get_is_read_only_and_preserves_other_modules(app, client, user):
    seed(user)
    other = User(username='QA-unified-other', role='user')
    other.set_password('fictional-password-only')
    db.session.add(other); db.session.flush()
    db.session.add(DailyNutrition(user_id=other.id, date=DAY, source='QA other', calories=98765))
    db.session.commit()
    login(client)
    statements = []
    def observe(_conn, _cursor, statement, *_args):
        statements.append(statement.lstrip().split()[0].upper())
    event.listen(db.engine, 'before_cursor_execute', observe)
    try:
        response = client.get('/dashboard', query_string={'as_of': DAY.isoformat(), 'period': '7', 'user_id': other.id})
    finally:
        event.remove(db.engine, 'before_cursor_execute', observe)
    assert response.status_code == 200
    assert not {'INSERT', 'UPDATE', 'DELETE', 'REPLACE'} & set(statements)
    html = response.get_data(as_text=True)
    assert '98765' not in html
    for marker in ['health-date', 'health-balance', 'balance_rolling_7d_days', 'weight-title', 'training-title', 'activity-title', 'goals-title', 'body-title', '/today', '/energy/sources?date=2040-02-03']:
        assert marker in html
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert client.get('/dashboard?date=2040-02-03').headers['Location'] == '/today?date=2040-02-03'


@pytest.mark.parametrize('target', ['1900-01-01', '9998-12-31'])
def test_supported_date_boundaries_render(client, user, target):
    login(client)
    response = client.get('/dashboard', query_string={'as_of': target, 'period': 90})
    assert response.status_code == 200
    assert f'value="{target}"' in response.get_data(as_text=True)


@pytest.mark.parametrize('target', ['1899-12-31', '9999-01-01', 'invalid'])
def test_date_boundaries_rejected_without_writes(client, user, target):
    login(client)
    response = client.get('/dashboard', query_string={'as_of': target})
    assert response.status_code == 400
    assert ('AAAA-MM-DD' if target == 'invalid' else '1900 y 9998') in response.get_data(as_text=True)


def test_account_timezone_controls_default_civil_date(app, client, user):
    account = db.session.get(User, user)
    account.timezone = 'America/Mexico_City'
    db.session.commit()
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2040, 2, 4, 1, tzinfo=timezone.utc).astimezone(tz)
    login(client)
    with patch('app.services.dashboard.date_range.datetime', Clock):
        response = client.get('/dashboard')
    assert response.status_code == 200
    assert 'value="2040-02-03"' in response.get_data(as_text=True)
    assert 'America/Mexico_City' in response.get_data(as_text=True)
