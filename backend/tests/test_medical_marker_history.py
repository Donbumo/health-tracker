from datetime import date
from decimal import Decimal

from app.extensions import db
from app.models import MedicalLabReport, MedicalLabResult, User
from app.services.medical_history import (
    medical_marker_catalog,
    medical_marker_history,
)
from tests.conftest import login


def _add_result(user_id: int, report_date: date, value: str, unit: str = "unidad_qa"):
    report = MedicalLabReport(
        user_id=user_id,
        date=report_date,
        laboratory_name="Laboratorio ficticio QA",
        source="qa_fixture",
    )
    report.results.append(
        MedicalLabResult(
            user_id=user_id,
            marker_name="Marcador evolución ficticio",
            value=Decimal(value),
            unit=unit,
            status="normal",
        )
    )
    db.session.add(report)


def test_medical_marker_history_is_ordered_and_calculates_numeric_change(app, user):
    with app.app_context():
        _add_result(user, date(2026, 7, 1), "10.000000")
        _add_result(user, date(2026, 7, 3), "12.500000")
        db.session.commit()

        catalog = medical_marker_catalog(user)
        assert catalog[0]["count"] == 2
        assert catalog[0]["latest_value"] == Decimal("12.500000")
        history = medical_marker_history(user, "marcador EVOLUCIÓN ficticio")
        assert [entry["report"].date for entry in history] == [
            date(2026, 7, 1),
            date(2026, 7, 3),
        ]
        assert history[0]["change_previous"] is None
        assert history[1]["change_previous"] == Decimal("2.500000")


def test_medical_marker_change_requires_matching_numeric_units(app, user):
    with app.app_context():
        _add_result(user, date(2026, 7, 1), "10.000000", "unidad_a")
        _add_result(user, date(2026, 7, 2), "20.000000", "unidad_b")
        db.session.commit()
        history = medical_marker_history(user, "Marcador evolución ficticio")
        assert history[1]["change_previous"] is None


def test_medical_marker_views_are_isolated_by_user(app, client, user):
    with app.app_context():
        _add_result(user, date(2026, 7, 1), "10.000000")
        second = User(username="medical-marker-second", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()

    login(client)
    listing = client.get("/medical/markers")
    assert listing.status_code == 200
    assert "Marcador evolución ficticio".encode() in listing.data
    detail = client.get("/medical/markers/Marcador%20evoluci%C3%B3n%20ficticio")
    assert detail.status_code == 200
    assert b"+2" not in detail.data
    assert "no sustituye evaluación médica".encode() in detail.data

    client.post("/logout")
    login(client, "medical-marker-second", "second-password")
    empty = client.get("/medical/markers")
    assert "Marcador evolución ficticio".encode() not in empty.data
    assert client.get(
        "/medical/markers/Marcador%20evoluci%C3%B3n%20ficticio"
    ).status_code == 404
