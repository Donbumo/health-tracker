from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.extensions import db
from app.models import User, WeighIn
from app.services.weight_history import weight_history
from tests.conftest import login


def _add_records(user_id: int, weights: list[str]) -> None:
    start = datetime(2026, 7, 1, 7, tzinfo=timezone.utc)
    for offset, weight in enumerate(weights):
        db.session.add(
            WeighIn(
                user_id=user_id,
                recorded_at=start + timedelta(days=offset),
                weight_kg=Decimal(weight),
                source="fictional-test",
            )
        )
    db.session.commit()


def test_weight_history_calculates_ordered_changes_average_and_trend(app, user):
    with app.app_context():
        _add_records(user, ["75.0", "74.8", "74.7", "74.5", "74.4", "74.2", "74.0", "73.8"])
        history = weight_history(user)

        assert [entry["record"].weight_kg for entry in history["entries"]] == [
            Decimal("75.000"),
            Decimal("74.800"),
            Decimal("74.700"),
            Decimal("74.500"),
            Decimal("74.400"),
            Decimal("74.200"),
            Decimal("74.000"),
            Decimal("73.800"),
        ]
        assert history["current_weight"] == Decimal("73.800")
        assert history["change_previous"] == Decimal("-0.200")
        assert history["change_first"] == Decimal("-1.200")
        assert history["average_last_seven"] == Decimal("74.34285714285714285714285714")
        assert history["trend"] == "falling"


def test_weight_history_handles_old_minimal_records_and_stable_trend(app, user):
    with app.app_context():
        _add_records(user, ["72.0", "72.1"])
        history = weight_history(user)
        assert history["trend"] == "stable"
        assert history["average_last_seven"] is None
        assert all(entry["record"].body_fat_percentage is None for entry in history["entries"])


def test_weight_history_view_is_isolated_by_user(app, client, user):
    with app.app_context():
        _add_records(user, ["81.2"])
        second = User(username="history-second", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()
        second_id = second.id
        _add_records(second_id, ["63.4"])

    login(client)
    first_page = client.get("/weigh-ins/history")
    assert first_page.status_code == 200
    assert b"81.200" in first_page.data
    assert b"63.400" not in first_page.data

    client.post("/logout")
    login(client, "history-second", "second-password")
    second_page = client.get("/weigh-ins/history")
    assert b"63.400" in second_page.data
    assert b"81.200" not in second_page.data
