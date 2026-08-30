from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from app.extensions import db
from app.models import WeighIn
from app.services.dashboard.date_range import DashboardDateRange
from app.services.dashboard.provenance import source_label, source_labels


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
    def load(self, user_id: int, date_range: DashboardDateRange) -> list[WeighIn]:
        start_at, end_at = date_range.utc_bounds()
        return db.session.execute(
            db.select(WeighIn)
            .where(
                WeighIn.user_id == user_id,
                WeighIn.recorded_at >= start_at,
                WeighIn.recorded_at < end_at,
            )
            .order_by(WeighIn.recorded_at, WeighIn.id)
        ).scalars().all()

    def build_from_rows(
        self,
        records: list[WeighIn],
        date_range: DashboardDateRange,
        unit: str,
    ) -> dict:
        start_at, end_at = date_range.utc_bounds()
        zone = ZoneInfo(date_range.timezone)
        prepared = [
            {
                "recorded_at": _as_utc(record.recorded_at),
                "date": _as_utc(record.recorded_at).astimezone(zone).date(),
                "value": _convert(record.weight_kg, unit),
                "source": source_label(
                    record.source, has_source_file=bool(record.source_file_id)
                ),
                "record": record,
            }
            for record in records
            if start_at <= _as_utc(record.recorded_at) < end_at
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
            points.append(
                {
                    key: value
                    for key, value in {**item, "moving_average_7d": moving_average}.items()
                    if key != "record"
                }
            )

        values = [point["value"] for point in points]
        average = (
            (sum(values, Decimal("0")) / Decimal(len(values))).quantize(
                THREE_PLACES, rounding=ROUND_HALF_UP
            )
            if values
            else None
        )
        body_metric_specs = (
            ("body_fat", "Grasa corporal", "body_fat_percentage", "%", False),
            ("muscle_mass", "Masa muscular", "muscle_mass_kg", unit, True),
            ("water", "Agua corporal", "water_percentage", "%", False),
            ("visceral_fat", "Grasa visceral", "visceral_fat", "índice", False),
            ("bmi", "IMC", "bmi", "", False),
        )
        body_metrics = []
        for key, label, field, metric_unit, convert_mass in body_metric_specs:
            metric_points = []
            for item in prepared:
                raw_value = getattr(item["record"], field)
                if raw_value is None:
                    continue
                metric_points.append(
                    {
                        "recorded_at": item["recorded_at"],
                        "date": item["date"],
                        "value": _convert(raw_value, unit) if convert_mass else raw_value,
                        "source": item["source"],
                    }
                )
            if not metric_points:
                continue
            metric_values = [point["value"] for point in metric_points]
            body_metrics.append(
                {
                    "key": key,
                    "label": label,
                    "unit": metric_unit,
                    "latest": metric_values[-1],
                    "change": (
                        metric_values[-1] - metric_values[0]
                        if len(metric_values) >= 2
                        else None
                    ),
                    "minimum": min(metric_values),
                    "maximum": max(metric_values),
                    "entries": len(metric_points),
                    "points": metric_points,
                }
            )

        change = values[-1] - values[0] if len(values) >= 2 else None
        return {
            "summary": {
                "unit": unit,
                "latest": values[-1] if values else None,
                "latest_date": points[-1]["date"] if points else None,
                "change": change,
                "trend": (
                    "down" if change is not None and change < 0 else
                    "up" if change is not None and change > 0 else
                    "stable" if change == 0 else None
                ),
                "average": average,
                "minimum": min(values) if values else None,
                "maximum": max(values) if values else None,
                "entries": len(points),
                "moving_average_7d": (
                    points[-1]["moving_average_7d"] if points else None
                ),
                "sources": source_labels(point["source"] for point in points),
            },
            "body": {
                "metrics": body_metrics,
                "default_metric": body_metrics[0]["key"] if body_metrics else None,
            },
            "trend": points,
            "coverage": {
                "weight_entries": len(points),
                "body_measurements": sum(
                    1
                    for item in prepared
                    if any(
                        getattr(item["record"], field) is not None
                        for _, _, field, _, _ in body_metric_specs
                    )
                ),
            },
        }

    def build(
        self,
        user_id: int,
        date_range: DashboardDateRange,
        unit: str,
    ) -> dict:
        return self.build_from_rows(self.load(user_id, date_range), date_range, unit)
