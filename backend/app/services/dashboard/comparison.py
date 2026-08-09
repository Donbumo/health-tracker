from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


TWO_PLACES = Decimal("0.01")


def _decimal(value) -> Decimal | None:
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _row(
    label: str,
    current,
    previous,
    unit: str,
    *,
    relative: bool = True,
) -> dict:
    current_value = _decimal(current)
    previous_value = _decimal(previous)
    delta = (
        current_value - previous_value
        if current_value is not None and previous_value is not None
        else None
    )
    relative_change = None
    if relative and delta is not None and previous_value != 0:
        relative_change = (
            delta / abs(previous_value) * Decimal("100")
        ).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    return {
        "label": label,
        "current": current_value,
        "previous": previous_value,
        "absolute_change": delta,
        "relative_change_percent": relative_change,
        "unit": unit,
    }


class DashboardComparisonService:
    def build(self, current: dict, previous: dict, previous_range: dict) -> dict:
        energy = current["summary"]["energy"]
        old_energy = previous["summary"]["energy"]
        protein = current["summary"]["protein"]
        old_protein = previous["summary"]["protein"]
        weight = current["summary"]["weight"]
        old_weight = previous["summary"]["weight"]
        training = current["summary"]["training"]
        old_training = previous["summary"]["training"]
        rows = [
            _row("Energía ingerida", energy["consumed_total"], old_energy["consumed_total"], "kcal"),
            _row("Energía gastada", energy["expended_total"], old_energy["expended_total"], "kcal"),
            _row("Balance energético", energy["balance_total"], old_energy["balance_total"], "kcal", relative=False),
            _row("Proteína", protein["total"], old_protein["total"], "g"),
            _row("Cumplimiento de proteína", protein["compliance_percent"], old_protein["compliance_percent"], "p. p.", relative=False),
            _row("Último peso", weight["latest"], old_weight["latest"], weight["unit"]),
            _row("Cambio de peso", weight["change"], old_weight["change"], weight["unit"], relative=False),
            _row("Sesiones", training["sessions"], old_training["sessions"], "sesiones"),
            _row("Entrenamientos planeados", training["planned"], old_training["planned"], "planes"),
            _row("Adherencia", training["adherence_percent"], old_training["adherence_percent"], "p. p.", relative=False),
            _row("Duración", training["duration_seconds"], old_training["duration_seconds"], "s"),
            _row("Volumen comparable", training["volume"], old_training["volume"], training["volume_unit"]),
        ]
        return {
            "range": previous_range,
            "available": any(
                row["current"] is not None and row["previous"] is not None
                for row in rows
            ),
            "rows": rows,
            "trends": previous["trends"],
        }
