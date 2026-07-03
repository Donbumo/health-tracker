from datetime import date
from decimal import Decimal

from app.extensions import db
from app.models import MedicalLabReport, MedicalLabResult, User


def test_medical_report_persists_multiple_numeric_and_text_results(app, user):
    with app.app_context():
        report = MedicalLabReport(
            user_id=user,
            date=date(2026, 7, 3),
            laboratory_name="Laboratorio ficticio QA",
            doctor_name=None,
            source="qa_fixture",
            notes="Reporte completamente ficticio.",
        )
        report.results = [
            MedicalLabResult(
                user_id=user,
                marker_name="Marcador numérico ficticio",
                marker_code="QA-NUM",
                value=Decimal("12.500000"),
                unit="unidad_qa",
                reference_min=Decimal("10.000000"),
                reference_max=Decimal("15.000000"),
                status="normal",
            ),
            MedicalLabResult(
                user_id=user,
                marker_name="Marcador textual ficticio",
                value_text="no reactivo ficticio",
                unit="cualitativo",
                reference_text="no reactivo",
                status="unknown",
            ),
        ]
        db.session.add(report)
        db.session.commit()

        stored = db.session.execute(db.select(MedicalLabReport)).scalar_one()
        assert stored.user_id == user
        assert stored.doctor_name is None
        assert len(stored.results) == 2
        assert stored.results[0].value == Decimal("12.500000")
        assert stored.results[0].value_text is None
        assert stored.results[1].value is None
        assert stored.results[1].value_text == "no reactivo ficticio"
        assert all(result.report_id == stored.id for result in stored.results)


def test_medical_reports_are_queryable_only_by_selected_user(app, user):
    with app.app_context():
        second = User(username="medical-model-second", role="user")
        second.set_password("second-password")
        db.session.add(second)
        db.session.flush()
        report = MedicalLabReport(
            user_id=user,
            date=date(2026, 7, 3),
            source="qa_fixture",
        )
        report.results.append(
            MedicalLabResult(
                user_id=user,
                marker_name="Marcador aislado ficticio",
                value=Decimal("1.000000"),
                unit="unidad_qa",
                status="unknown",
            )
        )
        db.session.add(report)
        db.session.commit()

        assert db.session.execute(
            db.select(MedicalLabReport).where(MedicalLabReport.user_id == second.id)
        ).scalar_one_or_none() is None
        assert db.session.execute(
            db.select(MedicalLabResult).where(MedicalLabResult.user_id == second.id)
        ).scalar_one_or_none() is None
