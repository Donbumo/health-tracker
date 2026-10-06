"""Pure, versioned strength calculations. No ORM, Flask, provider or writes."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from typing import TypedDict

from app.services.mobile_progress import WEIGHT_VOLUME_MODES, _decimal, _text
from app.services.workout_loads import from_kg, MAX_WEIGHT

E1RM_EPLEY_V1 = "E1RM_EPLEY_V1"
RULE_ID = "double_progression"
RULE_VERSION = "double_progression_v1"
STATE_LABELS = {
    "increase_load": "Subir carga", "increase_reps": "Buscar más reps",
    "maintain": "Mantener", "review": "Revisar", "insufficient_data": "Sin datos suficientes",
}


class ProgressionEvaluation(TypedDict):
    exercise_id: str | None
    program_id: str
    program_revision: int
    revision_id: str
    prescription_id: str
    state: str
    current: dict
    proposal: dict | None
    evidence: list[str]
    rule_id: str
    rule_version: str
    evaluated_at: str
    source_hash: str


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, default=str, allow_nan=False).encode()).hexdigest()


def e1rm(load_kg, reps, mode, unit="kg"):
    """Epley from ONE eligible set, in the requested display unit."""
    load = _decimal(load_kg)
    if (mode not in WEIGHT_VOLUME_MODES or load is None or load <= 0
            or not isinstance(reps, int) or isinstance(reps, bool) or not 1 <= reps <= 10
            or unit not in {"kg", "lb"}):
        return None
    return from_kg(load, unit) * (Decimal(1) + Decimal(reps) / Decimal(30))


def prescription_target(prescription):
    """Only homogeneous rep prescriptions can receive this first rule."""
    targets = []
    for item in prescription.get("sets", []):
        unit = item.get("load_unit", "kg")
        mode = item.get("load_mode", "direct_total")
        load_kg = _decimal(item.get("weight_kg"))
        if load_kg is None and item.get("load_value") is not None and mode == "direct_total":
            load_kg = _decimal(item["load_value"])
            if load_kg is not None and unit == "lb":
                load_kg *= Decimal("0.45359237")
        targets.append({"load": _text(from_kg(load_kg, unit)) if load_kg is not None and unit in {"kg", "lb"} else None,
                        "load_kg": _text(load_kg), "unit": unit, "mode": mode,
                        "rep_min": item.get("reps_min", item.get("reps")),
                        "rep_max": item.get("reps_max", item.get("reps")),
                        "target_rir": _text(_decimal(item.get("rir"))),
                        "target_rpe": _text(_decimal(item.get("rpe")))})
    if not targets:
        return None, "missing"
    if any(t != targets[0] for t in targets[1:]):
        return targets[0] | {"sets": len(targets)}, "heterogeneous"
    target = targets[0] | {"sets": len(targets)}
    if not all(isinstance(target[k], int) and target[k] > 0 for k in ("rep_min", "rep_max")):
        return target, "missing"
    if target["rep_min"] > target["rep_max"] or target["unit"] not in {"kg", "lb"}:
        return target, "invalid"
    return target, None


def target_signature(prescription):
    target, error = prescription_target(prescription)
    if error:
        return None
    # Load is allowed to evolve between sessions; rep/effort/mode changes break a run.
    return {key: value for key, value in target.items() if key not in {"load", "load_kg"}}


def session_evidence(row, unit):
    sets = row["sets"]
    loads = "/".join(_text(from_kg(_decimal(s["load_kg"]), unit)) if _decimal(s["load_kg"]) is not None else "—" for s in sets)
    reps = "/".join(str(s["reps"]) for s in sets)
    rir = "/".join(str(s["rir"]) if s["rir"] is not None else "—" for s in sets)
    rpe = "/".join(str(s["rpe"]) if s["rpe"] is not None else "—" for s in sets)
    return f'{row["date"]} · {loads} {unit} · {reps} reps · RIR {rir} · RPE {rpe}'


class GymProgressionEngine:
    @staticmethod
    def evaluate(*, prescription, identity, program_id, program_revision, revision_id,
                 prescription_id, sessions, profile=None, equipment=None, now=None):
        """Sessions are chronological occurrences of this exact plan/day/prescription.

        Do not discard an incomplete/incompatible occurrence before calling: it must
        break consecutive evidence. All prescribed sets are working sets in schema 1.0.
        """
        target, problem = prescription_target(prescription)
        recent = sessions[-3:]
        result = ProgressionEvaluation(
            exercise_id=identity, program_id=program_id, program_revision=program_revision,
            revision_id=revision_id, prescription_id=prescription_id,
            state="insufficient_data", current=target or {}, proposal=None, evidence=[],
            rule_id=RULE_ID, rule_version=RULE_VERSION,
            evaluated_at=(now or datetime.now(timezone.utc)).isoformat(),
            source_hash=fingerprint({"prescription": prescription, "identity": identity,
                                     "sessions": recent, "profile": profile, "equipment": equipment}),
        )

        def finish(state, message, proposal=None):
            result.update(state=state, proposal=proposal)
            result["evidence"].append(message)
            return result

        if not identity:
            return finish("review", "Vincula una identidad antes de comparar el historial.")
        if problem:
            return finish("review" if problem in {"heterogeneous", "invalid"} else "insufficient_data",
                          "La prescripción no tiene un rango homogéneo compatible con esta regla.")
        if target["mode"] not in WEIGHT_VOLUME_MODES:
            return finish("insufficient_data", "Esta modalidad no admite progresión de carga externa en esta versión.")
        result["evidence"].append(f'Objetivo · {target["sets"]} × {target["rep_min"]}–{target["rep_max"]} · {target["load"] or "—"} {target["unit"]} · RIR {target["target_rir"] or "—"} · RPE {target["target_rpe"] or "—"}')
        for row in recent:
            result["evidence"].append(session_evidence(row, target["unit"]))
        if len(sessions) < 2:
            return finish("insufficient_data", "Se necesitan al menos dos sesiones comparables completadas.")
        pair = recent[-2:]
        if pair[0].get("session_id") and pair[0].get("session_id") == pair[1].get("session_id"):
            return finish("review", "Las evidencias deben proceder de sesiones distintas.")
        for row in pair:
            if row.get("signature") != target_signature(prescription):
                return finish("review", "La prescripción cambió; reúne evidencia con el objetivo actual.")
            if any(s["mode"] != target["mode"] or s["unit"] != target["unit"] for s in row["sets"]):
                return finish("review", "Cambió la unidad o modalidad de carga. Revisa la comparación.")
            expected = {s["set_number"] for s in prescription["sets"]}
            actual = [s["number"] for s in row["sets"]]
            if len(actual) != len(set(actual)) or not set(actual).issubset(expected):
                return finish("review", "Las series registradas contradicen la prescripción.")
            if set(actual) != expected or any(_decimal(s["load_kg"]) is None or _decimal(s["load_kg"]) < 0 or s["reps"] < 1 for s in row["sets"]):
                return finish("insufficient_data", "Faltan series de trabajo confirmadas para evaluar dos sesiones completas.")
        if any(s["rir"] is None for r in pair for s in r["sets"]):
            result["evidence"].append("RIR no disponible en alguna serie; no se infiere el esfuerzo.")
        if target["target_rpe"] is not None and any(s["rpe"] is None for r in pair for s in r["sets"]):
            result["evidence"].append("RPE no disponible en alguna serie; no se infiere el esfuerzo.")
        same_triple = len(recent) == 3 and all(
            r.get("signature") == target_signature(prescription)
            and len(r["sets"]) == target["sets"]
            and all(s["mode"] == target["mode"] and s["unit"] == target["unit"] for s in r["sets"])
            for r in recent)
        if same_triple:
            below = all(any(s["reps"] < target["rep_min"] for s in r["sets"]) for r in recent)
            totals = [sum(s["reps"] for s in r["sets"]) for r in recent]
            loads = [[s["load_kg"] for s in r["sets"]] for r in recent]
            regression = loads[0] == loads[1] == loads[2] and totals[0] > totals[1] > totals[2]
            if below or regression:
                return finish("review", "Tres sesiones muestran dificultad persistente. Revisa el objetivo; no se propone bajar carga automáticamente.")
        contradicted = any(
            (target["target_rir"] is not None and s["rir"] is not None and _decimal(s["rir"]) < _decimal(target["target_rir"]))
            or (target["target_rpe"] is not None and s["rpe"] is not None and _decimal(s["rpe"]) > _decimal(target["target_rpe"]))
            for row in pair for s in row["sets"])
        if contradicted:
            return finish("maintain", "El esfuerzo registrado supera el objetivo; conserva la carga por ahora.")
        if all(s["reps"] >= target["rep_max"] for r in pair for s in r["sets"]):
            loads = {_text(_decimal(s["load_kg"])) for r in pair for s in r["sets"]}
            if len(loads) != 1 or (target["load_kg"] is not None and loads != {target["load_kg"]}):
                return finish("maintain", "Confirma dos sesiones al tope con la misma carga prescrita antes de aumentarla.")
            observed_load = next(iter(loads))
            # Some valid plans prescribe only a rep range. The current load then
            # comes from the latest complete, comparable sets; it remains evidence,
            # never a silent prescription write.
            if target["load"] is None:
                result["current"]["load"] = _text(from_kg(_decimal(observed_load), target["unit"]))
                result["current"]["load_kg"] = observed_load
            proposal = {"load": None, "reps": None, "field_changes": [],
                        "message": "Revisar siguiente carga disponible"}
            conventional = target["mode"] == "direct_total" and equipment not in {"machine", "cable", "other"}
            current_load = _decimal(target["load"] or result["current"].get("load"))
            if conventional and current_load is not None and current_load > 0:
                increments = []
                if profile and profile["mode"] == target["mode"] and profile["unit"] == target["unit"]:
                    increments = [d for v in profile.get("increments", []) if (d := _decimal(v)) is not None and d > 0]
                increment = min(increments) if increments else Decimal("2.5" if target["unit"] == "kg" else "5")
                proposed = current_load + increment
                kg = proposed * (Decimal("0.45359237") if target["unit"] == "lb" else Decimal(1))
                if kg > MAX_WEIGHT:
                    return finish("review", "La propuesta supera el límite de carga admitido.")
                changes = [{"set_number": s["set_number"], "load_value": _text(proposed),
                            "load_unit": target["unit"], "weight_kg": _text(kg), "load_mode": "direct_total"}
                           for s in prescription["sets"]]
                proposal.update(load=_text(proposed), field_changes=changes,
                                message=f'Propuesta: {_text(proposed)} {target["unit"]}, conservando el rango.')
            return finish("increase_load", "Dos sesiones consecutivas completas alcanzaron el máximo del rango.", proposal)
        last = pair[-1]["sets"]
        if all(target["rep_min"] <= s["reps"] <= target["rep_max"] for s in last) and any(s["reps"] < target["rep_max"] for s in last):
            return finish("increase_reps", "La última sesión está dentro del rango, con repeticiones aún por completar.",
                          {"load": target["load"], "reps": target["rep_max"], "field_changes": [],
                           "message": "Mantén la carga y busca completar el máximo del rango. La prescripción no cambia."})
        return finish("maintain", "Aún no hay dos sesiones consecutivas al tope; conserva el objetivo y registra otra sesión.")


def changed_document(document, prescription_id, changes):
    """Apply allowlisted signed changes to a copy; schema validation is the publisher's job."""
    week, day, order = map(int, prescription_id.split(":"))
    result = deepcopy(document)
    prescription = next(e for w in result["data"]["weeks"] if w["week_number"] == week
                        for d in w["days"] if d["day_number"] == day
                        for e in d["exercises"] if e["exercise_order"] == order)
    indexed = {c["set_number"]: c for c in changes}
    if len(indexed) != len(prescription["sets"]):
        raise ValueError("Incomplete proposal")
    for target in prescription["sets"]:
        change = indexed[target["set_number"]]
        if set(change) != {"set_number", "load_value", "load_unit", "weight_kg", "load_mode"}:
            raise ValueError("Invalid proposal")
        target.update(change)
        # Old component snapshots must never disagree with a new direct total.
        target.pop("load_details", None)
    return result
