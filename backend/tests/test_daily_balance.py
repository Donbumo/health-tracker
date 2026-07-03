from datetime import date
from decimal import Decimal

from app.extensions import db
from app.models import DailyEnergy, DailyNutrition, User
from app.services.daily_balance import daily_balance
from tests.conftest import login


def test_daily_balance_combines_nutrition_and_energy(app, client, user):
    with app.app_context():
        db.session.add(
            DailyNutrition(
                user_id=user,
                date=date(2026, 7, 4),
                source="fictional-test",
                calories=Decimal("2100"),
                protein_g=Decimal("140"),
                fat_g=Decimal("70"),
                net_carbs_g=Decimal("180"),
                fiber_g=Decimal("30"),
            )
        )
        db.session.add(
            DailyEnergy(
                user_id=user,
                date=date(2026, 7, 4),
                source="fictional-test",
                total_calories=Decimal("2450"),
                active_calories=Decimal("650"),
            )
        )
        db.session.commit()

        summary = daily_balance(user, date(2026, 7, 4))
        assert summary["calories_consumed"] == Decimal("2100.000")
        assert summary["calories_expended"] == Decimal("2450.00")
        assert summary["balance"] == Decimal("-350.000")
        assert summary["complete"] is True

    login(client)
    response = client.get("/daily-balance", query_string={"date": "2026-07-04"})
    assert response.status_code == 200
    assert b"-350" in response.data
    assert b"D\xc3\xada incompleto" not in response.data


def test_daily_balance_handles_missing_sides_without_error(app, client, user):
    with app.app_context():
        db.session.add(
            DailyNutrition(
                user_id=user,
                date=date(2026, 7, 5),
                source="fictional-test",
                calories=Decimal("2000"),
            )
        )
        db.session.add(
            DailyEnergy(
                user_id=user,
                date=date(2026, 7, 6),
                source="fictional-test",
                total_calories=Decimal("2300"),
            )
        )
        db.session.commit()
        nutrition_only = daily_balance(user, date(2026, 7, 5))
        energy_only = daily_balance(user, date(2026, 7, 6))
        assert nutrition_only["balance"] is None
        assert energy_only["balance"] is None
        assert nutrition_only["complete"] is False
        assert energy_only["complete"] is False

    login(client)
    response = client.get("/daily-balance", query_string={"date": "2026-07-05"})
    assert response.status_code == 200
    assert "Día incompleto".encode() in response.data
    assert client.get("/daily-balance?date=not-a-date").status_code == 400


def test_daily_balance_is_isolated_by_user(app, client, user):
    with app.app_context():
        db.session.add(
            DailyNutrition(
                user_id=user,
                date=date(2026, 7, 4),
                source="fictional-test",
                calories=Decimal("2100"),
            )
        )
        second = User(username="balance-second-user", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()
        second_id = second.id
        summary = daily_balance(second_id, date(2026, 7, 4))
        assert summary["nutrition"] is None
        assert summary["balance"] is None

    login(client, "balance-second-user", "second-password")
    response = client.get("/daily-balance", query_string={"date": "2026-07-04"})
    assert response.status_code == 200
    assert b"2100" not in response.data
    assert "Día incompleto".encode() in response.data
