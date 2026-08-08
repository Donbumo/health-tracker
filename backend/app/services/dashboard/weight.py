from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from app.extensions import db
from app.models import WeighIn
from app.services.dashboard.date_range import DashboardDateRange


LB_PER_KG = Decimal("2.2046226218487757")
THREE_PLACES = Decimal("0.001")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _convert(value: Decimal, unit: str) -> Decimal:
    converted = value * LB_PER_KG if unit == "lb" else value
    return converted.quantize(THREE_PLACES, rounding=ROUND_HALF_UP)


class WeightTrendService:
    def build(
        self,
        user_id: int,
        date_range: DashboardDateRange,
        unit: str,
    ) -> dict:
        start_at, end_at = date_range.utc_bounds()
        records = db.session.execute(
            db.select(WeighIn)
            .where(
                WeighIn.user_id == user_id,
                WeighIn.recorded_at >= start_at,
                WeighIn.recorded_at < end_at,
            )
            .order_by(WeighIn.recorded_at, WeighIn.id)
        ).scalars().all()
        zone = ZoneInfo(date_range.timezone)
        prepared = [
            {
                "recorded_at": _as_utc(record.recorded_at),
                "date": _as_utc(record.recorded_at).astimezone(zone).date(),
                "value": _convert(record.weight_kg, unit),
            }
            for record in records
        ]
        points = []
        for item in prepared:
            window_start = item["date"] - timedelta(days=6)
            window = [
                candidate["value"]
                for candidate in prepared
                if window_start <= candidate["date"] <= item["date"]
            ]
            moving_average = None
            if len(window) >= 2:
                moving_average = (
                    sum(window, Decimal("0")) / Decimal(len(window))
                ).quantize(THREE_PLACES, rounding=ROUND_HALF_UP)
            points.append({**item, "moving_average_7d": moving_average})

        values = [point["value"] for point in points]
        average = (
            (sum(values, Decimal("0")) / Decimal(len(values))).quantize(
                THREE_PLACES, rounding=ROUND_HALF_UP
            )
            if values
            else None
        )
        return {
            "summary": {
                "unit": unit,
                "latest": values[-1] if values else None,
                "latest_date": points[-1]["date"] if points else None,
                "change": values[-1] - values[0] if len(values) >= 2 else None,
                "average": average,
                "minimum": min(values) if values else None,
                "maximum": max(values) if values else None,
                "entries": len(points),
                "moving_average_7d": (
                    points[-1]["moving_average_7d"] if points else None
                ),
            },
            "trend": points,
            "coverage": {"weight_entries": len(points)},
        }
