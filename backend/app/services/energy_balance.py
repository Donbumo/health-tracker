"""Owner-scoped energy balance over the existing canonical daily series.

No writes, source ranking, nutritional recomputation or presentation rounding.
"""
from datetime import timedelta
from decimal import Decimal

from app.services.dashboard.date_range import DashboardDateRange
from app.services.dashboard.nutrition import NutritionTrendService
from app.services.nutrition_series import build_points


def previous_energy_period(period, mode="auto"):
    end = period.start_date - timedelta(days=1)
    # A whole calendar month compares with the whole preceding calendar month.
    calendar_month = (period.start_date.day == 1
                      and (period.start_date.year, period.start_date.month) == (period.end_date.year, period.end_date.month)
                      and (period.end_date + timedelta(days=1)).day == 1)
    if mode not in {"auto", "equal_days", "calendar_month"} or mode == "calendar_month" and not calendar_month:
        from app.services.dashboard.date_range import DashboardRangeError
        raise DashboardRangeError("La comparación por mes calendario requiere un único mes completo.")
    calendar_month = calendar_month and mode != "equal_days"
    start = end.replace(day=1) if calendar_month else end - timedelta(days=period.days - 1)
    previous = DashboardDateRange.from_query(
        {"from": start.isoformat(), "to": end.isoformat()}, period.timezone
    )
    return previous, "calendar_month" if calendar_month else "equal_days"


def _sum(values):
    known = [value for value in values if value is not None]
    return sum(known, Decimal(0)) if known else None


def _average(values):
    known = [value for value in values if value is not None]
    return {"value": _sum(known) / len(known) if known else None, "days": len(known)}


class EnergyBalanceService:
    def build(self, user_id, period, *, include_daily=False, comparison_mode="auto"):
        # Validate even internal callers; query bounds and work stay bounded.
        DashboardDateRange.from_query(
            {"from": period.start_date.isoformat(), "to": period.end_date.isoformat()},
            period.timezone,
        )
        if period.compare_previous:
            previous, mode = previous_energy_period(period, comparison_mode)
        loaded = NutritionTrendService().load(user_id, period)
        nutrition = {row.date: row for row in loaded["nutrition"]}
        energy = {row.date: row for row in loaded["energy"]}
        points = build_points(loaded["nutrition"], loaded["energy"], period.start_date, period.end_date)
        days, exclusions, provenance = [], [], []
        for point in points:
            day = point["date"]
            food, expenditure = nutrition.get(day), energy.get(day)
            consumed, expended = point["comparisons"]["calories"], point["expended"]
            recorded = point["values"]["calories"]
            intake_state = ("partial" if recorded is not None and consumed is None else
                            "unknown" if consumed is None else "zero" if consumed == 0 else "known")
            expenditure_state = ("conflict" if expenditure and "total_calories" in expenditure.conflicts else
                                 "unknown" if expended is None else "zero" if expended == 0 else "known")
            reasons = []
            if consumed is None:
                reasons.append("intake_" + intake_state)
            if expended is None:
                reasons.append("expenditure_" + expenditure_state)
            state = "complete" if not reasons else "unknown" if recorded is None and expenditure is None else "partial"
            source = expenditure.field_sources.get("total_calories") if expended is not None else None
            resolved = expenditure and expenditure.registry and "total_calories" in (expenditure.registry.resolutions_json or {})
            sources = {"consumed": food.source if food and recorded is not None else None,
                       "expended": ("user_override" if resolved or source is None else source.source)
                       if expended is not None else None}
            days.append({"date": day, "consumed_kcal": recorded, "comparable_consumed_kcal": consumed,
                         "expended_kcal": expended, "balance_kcal": point["balance"],
                         "intake_state": intake_state, "expenditure_state": expenditure_state,
                         "coverage": state, "sources": sources})
            if reasons:
                exclusions.append({"date": day, "reasons": reasons})
            for metric, source_name in sources.items():
                if source_name is not None:
                    provenance.append({"metric": metric, "source": source_name, "date": day})

        paired = [day for day in days if day["balance_kcal"] is not None]
        balances = [day["balance_kcal"] for day in paired]
        complete = len(paired) == period.days
        current_period = period.as_dict()
        if period.compare_previous:
            current_period.update(previous_from=previous.start_date.isoformat(), previous_to=previous.end_date.isoformat(),
                                  previous_label=previous.label)
        result = {
            "period": current_period,
            "metrics": {
                "consumed_kcal": _sum(day["consumed_kcal"] for day in days),
                "expended_kcal": _sum(day["expended_kcal"] for day in days),
                "comparable_consumed_kcal": _sum(day["comparable_consumed_kcal"] for day in paired),
                "comparable_expended_kcal": _sum(day["expended_kcal"] for day in paired),
                "balance_kcal": _sum(balances),
                "complete_balance_kcal": _sum(balances) if complete else None,
            },
            "averages": {
                "consumed_kcal": _average(day["comparable_consumed_kcal"] for day in days),
                "expended_kcal": _average(day["expended_kcal"] for day in days),
                "balance_kcal": _average(balances),
            },
            "coverage": {
                "requested_days": period.days,
                "intake_recorded_days": sum(day["consumed_kcal"] is not None for day in days),
                "intake_known_days": sum(day["comparable_consumed_kcal"] is not None for day in days),
                "expenditure_known_days": sum(day["expended_kcal"] is not None for day in days),
                "both_known_days": len(paired),
                **{state + "_days": sum(day["coverage"] == state for day in days)
                   for state in ("complete", "partial", "unknown")},
                "is_complete": complete,
            },
            "excluded_days": exclusions,
            "extremes": {
                "lowest_balance": min(paired, key=lambda day: day["balance_kcal"]) if paired else None,
                "highest_balance": max(paired, key=lambda day: day["balance_kcal"]) if paired else None,
            },
            "daily": days if include_daily else None,
            "provenance": provenance,
            "calculation": "health_tracker: canonical comparable intake minus total expenditure; active calories already included",
            "warnings": [] if complete else ["partial_period_balance: only days with both comparable metrics contribute"],
            "limitations": ["Recorded coverage does not prove all meals or expenditure were captured.",
                            "Recorded intake totals may include partial subtotals; averages use only comparable intake."],
            "comparison": None,
        }
        if period.compare_previous:
            prior = self.build(user_id, previous, include_daily=include_daily)
            deltas = {}
            for metric in ("consumed_kcal", "expended_kcal", "balance_kcal"):
                left, right = result["averages"][metric], prior["averages"][metric]
                valid = left["days"] > 0 and right["days"] > 0
                metric_complete = left["days"] == period.days and right["days"] == previous.days
                deltas[metric] = {"daily_average_delta": left["value"] - right["value"] if valid else None,
                                  "complete_total_delta": result["metrics"][metric] - prior["metrics"][metric] if metric_complete else None,
                                  "current_days": left["days"], "previous_days": right["days"],
                                  "state": "complete" if metric_complete else
                                           "partial_sample" if valid else "unavailable"}
            left, right = result["metrics"]["complete_balance_kcal"], prior["metrics"]["complete_balance_kcal"]
            result["comparison"] = {"mode": mode, "previous": prior, "deltas": deltas,
                                    "complete_balance_delta_kcal": left - right if left is not None and right is not None else None}
        return result
