"""Batched, owner-scoped read models for Gym. Templates receive derived values."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from typing import TypedDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import current_app

from sqlalchemy.orm import selectinload, with_loader_criteria
from sqlalchemy.orm.attributes import set_committed_value

from app.extensions import db
from app.models import (Exercise, ExerciseAlias, ExerciseLoadProfile, TrainingPlan,
                        TrainingPlanVersion, TrainingSession, TrainingSessionExercise, TrainingSet, User)
from app.services.exercise_identity import normalize_exercise_name
from app.services.gym_programs import GymError
from app.services.gym_progression import (GymProgressionEngine, STATE_LABELS, e1rm,
                                         target_signature, prescription_target)
from app.services.gym_sessions import utc
from app.services.mobile_progress import _decimal, _text, _set_volume, _session_volume, WEIGHT_VOLUME_MODES
from app.services.workout_loads import from_kg


class GymStrengthOverview(TypedDict):
    weekly: dict
    consistency: list[dict]
    consistency_total: int
    evaluations: list[dict]
    strength: dict | None


class ExerciseStrengthDetail(TypedDict):
    identity: dict
    evaluation: dict | None
    contexts: list[dict]
    points: list[dict]
    chart: dict
    top_set: dict | None
    history: list[dict]


class WorkoutCompletionSummary(TypedDict):
    session_id: str
    today: dict
    previous: dict | None
    changes: list[dict]
    candidates: list[dict]


def _metrics(records, unit):
    volumes = [_session_volume(r) for r in records]
    available = [v for v, _ in volumes if v is not None]
    volume = sum(available, Decimal(0)) if available else None
    durations = [r.duration_seconds for r in records]
    return {"sessions": len(records), "sets": sum(len(e.sets) for r in records for e in r.exercises),
            "volume": _text(from_kg(volume, unit)) if volume is not None else None,
            "partial": any(p for _, p in volumes), "unit": unit,
            "duration_minutes": _text(Decimal(sum(durations)) / 60) if durations and all(d is not None for d in durations) else None}


class StrengthReader:
    """One request-sized snapshot. Query counts grow only in selectin batches, not cards.

    Historical sessions are read once, without arbitrary truncation. No public caching.
    Explicit ownership criteria also guard children of corrupted cross-owner relations.
    """
    def __init__(self, user_id, *, now=None, lock=False):
        self.user_id = user_id
        self.now = utc(now or datetime.now(timezone.utc))
        self.user = db.session.get(User, user_id)
        if self.user is None:
            raise GymError("Usuario no encontrado.", 404)
        try:
            self.zone = ZoneInfo(self.user.timezone or current_app.config["APP_TIMEZONE"])
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            self.zone = ZoneInfo(current_app.config["APP_TIMEZONE"])
        self.unit = self.user.preferred_load_unit or "kg"
        self.identities = db.session.execute(db.select(Exercise).where(Exercise.user_id == user_id).options(
            selectinload(Exercise.aliases), selectinload(Exercise.load_profile), selectinload(Exercise.external_catalog),
            with_loader_criteria(ExerciseAlias, ExerciseAlias.user_id == user_id),
            with_loader_criteria(ExerciseLoadProfile, ExerciseLoadProfile.user_id == user_id),
        )).scalars().all()
        self.by_id = {e.public_id: e for e in self.identities}
        self.by_name = {}
        for e in self.identities:
            for name in [e.normalized_name, *(a.normalized_name for a in e.aliases)]:
                if name in self.by_name and self.by_name[name] != e:
                    self.by_name[name] = None
                else:
                    self.by_name[name] = e
        self.plans = db.session.execute(db.select(TrainingPlan).where(
            TrainingPlan.user_id == user_id, TrainingPlan.deleted_at.is_(None)).options(
            selectinload(TrainingPlan.versions), with_loader_criteria(TrainingPlanVersion, TrainingPlanVersion.user_id == user_id)
        )).scalars().all()
        self.versions = {v.id: v for p in self.plans for v in p.versions if v.user_id == user_id}
        self.records = db.session.execute(db.select(TrainingSession).where(
            TrainingSession.user_id == user_id, TrainingSession.deleted_at.is_(None),
            TrainingSession.status == "completed", TrainingSession.performed_at <= self.now,
            TrainingSession.training_plan_id.in_([p.id for p in self.plans]),
        ).options(selectinload(TrainingSession.exercises).selectinload(TrainingSessionExercise.sets),
                  with_loader_criteria(TrainingSessionExercise, TrainingSessionExercise.user_id == user_id),
                  with_loader_criteria(TrainingSet, TrainingSet.user_id == user_id))
            .order_by(TrainingSession.performed_at, TrainingSession.id)
            .execution_options(populate_existing=True)).scalars().all()
        if lock:
            self._current_locked_snapshot()
            self.by_id = {e.public_id: e for e in self.identities}
            self.by_name = {}
            for e in self.identities:
                for name in [e.normalized_name, *(a.normalized_name for a in e.aliases)]:
                    self.by_name[name] = e if name not in self.by_name or self.by_name[name] == e else None
        self.contexts = []
        for plan in self.plans:
            version = next((v for v in plan.versions if v.version_number == plan.active_version_number and v.user_id == user_id), None)
            if version is None:
                continue
            for w in version.content["data"]["weeks"]:
                for d in w["days"]:
                    for e in d["exercises"]:
                        identity = self.identity(e)
                        self.contexts.append({"plan": plan, "version": version, "week": w["week_number"],
                                              "day": d["day_number"], "day_name": d["name"],
                                              "prescription": e, "identity": identity,
                                              "id": f'{w["week_number"]}:{d["day_number"]}:{e["exercise_order"]}'})
        self.occurrences = defaultdict(list)
        self.by_prescription = defaultdict(list)
        self.session_rows = defaultdict(list)
        self._evaluations = {}
        for record in self.records:
            version = self.versions.get(record.training_plan_version_id)
            historical_day = next((d for w in (version.content["data"]["weeks"] if version else [])
                                   if w["week_number"] == record.planned_week_number
                                   for d in w["days"] if d["day_number"] == record.planned_day_number), None)
            for occurrence in record.exercises:
                target = next((e for e in (historical_day["exercises"] if historical_day else [])
                               if e["exercise_order"] == occurrence.planned_exercise_order), None)
                # Historical explicit identity is valid only for that actual prescription/name.
                identity = self.identity(target) if target and normalize_exercise_name(target["name"]) == normalize_exercise_name(occurrence.name) else self.identity({"name": occurrence.name})
                sets = [{"number": s.planned_set_number or s.set_number, "recorded_number": s.set_number,
                         "load_kg": _text(_decimal(s.weight_kg)), "reps": s.reps,
                         "rir": _text(_decimal(s.rir)), "rpe": _text(_decimal(s.rpe)),
                         "mode": (s.load_details_json or {}).get("load_mode", "direct_total"),
                         "unit": (s.load_details_json or {}).get("original_unit", "kg"),
                         "volume_kg": _text(_set_volume(s))} for s in sorted(occurrence.sets, key=lambda s: s.set_number)]
                row = {"session_id": record.public_id, "revision": record.revision,
                       "version_id": version.public_id if version else None,
                       "date": utc(record.performed_at).astimezone(self.zone).strftime("%d/%m/%Y"),
                       "performed_at": utc(record.performed_at).isoformat(),
                       "exercise_order": occurrence.exercise_order, "name": occurrence.name,
                       "identity": identity.public_id if identity else None,
                       "signature": target_signature(target or {}), "sets": sets}
                self.session_rows[record.public_id].append(row)
                if identity:
                    self.occurrences[identity.public_id].append(row)
                key = (record.training_plan_id, record.planned_week_number, record.planned_day_number,
                       occurrence.planned_exercise_order, identity.public_id if identity else None)
                self.by_prescription[key].append(row)
            # An omitted exercise in a partially completed day breaks consecutive
            # evidence too; never silently skip it and join two older successes.
            recorded_orders = {e.planned_exercise_order for e in record.exercises}
            for target in (historical_day["exercises"] if historical_day else []):
                if target["exercise_order"] in recorded_orders:
                    continue
                identity = self.identity(target)
                key = (record.training_plan_id, record.planned_week_number, record.planned_day_number,
                       target["exercise_order"], identity.public_id if identity else None)
                self.by_prescription[key].append({"session_id": record.public_id, "revision": record.revision,
                    "date": utc(record.performed_at).astimezone(self.zone).strftime("%d/%m/%Y"),
                    "signature": target_signature(target), "sets": []})

    def _current_locked_snapshot(self):
        """Refresh every private source with locking reads, including loader children."""
        def rows(model):
            return db.session.execute(db.select(model).where(model.user_id == self.user_id)
                .order_by(model.id).with_for_update().execution_options(populate_existing=True)).scalars().all()
        self.identities = rows(Exercise)
        aliases, profiles = rows(ExerciseAlias), rows(ExerciseLoadProfile)
        for e in self.identities:
            set_committed_value(e, "aliases", [a for a in aliases if a.exercise_id == e.id])
            set_committed_value(e, "load_profile", next((p for p in profiles if p.exercise_id == e.id), None))
        self.plans = [p for p in rows(TrainingPlan) if p.deleted_at is None]
        versions = rows(TrainingPlanVersion)
        for p in self.plans:
            set_committed_value(p, "versions", [v for v in versions if v.training_plan_id == p.id])
        self.versions = {v.id: v for p in self.plans for v in p.versions}
        sessions, exercises, sets = rows(TrainingSession), rows(TrainingSessionExercise), rows(TrainingSet)
        sets_by_exercise, exercises_by_session = defaultdict(list), defaultdict(list)
        for s in sets:
            sets_by_exercise[s.training_session_exercise_id].append(s)
        for e in exercises:
            set_committed_value(e, "sets", sets_by_exercise[e.id])
            exercises_by_session[e.training_session_id].append(e)
        for r in sessions:
            set_committed_value(r, "exercises", exercises_by_session[r.id])
        plan_ids = {p.id for p in self.plans}
        self.records = sorted([r for r in sessions if r.deleted_at is None and r.status == "completed"
                               and r.training_plan_id in plan_ids and utc(r.performed_at) <= self.now],
                              key=lambda r: (utc(r.performed_at), r.id))

    def identity(self, prescription):
        explicit = prescription.get("exercise_id")
        if explicit:
            return self.by_id.get(explicit)
        return self.by_name.get(normalize_exercise_name(prescription.get("name", "")))

    def evaluate(self, context):
        key = (context["plan"].public_id, context["id"])
        if key in self._evaluations:
            return self._evaluations[key]
        identity = context["identity"]
        profile = identity.load_profile if identity else None
        equipment = identity.external_catalog.details.get("equipment") if identity and identity.external_catalog else None
        rows = self.by_prescription[(context["plan"].id, context["week"], context["day"],
                                    context["prescription"]["exercise_order"], identity.public_id if identity else None)]
        evaluation = GymProgressionEngine.evaluate(
            prescription=context["prescription"], identity=identity.public_id if identity else None,
            program_id=context["plan"].public_id, program_revision=context["plan"].revision,
            revision_id=context["version"].public_id, prescription_id=context["id"], sessions=rows,
            profile={"mode": profile.load_mode, "unit": profile.preferred_unit,
                     "increments": profile.quick_increments_json, "revision": profile.revision} if profile else None,
            equipment=equipment, now=self.now)
        evaluation.update(name=context["prescription"]["name"], label=STATE_LABELS[evaluation["state"]],
                          day_name=context["day_name"], program_name=context["plan"].name)
        self._evaluations[key] = evaluation
        return evaluation

    def context(self, program_id, prescription_id):
        context = next((c for c in self.contexts if c["plan"].public_id == program_id and c["id"] == prescription_id), None)
        if context is None:
            raise GymError("Prescripción no encontrada.", 404)
        return context

    def coverage(self, record):
        rows = self.session_rows[record.public_id]
        if not rows or any(not r["identity"] or not r["sets"] for r in rows):
            return None
        if any(s["volume_kg"] is None for r in rows for s in r["sets"]):
            return None
        return frozenset((r["identity"], s["mode"]) for r in rows for s in r["sets"])

    def overview(self):
        local = self.now.astimezone(self.zone)
        monday = local.date() - timedelta(days=local.weekday())
        weeks = []
        buckets = []
        for n in range(3, -1, -1):
            start = datetime.combine(monday - timedelta(weeks=n), time.min, self.zone)
            end = start + timedelta(weeks=1)
            rows = [r for r in self.records if start <= utc(r.performed_at).astimezone(self.zone) < end]
            buckets.append(rows)
            weeks.append({"label": start.strftime("%d/%m"), "count": len(rows)})
        weekly = _metrics(buckets[-1], self.unit)
        previous = _metrics(buckets[-2], self.unit)
        def coverage(records):
            values = [self.coverage(r) for r in records]
            return frozenset().union(*values) if values and all(v is not None for v in values) else None
        change = None
        if (weekly["volume"] is not None and previous["volume"] is not None
                and _decimal(previous["volume"]) > 0 and not weekly["partial"] and not previous["partial"]
                and coverage(buckets[-1]) is not None and coverage(buckets[-1]) == coverage(buckets[-2])):
            change = _text((_decimal(weekly["volume"]) / _decimal(previous["volume"]) - 1) * 100)
        weekly.update(comparison=change,
                      start=monday.strftime("%d/%m"), end=(monday + timedelta(days=6)).strftime("%d/%m"))
        maximum = max([w["count"] for w in weeks] + [1])
        for w in weeks:
            w["height"] = round(w["count"] / maximum * 100)
        evaluations = [self.evaluate(c) for c in self.contexts if c["plan"].gym_active]
        order = {"increase_load": 0, "increase_reps": 1, "review": 2, "maintain": 3, "insufficient_data": 4}
        evaluations.sort(key=lambda e: order[e["state"]])
        strength = None
        for evaluation in evaluations:
            if not evaluation["exercise_id"]:
                continue
            points = self.points(evaluation["exercise_id"], 56)
            eligible = [p for p in points if p["estimate"] is not None]
            if len(eligible) >= 2 and eligible[-1]["mode"] == eligible[-2]["mode"]:
                strength = {"name": evaluation["name"], "exercise_id": evaluation["exercise_id"],
                            "estimate": eligible[-1]["estimate"], "unit": self.unit, "top": eligible[-1]["top"]}
                break
        return GymStrengthOverview(weekly=weekly, consistency=weeks, consistency_total=sum(w["count"] for w in weeks),
                                   evaluations=evaluations[:4], strength=strength)

    def comparable_range(self, start_date, end_date, previous_start, previous_end):
        """Volume for the exact Dashboard windows, using the loaded owner-only snapshot."""
        def rows_between(start, end):
            return [row for row in self.records
                    if start <= utc(row.performed_at).astimezone(self.zone).date() <= end]

        current_rows = rows_between(start_date, end_date)
        previous_rows = rows_between(previous_start, previous_end)
        current = _metrics(current_rows, self.unit)
        previous = _metrics(previous_rows, self.unit)

        def identities(rows):
            values = [self.coverage(row) for row in rows]
            return frozenset().union(*values) if values and all(value is not None for value in values) else None

        comparison = None
        if (current["volume"] is not None and previous["volume"] is not None
                and _decimal(previous["volume"]) > 0 and not current["partial"] and not previous["partial"]
                and identities(current_rows) is not None
                and identities(current_rows) == identities(previous_rows)):
            comparison = _text((_decimal(current["volume"]) / _decimal(previous["volume"]) - 1) * 100)
        return {**current, "previous_volume": previous["volume"], "comparison": comparison}

    def points(self, exercise_id, days):
        # One point per session even when the same identity occurs twice in that day.
        grouped = {}
        for row in self.occurrences[exercise_id]:
            if utc(datetime.fromisoformat(row["performed_at"])) < self.now - timedelta(days=days):
                continue
            group = grouped.setdefault(row["session_id"], {"session_id": row["session_id"], "date": row["date"],
                                                         "performed_at": row["performed_at"], "sets": []})
            group["sets"].extend(s | {"exercise_order": row["exercise_order"]} for s in row["sets"])
        points = []
        for row in grouped.values():
            modes = {s["mode"] for s in row["sets"]}
            mode = next(iter(modes)) if len(modes) == 1 else None
            valid = [s for s in row["sets"] if s["volume_kg"] is not None] if mode in WEIGHT_VOLUME_MODES else []
            top = max(valid, key=lambda s: (_decimal(s["load_kg"]), s["reps"])) if valid else None
            estimates = [v for s in valid if (v := e1rm(s["load_kg"], s["reps"], mode, self.unit)) is not None]
            volumes = [_decimal(s["volume_kg"]) for s in valid]
            points.append(row | {"mode": mode, "load": _text(from_kg(_decimal(top["load_kg"]), self.unit)) if top else None,
                                 "estimate": _text(max(estimates)) if estimates else None, "unit": self.unit,
                                 "volume": _text(from_kg(sum(volumes), self.unit)) if volumes else None,
                                 "partial": len(valid) != len(row["sets"]),
                                 "top": top | {"load": _text(from_kg(_decimal(top["load_kg"]), self.unit)),
                                               "session_id": row["session_id"], "date": row["date"]} if top else None})
        return points

    def detail(self, exercise_id, period="8", *, program_id=None, prescription_id=None):
        if exercise_id not in self.by_id:
            raise GymError("Ejercicio no encontrado. Vincula primero su identidad.", 404)
        if period not in {"8", "3", "6"}:
            raise GymError("Periodo no válido.")
        identity = self.by_id[exercise_id]
        contexts = [c for c in self.contexts if c["identity"] == identity]
        contexts.sort(key=lambda c: not c["plan"].gym_active)
        selected = next((c for c in contexts if c["plan"].public_id == program_id and c["id"] == prescription_id), None) if program_id else (contexts[0] if contexts else None)
        if program_id and selected is None:
            raise GymError("Prescripción no encontrada.", 404)
        points = self.points(exercise_id, {"8": 56, "3": 92, "6": 183}[period])
        reference = identity.external_catalog
        return ExerciseStrengthDetail(
            identity={"exercise_id": identity.public_id, "name": identity.canonical_name,
                      "equipment": reference.details.get("equipment") if reference else None,
                      "muscles": reference.details.get("primary_muscles", []) if reference else []},
            evaluation=self.evaluate(selected) if selected else None,
            contexts=[{"program_id": c["plan"].public_id, "prescription_id": c["id"],
                       "label": f'{c["plan"].name} · {c["day_name"]} · {c["prescription"]["name"]}'} for c in contexts],
            points=points, chart=chart_projection(points),
            top_set=points[-1]["top"] if points else None,
            history=list(reversed(points))[:10], period=period, unit=self.unit,
            estimate=points[-1]["estimate"] if points else None)

    def summary(self, public_id):
        record = next((r for r in self.records if r.public_id == public_id), None)
        if record is None:
            raise GymError("Sesión completada no encontrada.", 404)
        before = [r for r in self.records if (utc(r.performed_at), r.id) < (utc(record.performed_at), record.id)]
        same_day = [r for r in before if (r.training_plan_id, r.planned_week_number, r.planned_day_number)
                    == (record.training_plan_id, record.planned_week_number, record.planned_day_number)]
        previous = same_day[-1] if same_day else None
        comparable = previous and self.coverage(record) is not None and self.coverage(record) == self.coverage(previous)
        changes = []
        for row in self.session_rows[public_id]:
            candidates = [p for r in reversed(same_day) for p in self.session_rows[r.public_id] if row["identity"] and p["identity"] == row["identity"]]
            old = candidates[0] if candidates else None
            change = "Sin sesión anterior comparable"
            if old and row["sets"] and len(row["sets"]) == len(old["sets"]):
                pairs = list(zip(row["sets"], old["sets"]))
                if all(a["volume_kg"] is not None and b["volume_kg"] is not None and a["mode"] == b["mode"] and a["number"] == b["number"] for a, b in pairs):
                    loads = [from_kg(_decimal(a["load_kg"]) - _decimal(b["load_kg"]), self.unit) for a, b in pairs]
                    reps = sum(a["reps"] - b["reps"] for a, b in pairs)
                    if all(v == 0 for v in loads):
                        change = f'{reps:+d} reps totales · misma carga' if reps else "Sin cambios"
                    elif len(set(loads)) == 1:
                        change = f'{loads[0]:+.2f} {self.unit} por serie · {reps:+d} reps totales'
                    else:
                        change = "Cargas distintas por serie; revisa el historial"
            changes.append({"name": row["name"], "exercise_id": row["identity"], "change": change,
                            "sets": len(row["sets"]), "reps": " / ".join(str(s["reps"]) for s in row["sets"])})
        context = [c for c in self.contexts if c["plan"].id == record.training_plan_id and c["week"] == record.planned_week_number and c["day"] == record.planned_day_number]
        evaluations = [self.evaluate(c) for c in context]
        candidates = [e for e in evaluations if e["state"] in {"increase_load", "increase_reps", "review"}]
        plan = next(p for p in self.plans if p.id == record.training_plan_id)
        version = self.versions.get(record.training_plan_version_id)
        day = next((d for w in (version.content["data"]["weeks"] if version else []) if w["week_number"] == record.planned_week_number for d in w["days"] if d["day_number"] == record.planned_day_number), None)
        return WorkoutCompletionSummary(session_id=public_id, today=_metrics([record], self.unit),
            previous=_metrics([previous], self.unit) if comparable else None,
            previous_date=utc(previous.performed_at).astimezone(self.zone).strftime("%d/%m") if comparable else None,
            changes=changes, candidates=candidates, plan_name=plan.name, day_name=day["name"] if day else "Sesión",
            date=utc(record.performed_at).astimezone(self.zone).strftime("%d/%m/%Y"),
            removed=sorted({r["name"] for r in self.session_rows[previous.public_id] if r["identity"] not in {c["exercise_id"] for c in changes}}) if previous else [])


def chart_projection(points):
    valid = [p for p in points if p["load"] is not None]
    if not valid:
        return {"segments": [], "dots": [], "ticks": []}
    values = [_decimal(p["load"]) for p in valid]
    low, high = min(values) - 5, max(values) + 5
    start = datetime.fromisoformat(points[0]["performed_at"])
    span = max(1, (datetime.fromisoformat(points[-1]["performed_at"]) - start).total_seconds())
    segments, dots, line, last_mode = [], [], [], None
    for p in points:
        if p["load"] is None or p["mode"] != last_mode:
            if line:
                segments.append(" ".join(line))
            line = []
        last_mode = p["mode"]
        if p["load"] is None:
            continue
        x = round(55 + 510 * (datetime.fromisoformat(p["performed_at"]) - start).total_seconds() / span, 2)
        y = round(190 - float((_decimal(p["load"]) - low) / (high - low)) * 155, 2)
        line.append(f"{x},{y}")
        dots.append({"x": x, "y": y, "label": f'{p["date"]} · {p["load"]} {p["unit"]} · {p["mode"]}'})
    if line:
        segments.append(" ".join(line))
    return {"segments": segments, "dots": dots,
            "ticks": [{"y": y, "value": _text(v)} for y, v in [(190, low), (112.5, (low + high) / 2), (35, high)]]}
