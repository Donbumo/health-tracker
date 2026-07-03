from app.extensions import db
from app.models import MedicalLabReport, MedicalLabResult


def _user_results(user_id: int) -> list[MedicalLabResult]:
    return list(
        db.session.execute(
            db.select(MedicalLabResult)
            .join(MedicalLabReport)
            .where(
                MedicalLabResult.user_id == user_id,
                MedicalLabReport.user_id == user_id,
            )
            .order_by(
                MedicalLabReport.date.asc(),
                MedicalLabReport.id.asc(),
                MedicalLabResult.id.asc(),
            )
        ).scalars()
    )


def medical_marker_catalog(user_id: int) -> list[dict]:
    grouped: dict[str, list[MedicalLabResult]] = {}
    for result in _user_results(user_id):
        grouped.setdefault(result.marker_name.casefold(), []).append(result)

    catalog = []
    for results in grouped.values():
        latest = results[-1]
        catalog.append(
            {
                "name": latest.marker_name,
                "count": len(results),
                "latest_date": latest.report.date,
                "latest_value": (
                    latest.value if latest.value is not None else latest.value_text
                ),
                "unit": latest.unit,
                "status": latest.status,
            }
        )
    return sorted(catalog, key=lambda item: item["name"].casefold())


def medical_marker_history(user_id: int, marker_name: str) -> list[dict]:
    normalized = marker_name.strip().casefold()
    results = [
        result
        for result in _user_results(user_id)
        if result.marker_name.casefold() == normalized
    ]
    entries = []
    previous = None
    for result in results:
        change = None
        if (
            previous is not None
            and result.value is not None
            and previous.value is not None
            and result.unit.casefold() == previous.unit.casefold()
        ):
            change = result.value - previous.value
        entries.append(
            {
                "result": result,
                "report": result.report,
                "change_previous": change,
            }
        )
        previous = result
    return entries
