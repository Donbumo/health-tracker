from decimal import Decimal

from app.extensions import db
from app.models import WeighIn


STABLE_THRESHOLD_KG = Decimal("0.100")


def weight_history(user_id: int) -> dict:
    records = list(
        db.session.execute(
            db.select(WeighIn)
            .where(WeighIn.user_id == user_id)
            .order_by(WeighIn.recorded_at.asc(), WeighIn.id.asc())
        ).scalars()
    )
    if not records:
        return {
            "entries": [],
            "current_weight": None,
            "change_previous": None,
            "change_first": None,
            "average_last_seven": None,
            "trend": None,
        }

    first_weight = records[0].weight_kg
    entries = []
    previous_weight = None
    for record in records:
        entries.append(
            {
                "record": record,
                "change_previous": (
                    record.weight_kg - previous_weight
                    if previous_weight is not None
                    else None
                ),
                "change_first": record.weight_kg - first_weight,
            }
        )
        previous_weight = record.weight_kg

    current_weight = records[-1].weight_kg
    change_previous = entries[-1]["change_previous"]
    if change_previous is None or abs(change_previous) <= STABLE_THRESHOLD_KG:
        trend = "stable"
    elif change_previous > 0:
        trend = "rising"
    else:
        trend = "falling"

    recent = records[-7:]
    average_last_seven = None
    if len(recent) == 7:
        average_last_seven = sum(
            (record.weight_kg for record in recent),
            Decimal("0"),
        ) / Decimal("7")

    return {
        "entries": entries,
        "current_weight": current_weight,
        "change_previous": change_previous,
        "change_first": current_weight - first_weight,
        "average_last_seven": average_last_seven,
        "trend": trend,
    }
