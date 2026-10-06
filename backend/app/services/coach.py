"""Owner-scoped, provider-independent Coach briefs from existing read models.

Signal rules are deliberately conservative: missing records mean unknown, never
zero intake or a medical conclusion. No domain write occurs in this module.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
import time as clock
from typing import TypedDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import current_app

from app.services.dashboard.date_range import DashboardDateRange
from app.services.dashboard.summary import DashboardSummaryService
from app.services.gym_strength import StrengthReader


class CoachBrief(TypedDict):
    period: dict
    generated_at: str
    signals: list[dict]
    top_priorities: list[dict]
    coverage: dict
    domains: list[str]
    possible_actions: list[dict]


def _decimal(value):
    try:
        result = Decimal(str(value)) if value is not None else None
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result is None or result.is_finite() else None


def _value(value):
    number = _decimal(value)
    return format(number.quantize(Decimal("0.01")), "f") if number is not None else None


def _coverage(observed, expected, *, minimum):
    observed = max(0, int(observed or 0))
    expected = max(1, int(expected or 1))
    return {"state": "sufficient" if observed >= minimum else "partial" if observed else "insufficient",
            "observed": observed, "expected": expected}


def _evidence(label, value, source, period):
    return {"label": label, "value": value, "source": source, "period": period}


class CoachSignalEngine:
    """Project dashboard/Gym read models into bounded, auditable signals."""

    PRIORITY = {"high": 3, "medium": 2, "low": 1}

    @classmethod
    def _signal(cls, *, period, domain, kind, metric, title, message, current=None,
                baseline=None, change=None, unit=None, coverage=None, provenance=(),
                evidence=(), action=None, identity=None, severity="low"):
        if not evidence:
            raise ValueError("Una señal Coach necesita evidencia estructurada.")
        return {"signal_id": f"{period['preset']}:{domain}:{kind}:{metric}" + (f":{identity}" if identity else ""),
                "domain": domain, "type": kind, "severity": severity, "period": period,
                "metric": metric, "current": _value(current), "baseline": _value(baseline),
                "change": _value(change), "unit": unit, "coverage": coverage,
                "provenance": list(provenance), "evidence": list(evidence),
                "title": title, "message": message, "action": action}

    @classmethod
    def _rank(cls, signals):
        def key(item):
            coverage = item["coverage"] or {}
            confidence = min(1, coverage.get("observed", 0) / max(1, coverage.get("expected", 1)))
            magnitude = abs(_decimal(item["change"]) or 0) if item["type"] in {
                "energy_change", "steps_change", "volume_change", "adherence_change",
                "training_nutrition_change"} else 0
            return (-cls.PRIORITY[item["severity"]], -(item["action"] is not None),
                    -confidence, -magnitude, item["signal_id"])
        unique = {}
        for item in signals:
            prior = unique.get(item["signal_id"])
            if prior is None or key(item) < key(prior):
                unique[item["signal_id"]] = item
        return sorted(unique.values(), key=key)

    @classmethod
    def build(cls, dashboard, gym, *, generated_at=None):
        generated_at = generated_at or datetime.now(timezone.utc)
        period = dashboard["range"]
        previous = dashboard["previous_period"]
        summary = dashboard["summary"]
        old = previous["summary"]
        daily_period = {"preset": "today", "from": period["to"], "to": period["to"],
                        "timezone": period["timezone"], "days": 1}
        daily, weekly = [], []

        # Gym states come directly from GymProgressionEngine via StrengthReader.
        for evaluation in gym["evaluations"]:
            state = evaluation["state"]
            if state == "increase_load":
                kind, severity = "progression_candidate", "high"
            elif state == "increase_reps":
                kind, severity = "increase_reps", "medium"
            elif state == "review":
                kind, severity = "review", "medium"
            elif state == "maintain":
                kind, severity = "maintain", "low"
            else:
                kind, severity = "insufficient_data", "low"
            action = None
            if state == "increase_load" and (evaluation.get("proposal") or {}).get("field_changes"):
                action = {"capability": "training.progression.update",
                          "program_id": evaluation["program_id"],
                          "prescription_id": evaluation["prescription_id"],
                          "label": "Preparar cambio"}
            source = "GymProgressionEngine · " + evaluation["rule_version"]
            signal = cls._signal(period=period, domain="gym", kind=kind,
                metric="exercise_progression", identity=evaluation["program_id"] + ":" + evaluation["prescription_id"],
                title=evaluation["name"], message=evaluation["label"] + ". " + evaluation["evidence"][-1],
                current=evaluation["current"].get("load"),
                unit=evaluation["current"].get("unit"),
                coverage=_coverage(min(2, len(evaluation["evidence"]) - 1), 2, minimum=2),
                provenance=(source,),
                evidence=(_evidence("Regla", evaluation["rule_version"], source, period),
                          *((_evidence("Propuesta sin aplicar", evaluation["proposal"].get("load"), source, period),)
                            if evaluation.get("proposal") else ()),
                          *(_evidence("Sesión u objetivo", line, source, period) for line in evaluation["evidence"])),
                action=action, severity=severity)
            if kind in {"progression_candidate", "increase_reps", "review"}:
                daily.append(signal)
            weekly.append(signal)

        # Today uses the last points of the same seven-day dashboard snapshot.
        today_energy = dashboard["trends"]["energy"][-1]
        if today_energy["consumed"] is None:
            daily.append(cls._signal(period=daily_period, domain="nutrition", kind="insufficient_data",
                metric="energy_intake", title="Nutrición sin registro hoy",
                message="No hay un registro energético de hoy; no se infiere cuánto comiste.",
                coverage=_coverage(0, 1, minimum=1), provenance=("Dashboard · nutrición",),
                evidence=(_evidence("Días con ingesta registrada", 0, "Dashboard · nutrición", daily_period),)))
        else:
            daily.append(cls._signal(period=daily_period, domain="nutrition", kind="recorded",
                metric="energy_intake", title="Ingesta registrada hoy",
                message="Hay un valor registrado hoy; puede faltar información de otras comidas.",
                current=today_energy["consumed"], unit="kcal",
                coverage=_coverage(1, 1, minimum=1),
                provenance=tuple(today_energy.get("sources") or ("Dashboard · nutrición",)),
                evidence=(_evidence("Ingesta registrada", today_energy["consumed"], "Dashboard · nutrición", daily_period),)))

        today_steps = dashboard["trends"]["activity"][-1]
        prior_steps = [point["steps"] for point in dashboard["trends"]["activity"][:-1]
                       if point["steps"] is not None]
        if today_steps["steps"] is not None and len(prior_steps) >= 3:
            baseline_steps = sum(prior_steps) / len(prior_steps)
            if baseline_steps > 0 and abs(today_steps["steps"] / baseline_steps - 1) >= 0.2:
                daily.append(cls._signal(period=daily_period, domain="activity", kind="steps_change",
                    metric="daily_steps", title="Pasos registrados hoy frente a días recientes",
                    message="Comparación descriptiva con días que tienen pasos registrados; el día aún puede estar incompleto.",
                    current=today_steps["steps"], baseline=baseline_steps,
                    change=(today_steps["steps"] / baseline_steps - 1) * 100, unit="pasos",
                    coverage=_coverage(len(prior_steps), 6, minimum=3),
                    provenance=("Dashboard · actividad",),
                    evidence=(_evidence("Hoy", today_steps["steps"], "Dashboard · actividad", daily_period),
                              _evidence("Media de días recientes registrados", _value(baseline_steps),
                                        "Dashboard · actividad", period)), severity="low"))

        def change_signal(domain, metric, label, current, baseline, observed, old_observed,
                          source, threshold, unit, kind, severity="medium"):
            now_value, old_value = _decimal(current), _decimal(baseline)
            if observed < 5 or old_observed < 5 or now_value is None or old_value is None or old_value <= 0:
                return None
            change = (now_value / old_value - 1) * 100
            if abs(change) < Decimal(str(threshold)):
                return None
            direction = "subió" if change > 0 else "bajó"
            return cls._signal(period=period, domain=domain, kind=kind, metric=metric,
                title=f"{label} {direction} en los registros",
                message=f"Promedio registrado {direction} frente a los 7 días anteriores comparables.",
                current=now_value, baseline=old_value, change=change, unit=unit,
                coverage=_coverage(observed, 7, minimum=5), provenance=(source,),
                evidence=(_evidence("Promedio actual", _value(now_value), source, period),
                          _evidence("Promedio anterior", _value(old_value), source, previous["range"]),
                          _evidence("Cobertura actual/anterior", f"{observed}/7 y {old_observed}/7 días", source, period)),
                severity=severity)

        intake = change_signal("nutrition", "energy_average", "La energía registrada",
            summary["energy"]["consumed_average"], old["energy"]["consumed_average"],
            summary["energy"]["nutrition_days"], old["energy"]["nutrition_days"],
            "Dashboard · nutrición", 10, "kcal", "energy_change")
        if intake:
            weekly.append(intake)
        elif summary["energy"]["nutrition_days"] < 5:
            weekly.append(cls._signal(period=period, domain="nutrition", kind="insufficient_data",
                metric="energy_average", title="Cobertura nutricional incompleta",
                message="Los registros disponibles son insuficientes para comparar ingesta semanal.",
                coverage=_coverage(summary["energy"]["nutrition_days"], 7, minimum=5),
                provenance=("Dashboard · nutrición",),
                evidence=(_evidence("Días con ingesta", summary["energy"]["nutrition_days"],
                                    "Dashboard · nutrición", period),)))

        protein = summary["nutrition"]["averages"]["protein"]
        if protein["goal"] is not None and protein["days"] >= 5 and protein["goal_days"] >= 5:
            ratio = _decimal(protein["percent_of_goal"])
            if ratio is not None and ratio < 80:
                weekly.append(cls._signal(period=period, domain="nutrition", kind="macro_adherence",
                    metric="protein", title="Proteína registrada bajo el objetivo",
                    message="El promedio de los días registrados está por debajo del objetivo configurado.",
                    current=protein["average"], baseline=protein["goal"],
                    change=ratio, unit="g", coverage=_coverage(protein["days"], 7, minimum=5),
                    provenance=("Dashboard · nutrición", "Meta propia"),
                    evidence=(_evidence("Promedio registrado", protein["average"], "Dashboard · nutrición", period),
                              _evidence("Meta configurada", protein["goal"], "Meta propia", period)),
                    severity="medium"))

        steps = change_signal("activity", "steps_average", "El promedio de pasos",
            summary["activity"]["steps_average"], old["activity"]["steps_average"],
            summary["activity"]["step_days"], old["activity"]["step_days"],
            "Dashboard · actividad", 15, "pasos", "steps_change")
        if steps:
            weekly.append(steps)

        active_calories = change_signal("activity", "active_calories", "El gasto activo registrado",
            _decimal(summary["activity"]["active_calories"]) / summary["activity"]["active_calorie_days"]
            if summary["activity"]["active_calorie_days"] and _decimal(summary["activity"]["active_calories"]) is not None else None,
            _decimal(old["activity"]["active_calories"]) / old["activity"]["active_calorie_days"]
            if old["activity"]["active_calorie_days"] and _decimal(old["activity"]["active_calories"]) is not None else None,
            summary["activity"]["active_calorie_days"], old["activity"]["active_calorie_days"],
            "Dashboard · actividad", 15, "kcal activas", "active_energy_change", "low")
        if active_calories:
            weekly.append(active_calories)

        weight = summary["weight"]
        weight_change = _decimal(weight["change"])
        if weight["entries"] >= 3 and weight_change is not None:
            kind = "weight_stable" if abs(weight_change) < Decimal("0.3") else "weight_trend"
            weekly.append(cls._signal(period=period, domain="body", kind=kind,
                metric="weight", title="Peso registrado: " + ("estable" if kind == "weight_stable" else "cambio reciente"),
                message="Cambio descriptivo entre mediciones del periodo; no es una interpretación médica.",
                current=weight["latest"], change=weight_change, unit=weight["unit"],
                coverage=_coverage(weight["entries"], 3, minimum=3),
                provenance=tuple(weight["sources"] or ("Dashboard · peso",)),
                evidence=(_evidence("Última medición", weight["latest"], "Dashboard · peso", period),
                          _evidence("Cambio entre extremos", weight["change"], "Dashboard · peso", period)),
                severity="low"))
        elif weight["entries"] < 2:
            weekly.append(cls._signal(period=period, domain="body", kind="insufficient_data",
                metric="weight", title="Peso: sin tendencia comparable",
                message="Se necesitan al menos dos mediciones para describir un cambio.",
                coverage=_coverage(weight["entries"], 2, minimum=2),
                provenance=("Dashboard · peso",),
                evidence=(_evidence("Mediciones", weight["entries"], "Dashboard · peso", period),)))

        training, old_training = summary["training"], old["training"]
        if training["sessions"] and old_training["sessions"]:
            diff = training["sessions"] - old_training["sessions"]
            if diff:
                weekly.append(cls._signal(period=period, domain="training", kind="training_frequency_change",
                    metric="sessions", title="Cambió la frecuencia registrada",
                    message="Sesiones registradas frente a los 7 días anteriores.",
                    current=training["sessions"], baseline=old_training["sessions"], change=diff,
                    unit="sesiones", coverage=_coverage(training["sessions"], 7, minimum=1),
                    provenance=("Dashboard · entrenamiento",),
                    evidence=(_evidence("Sesiones actuales", training["sessions"], "Dashboard · entrenamiento", period),
                              _evidence("Sesiones anteriores", old_training["sessions"], "Dashboard · entrenamiento", previous["range"])),
                    severity="low"))
        if training["planned"] >= 2 and training["planned"] - training["completed_plans"] >= 2:
            weekly.append(cls._signal(period=period, domain="training", kind="repeated_missed_sessions",
                metric="planned_workouts", title="Entrenamientos planeados por revisar",
                message="Hay al menos dos entrenamientos planeados sin marca de completado; revisa su estado antes de concluir que se omitieron.",
                current=training["completed_plans"], baseline=training["planned"], unit="entrenamientos",
                coverage=_coverage(training["completed_plans"], training["planned"], minimum=training["planned"]),
                provenance=("Dashboard · planificación",),
                evidence=(_evidence("Completados/planeados", f'{training["completed_plans"]}/{training["planned"]}',
                                    "Dashboard · planificación", period),), severity="medium"))
        if training["planned"] >= 2 and old_training["planned"] >= 2:
            now_adherence = _decimal(training["adherence_percent"])
            old_adherence = _decimal(old_training["adherence_percent"])
            if now_adherence is not None and old_adherence is not None and abs(now_adherence - old_adherence) >= 15:
                weekly.append(cls._signal(period=period, domain="training", kind="adherence_change",
                    metric="planned_completion", title="Cambió el cumplimiento del plan",
                    message="Completados sobre planeados en periodos equivalentes.",
                    current=now_adherence, baseline=old_adherence, change=now_adherence-old_adherence,
                    unit="p. p.", coverage=_coverage(training["planned"], 7, minimum=2),
                    provenance=("Dashboard · planificación",),
                    evidence=(_evidence("Periodo actual", f'{training["completed_plans"]}/{training["planned"]}', "Dashboard · planificación", period),
                              _evidence("Periodo anterior", f'{old_training["completed_plans"]}/{old_training["planned"]}', "Dashboard · planificación", previous["range"])),
                    severity="medium"))

        gym_week = gym["coach_volume"]
        if gym_week["comparison"] is not None and abs(_decimal(gym_week["comparison"])) >= 5:
            weekly.append(cls._signal(period=period, domain="gym", kind="volume_change",
                metric="comparable_volume", title="Cambió el volumen comparable de Gym",
                message="Comparación solo de modos e identidades compatibles entre semanas.",
                current=gym_week["volume"], baseline=gym_week.get("previous_volume"), change=gym_week["comparison"],
                unit=gym_week["unit"] + "·reps", coverage=_coverage(gym_week["sessions"], 7, minimum=1),
                provenance=("StrengthReader · volumen comparable",),
                evidence=(_evidence("Volumen actual", gym_week["volume"], "StrengthReader", period),
                          _evidence("Volumen anterior", gym_week.get("previous_volume"), "StrengthReader", previous["range"]),
                          _evidence("Cambio porcentual", gym_week["comparison"], "StrengthReader", period)),
                severity="medium"))

        for goal in dashboard["goals"]:
            if goal["actual"] is None or goal["percent"] is None:
                continue
            metric = goal["type"]
            observed = (summary["activity"]["step_days"] if metric == "daily_steps" else
                        summary["energy"]["nutrition_days"] if metric.startswith("nutrition_") else
                        training["planned"] if metric == "scheduled_workouts_completion" else
                        training["sessions"] if metric.startswith("training_") else 0)
            if observed < 5 and metric in {"daily_steps", "nutrition_calories", "nutrition_protein", "nutrition_carbohydrates", "nutrition_fat"}:
                continue
            if not observed:
                continue
            percent = _decimal(goal["percent"])
            if percent is None or not (percent >= 100 or percent < 80):
                continue
            weekly.append(cls._signal(period=period, domain="goals", kind="goal_reached" if percent >= 100 else "goal_gap",
                metric=metric, title=f'{goal["label"]}: ' + ("objetivo alcanzado" if percent >= 100 else "por debajo del objetivo"),
                message="Comparación descriptiva con tu meta configurada y los registros disponibles.",
                current=goal["actual"], baseline=goal["target"], change=percent,
                unit=goal["unit"], coverage=_coverage(observed, 7, minimum=5 if metric.startswith("nutrition_") or metric == "daily_steps" else 1),
                provenance=("Dashboard · objetivos", goal["source"]),
                evidence=(_evidence("Valor registrado", goal["actual"], "Dashboard", period),
                          _evidence("Meta configurada", goal["target"], goal["source"], period)),
                severity="medium" if percent < 80 else "low"))

        # Cross-domain wording stays descriptive and requires both complete windows.
        volume_up = _decimal(gym_week["comparison"])
        if (intake and _decimal(intake["change"]) < 0 and volume_up is not None and volume_up >= 5
                and summary["energy"]["nutrition_days"] >= 5 and old["energy"]["nutrition_days"] >= 5
                and not gym_week["partial"]):
            weekly.append(cls._signal(period=period, domain="cross_domain", kind="training_nutrition_change",
                metric="volume_and_registered_energy", title="Entrenamiento e ingesta registrada cambiaron",
                message="Subió el volumen comparable de Gym y bajó el promedio de energía registrada. No se infiere causalidad ni ingesta real no registrada.",
                current=volume_up, baseline=intake["change"], unit="%",
                coverage=_coverage(min(summary["energy"]["nutrition_days"], old["energy"]["nutrition_days"]), 7, minimum=5),
                provenance=("StrengthReader", "Dashboard · nutrición"),
                evidence=(_evidence("Cambio de volumen", gym_week["comparison"], "StrengthReader", period),
                          _evidence("Cambio de promedio registrado", intake["change"], "Dashboard · nutrición", period)),
                severity="medium"))

        if dashboard["goals"] and not any(item["domain"] == "goals" for item in weekly):
            weekly.append(cls._signal(period=period, domain="goals", kind="insufficient_data",
                metric="configured_goals", title="Metas: revisa cobertura antes de comparar",
                message="Hay metas configuradas, pero los registros no justifican una señal de cumplimiento o desviación.",
                coverage=_coverage(0, len(dashboard["goals"]), minimum=1),
                provenance=("Dashboard · objetivos",),
                evidence=(_evidence("Metas configuradas", len(dashboard["goals"]), "Dashboard · objetivos", period),)))

        return {"today": cls._brief(daily_period, daily, generated_at),
                "week": cls._brief(period, weekly, generated_at)}

    @classmethod
    def _brief(cls, period, signals, generated_at) -> CoachBrief:
        ranked = cls._rank(signals)
        if not ranked:
            ranked = [cls._signal(period=period, domain="data", kind="insufficient_data",
                metric="coverage", title="Aún no hay cambios comparables",
                message="Registra información para construir un resumen con evidencia.",
                coverage=_coverage(0, period["days"], minimum=1),
                provenance=("Health Tracker",),
                evidence=(_evidence("Registros comparables", 0, "Health Tracker", period),))]
        priorities = []
        domain_counts = {}
        for item in ranked:
            if domain_counts.get(item["domain"], 0) >= 2:
                continue
            priorities.append(item)
            domain_counts[item["domain"]] = domain_counts.get(item["domain"], 0) + 1
            if len(priorities) == 5:
                break
        if len(priorities) < 5:
            priorities.extend(item for item in ranked if item not in priorities)
            priorities = priorities[:5]
        return {"period": period, "generated_at": generated_at.isoformat(),
                "signals": ranked, "top_priorities": priorities,
                "coverage": {item["domain"]: item["coverage"] for item in priorities},
                "domains": list(dict.fromkeys(item["domain"] for item in priorities)),
                "possible_actions": [item["action"] for item in priorities if item["action"]]}


class CoachBriefService:
    """One dashboard load plus one Gym read; never queries for each signal."""

    def build(self, user, *, today: date | None = None, dashboard_snapshot: dict | None = None) -> dict[str, CoachBrief]:
        started = clock.perf_counter()
        timezone_name = user.timezone or current_app.config["APP_TIMEZONE"]
        try:
            zone = ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            timezone_name = current_app.config["APP_TIMEZONE"]
            zone = ZoneInfo(timezone_name)
        local_today = today or current_app.config.get("AI_TODAY_OVERRIDE") or datetime.now(zone).date()
        if isinstance(local_today, str):
            local_today = date.fromisoformat(local_today)
        date_range = DashboardDateRange.from_query({"preset": "7d"}, timezone_name, today=local_today)
        if (dashboard_snapshot and dashboard_snapshot.get("range", {}).get("preset") == "7d"
                and dashboard_snapshot["range"].get("to") == date_range.end_date.isoformat()
                and dashboard_snapshot["range"].get("timezone") == timezone_name):
            dashboard = dashboard_snapshot
        else:
            dashboard = DashboardSummaryService().build(user.id, date_range, user.preferred_load_unit)
        cutoff = datetime.combine(local_today, time.max, zone).astimezone(timezone.utc)
        reader = StrengthReader(user.id, now=cutoff)
        gym = reader.overview()
        gym["coach_volume"] = reader.comparable_range(
            date_range.start_date, date_range.end_date,
            date_range.previous_start, date_range.previous_end)
        briefs = CoachSignalEngine.build(dashboard, gym)
        for name, brief in briefs.items():
            priorities = brief["top_priorities"]
            current_app.logger.info(
                "coach_brief period=%s signal_ids=%s domains=%s coverage=%s duration_ms=%d",
                name,
                ",".join(item["signal_id"] for item in priorities),
                ",".join(brief["domains"]),
                ",".join((item["coverage"] or {}).get("state", "unknown") for item in priorities),
                round((clock.perf_counter() - started) * 1000),
            )
        return briefs
