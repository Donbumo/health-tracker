from datetime import date
from decimal import Decimal

from app.extensions import db
from app.models import MedicalLabReport, MedicalLabResult, User
from tests.conftest import login


def _add_report(user_id: int, report_date: date, marker_count: int = 2):
    report = MedicalLabReport(
        user_id=user_id,
        date=report_date,
        laboratory_name="Laboratorio dashboard ficticio",
        source="qa_fixture",
    )
    for index in range(marker_count):
        report.results.append(
            MedicalLabResult(
                user_id=user_id,
                marker_name=f"Marcador dashboard ficticio {index + 1}",
                value=Decimal(str(index + 1)),
                unit="unidad_qa",
                status="unknown",
            )
        )
    db.session.add(report)
    db.session.commit()
    return report.id


def test_dashboard_shows_empty_and_latest_medical_report(app, client, user):
    login(client)
    empty = client.get("/dashboard", query_string={"date": "2026-07-03"})
    assert empty.status_code == 200
    assert b"Sin estudios registrados" in empty.data
    assert b'href="/medical/labs/manual"' in empty.data

    with app.app_context():
        _add_report(user, date(2026, 7, 1), 1)
        latest_id = _add_report(user, date(2026, 7, 3), 2)
        _add_report(user, date(2026, 7, 4), 3)

    dashboard = client.get("/dashboard", query_string={"date": "2026-07-03"})
    assert dashboard.status_code == 200
    assert b"Laboratorio dashboard ficticio" in dashboard.data
    assert b"2 marcadores registrados" in dashboard.data
    assert f'href="/medical/labs/{latest_id}"'.encode() in dashboard.data
    assert b"3 marcadores registrados" not in dashboard.data


def test_dashboard_medical_summary_is_isolated_by_user(app, client, user):
    with app.app_context():
        _add_report(user, date(2026, 7, 3), 2)
        second = User(username="medical-dashboard-second", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.commit()

    login(client, "medical-dashboard-second", "second-password")
    dashboard = client.get("/dashboard", query_string={"date": "2026-07-03"})
    assert dashboard.status_code == 200
    assert b"Laboratorio dashboard ficticio" not in dashboard.data
    assert b"Sin estudios registrados" in dashboard.data
