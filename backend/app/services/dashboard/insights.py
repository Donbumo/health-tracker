from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


def _number(value, digits=1) -> str:
    if value is None:
        return ""
    quantizer = Decimal("1") if digits == 0 else Decimal("0.1")
    return format(Decimal(value).quantize(quantizer, rounding=ROUND_HALF_UP), "f")


def _relative(current, previous):
    if current is None or previous is None or Decimal(previous) == 0:
        return None
    return (
        (Decimal(current) - Decimal(previous))
        / abs(Decimal(previous))
        * Decimal("100")
    )


class DashboardInsightsService:
    def build(self, current: dict, previous: dict, period_days: int) -> list[dict]:
        insights = []
        energy = current["summary"]["energy"]
        old_energy = previous["summary"]["energy"]
        if energy["nutrition_days"]:
            insights.append(
                {
                    "type": "coverage",
                    "text": (
                        f"Registraste nutrición {energy['nutrition_days']} de "
                        f"{period_days} días."
                    ),
                }
            )
        else:
            insights.append(
                {"type": "coverage", "text": "No hay nutrición registrada en el periodo."}
            )

        expenditure_change = _relative(
            energy["expended_average"], old_energy["expended_average"]
        )
        if expenditure_change is not None:
            direction = "aumentó" if expenditure_change > 0 else "disminuyó"
            insights.append(
                {
                    "type": "comparison",
                    "text": (
                        f"Tu gasto promedio {direction} "
                        f"{_number(abs(expenditure_change), 1)}% respecto al periodo anterior."
                    ),
                }
            )
        elif not energy["energy_days"]:
            insights.append(
                {"type": "coverage", "text": "No hay gasto energético registrado en el periodo."}
            )

        weight = current["summary"]["weight"]
        if weight["change"] is not None:
            verb = "bajó" if Decimal(weight["change"]) < 0 else "subió" if Decimal(weight["change"]) > 0 else "se mantuvo"
            amount = _number(abs(Decimal(weight["change"])), 1)
            text = (
                f"Tu peso {verb} {amount} {weight['unit']} entre la primera y la última medición."
                if Decimal(weight["change"]) != 0
                else "Tu primera y última medición de peso del periodo fueron iguales."
            )
            insights.append({"type": "weight", "text": text})

        activity = current["summary"]["activity"]
        if activity["paired_goal_days"]:
            insights.append(
                {
                    "type": "goal",
                    "text": (
                        f"Alcanzaste tu meta de pasos {activity['days_at_goal']} de "
                        f"{activity['paired_goal_days']} días comparables."
                    ),
                }
            )

        training = current["summary"]["training"]
        if training["sessions"]:
            duration = (
                f" y {_number(training['duration_minutes'], 0)} minutos registrados"
                if training["duration_minutes"] is not None
                else ""
            )
            insights.append(
                {
                    "type": "training",
                    "text": (
                        f"Completaste {training['sessions']} "
                        f"{'sesión' if training['sessions'] == 1 else 'sesiones'}{duration}."
                    ),
                }
            )

        if len(insights) < 3 and not weight["entries"]:
            insights.append(
                {"type": "coverage", "text": "No hay mediciones de peso en el periodo."}
            )
        return insights[:5]
