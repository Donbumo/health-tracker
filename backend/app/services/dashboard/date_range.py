from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


MAX_DASHBOARD_DAYS = 366
DEFAULT_PRESET = "7d"
PRESET_LABELS = {
    "today": "Hoy",
    "7d": "Últimos 7 días",
    "30d": "Últimos 30 días",
    "90d": "Últimos 90 días",
    "this-month": "Este mes",
    "previous-month": "Mes anterior",
    "this-year": "Este año",
}
SPANISH_MONTHS = (
    "ene",
    "feb",
    "mar",
    "abr",
    "may",
    "jun",
    "jul",
    "ago",
    "sep",
    "oct",
    "nov",
    "dic",
)


class DashboardRangeError(ValueError):
    """Human-readable validation error for dashboard GET filters."""


def _parse_date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise DashboardRangeError(
            f"La fecha {label} debe usar el formato AAAA-MM-DD."
        ) from error


def _month_end(value: date) -> date:
    next_month = (
        date(value.year + 1, 1, 1)
        if value.month == 12
        else date(value.year, value.month + 1, 1)
    )
    return next_month - timedelta(days=1)


def _human_date(value: date) -> str:
    return f"{value.day} {SPANISH_MONTHS[value.month - 1]} {value.year}"


@dataclass(frozen=True)
class DashboardDateRange:
    preset: str
    start_date: date
    end_date: date
    timezone: str
    compare_previous: bool = False

    @property
    def days(self) -> int:
        return (self.end_date - self.start_date).days + 1

    @property
    def previous_end(self) -> date:
        return self.start_date - timedelta(days=1)

    @property
    def previous_start(self) -> date:
        return self.previous_end - timedelta(days=self.days - 1)

    @property
    def label(self) -> str:
        if self.start_date == self.end_date:
            return _human_date(self.start_date)
        return f"{_human_date(self.start_date)} – {_human_date(self.end_date)}"

    @property
    def previous_label(self) -> str:
        if self.previous_start == self.previous_end:
            return _human_date(self.previous_start)
        return f"{_human_date(self.previous_start)} – {_human_date(self.previous_end)}"

    def utc_bounds(self) -> tuple[datetime, datetime]:
        """Return a DST-safe, half-open UTC interval for local inclusive dates."""
        zone = ZoneInfo(self.timezone)
        start_local = datetime.combine(self.start_date, time.min, tzinfo=zone)
        end_local = datetime.combine(
            self.end_date + timedelta(days=1), time.min, tzinfo=zone
        )
        return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)

    def previous_period(self) -> "DashboardDateRange":
        return DashboardDateRange(
            preset="custom",
            start_date=self.previous_start,
            end_date=self.previous_end,
            timezone=self.timezone,
            compare_previous=False,
        )

    def as_dict(self) -> dict:
        return {
            "preset": self.preset,
            "from": self.start_date.isoformat(),
            "to": self.end_date.isoformat(),
            "timezone": self.timezone,
            "days": self.days,
            "label": self.label,
            "compare": "previous" if self.compare_previous else None,
            "previous_from": (
                self.previous_start.isoformat() if self.compare_previous else None
            ),
            "previous_to": (
                self.previous_end.isoformat() if self.compare_previous else None
            ),
            "previous_label": self.previous_label if self.compare_previous else None,
        }

    @classmethod
    def from_query(
        cls,
        query,
        timezone_name: str,
        *,
        today: date | None = None,
    ) -> "DashboardDateRange":
        try:
            zone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as error:
            raise DashboardRangeError(
                "La zona horaria guardada no es válida; revísala en Preferencias."
            ) from error

        local_today = today or datetime.now(zone).date()
        raw_from = (query.get("from") or query.get("start") or "").strip()
        raw_to = (query.get("to") or query.get("end") or "").strip()
        raw_compare = (query.get("compare") or "").strip()
        compare_previous = raw_compare == "previous"
        if raw_compare not in {"", "previous"}:
            raise DashboardRangeError(
                "La comparación solicitada no es válida. Usa el periodo anterior."
            )

        if raw_from or raw_to:
            if not raw_from or not raw_to:
                raise DashboardRangeError(
                    "Indica las dos fechas para usar un rango personalizado."
                )
            preset = "custom"
            start_date = _parse_date(raw_from, "inicial")
            end_date = _parse_date(raw_to, "final")
        else:
            raw_period = (query.get("period") or "").strip()
            if raw_period:
                if raw_period not in {"7", "30", "90"}:
                    raise DashboardRangeError("El periodo seleccionado no es válido.")
                preset = f"{raw_period}d"
            else:
                preset = (query.get("preset") or DEFAULT_PRESET).strip()
            if preset not in PRESET_LABELS:
                raise DashboardRangeError("El periodo seleccionado no es válido.")
            end_date = local_today
            if preset == "today":
                start_date = local_today
            elif preset in {"7d", "30d", "90d"}:
                start_date = local_today - timedelta(days=int(preset[:-1]) - 1)
            elif preset == "this-month":
                start_date = local_today.replace(day=1)
            elif preset == "previous-month":
                end_date = local_today.replace(day=1) - timedelta(days=1)
                start_date = end_date.replace(day=1)
            else:
                start_date = local_today.replace(month=1, day=1)

        if start_date > end_date:
            raise DashboardRangeError(
                "La fecha inicial no puede ser posterior a la fecha final."
            )
        days = (end_date - start_date).days + 1
        if days > MAX_DASHBOARD_DAYS:
            raise DashboardRangeError(
                f"El rango no puede superar {MAX_DASHBOARD_DAYS} días."
            )
        return cls(
            preset=preset,
            start_date=start_date,
            end_date=end_date,
            timezone=timezone_name,
            compare_previous=compare_previous,
        )
