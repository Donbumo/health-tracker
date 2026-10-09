"""Small, closed grammar over domain-owned metadata; never calls tools or writes.

High confidence means exactly one interpretation of *every* clause/token, not a
numeric score. Unsupported modifiers, questions, conflicting values and units
decline the whole turn. The registry remains the authority for validation.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

from app.services.ai.capabilities.types import ActionLanguage, ActionNumericSlot, CapabilityError
from app.services.ai.types import AIProviderPlanProposal, AIProviderPlanStepProposal


def normalized(text: str) -> str:
    return " ".join("".join(
        char for char in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(char)
    ).split())


def alternatives(values) -> str:
    return "(?:" + "|".join(re.escape(value) for value in sorted(
        {normalized(value) for value in values}, key=len, reverse=True
    )) + ")"


def put(arguments: dict, path: str, value) -> None:
    """Build nested schema arguments, including a single explicitly named meal."""
    parts = path.split(".")
    cursor = arguments
    for index, part in enumerate(parts[:-1]):
        if isinstance(cursor, list):
            while len(cursor) <= int(part):
                cursor.append({})
            cursor = cursor[int(part)]
        else:
            cursor = cursor.setdefault(part, [] if parts[index + 1].isdigit() else {})
    cursor[parts[-1]] = value


@dataclass(frozen=True)
class DeterministicActionMatch:
    proposal: AIProviderPlanProposal | None = None
    confidence: str = "none"
    ambiguity: str = "unrecognized"

    @property
    def high_confidence(self) -> bool:
        return self.confidence == "high" and self.ambiguity == "none"


class DeterministicActionInterpreter:
    def __init__(self, registry):
        self.registry = registry
        self.patterns = tuple(
            (action, language)
            for action in registry.action_capabilities
            for language in action.language
        )

    def interpret(self, text: str, *, allowed_action_ids=None) -> DeterministicActionMatch:
        if "\n" in text or "\r" in text:
            return DeterministicActionMatch()
        text = normalized(text).removesuffix(".")
        # Only sentence-final periods are punctuation in this grammar. This also
        # rejects questions, quotes, instructions in notes, and multiple sentences.
        if not text or re.search(r"[!?¿¡;\"'<>]", text):
            return DeterministicActionMatch()
        verbs = alternatives(verb for _, language in self.patterns for verb in language.verbs)
        clauses = re.split(rf"\s+y\s+(?={verbs}\b)", text)
        if not 1 <= len(clauses) <= 10:
            return DeterministicActionMatch()
        steps = []
        operations = set()
        identities = []
        for clause in clauses:
            matches = []
            for action, language in self.patterns:
                if allowed_action_ids is not None and action.action_id not in allowed_action_ids:
                    continue
                arguments = self._clause(clause, language)
                if arguments is not None:
                    candidate = (action, arguments, language)
                    if candidate not in matches:
                        matches.append(candidate)
            if len(matches) != 1:
                return DeterministicActionMatch(ambiguity="multiple" if matches else "unrecognized")
            action, arguments, language = matches[0]
            identity = (action.action_id, language.bindings)
            if identity in identities:
                return DeterministicActionMatch(ambiguity="duplicate_target")
            identities.append(identity)
            operations.add(action.operation)
            steps.append(AIProviderPlanStepProposal(
                step_id=f"step_{len(steps) + 1}", action_capability_id=action.action_id,
                arguments=arguments,
            ))
        intent = "record" if operations == {"create"} else "correct" if "create" not in operations else "hybrid"
        return DeterministicActionMatch(
            AIProviderPlanProposal(intent, "Cambios solicitados para revisión", tuple(steps)),
            "high", "none",
        )

    def _clause(self, text: str, language: ActionLanguage) -> dict | None:
        entities = alternatives(language.entities)
        verbs = alternatives(language.verbs)
        entity = rf"(?:mi |el |la |un |una )?{entities}\b"
        patterns = [rf"(?:hoy )?{verbs}\s+{entity}(?P<tail>.*)"]
        if language.statement_verbs:
            patterns.append(rf"(?:hoy )?{entity}\s+(?:hoy )?{alternatives(language.statement_verbs)}\b(?P<tail>.*)")
        if language.implicit_entity_verbs:
            patterns.append(rf"(?:hoy )?{alternatives(language.implicit_entity_verbs)}\b(?P<tail>.*)")
        matched = next((m for pattern in patterns if (m := re.fullmatch(pattern, text))), None)
        if matched is None:
            return None
        tail = matched.group("tail").strip()
        tail = re.sub(r"^(?:en|a|de|con)\s+", "", tail)
        arguments = {}
        for path, value in language.bindings:
            put(arguments, path, value)
        if not tail:
            # Statements without a value are not explicit commands to record it.
            return arguments if re.match(rf"(?:hoy )?{verbs}\b", text) else None
        seen = set()
        for fragment in re.split(r"\s+y\s+|,\s+", tail):
            candidates = []
            for slot in language.slots:
                value = self._number(fragment, slot)
                if value is not None:
                    candidates.append((slot, value))
            if len(candidates) != 1:
                return None
            slot, (number, unit) = candidates[0]
            if slot.path in seen:
                return None
            seen.add(slot.path)
            # JSON numeric values are accepted by domain schemas, including future
            # integer fields. No numeric extraction is ever included in logs.
            put(arguments, slot.path, float(number) if "." in number else int(number))
            if slot.unit_field and unit is not None:
                put(arguments, slot.unit_field, unit)
        return arguments

    @staticmethod
    def _number(fragment: str, slot: ActionNumericSlot):
        number = r"(?P<number>\d+(?:[.,]\d+)?)"
        aliases = alternatives(slot.aliases)
        units = alternatives(alias for alias, _ in slot.units)
        unit = rf"\s*(?P<unit>{units})" if slot.units else ""
        patterns = []
        if slot.aliases:
            patterns.extend((
                rf"{aliases}\s*(?:(?:en|a|de|es|fue)\s+)?{number}(?:{unit})?",
                rf"{number}(?:{unit})?\s*(?:de\s+)?{aliases}",
            ))
        if slot.primary:
            patterns.append(rf"{number}(?:{unit})?")
        for pattern in patterns:
            match = re.fullmatch(pattern, fragment.strip())
            if match:
                unit_name = match.groupdict().get("unit")
                canonical = dict((normalized(a), b) for a, b in slot.units).get(unit_name, slot.default_unit)
                return match.group("number").replace(",", "."), canonical
        return None

    def slot_updates(self, rows, text: str) -> dict[str, dict]:
        """Use the same slot metadata; each fragment must map to one pending step.

        Never partially consume an ambiguous reply. Finished steps and existing
        fields cannot be edited through an unlabelled slot continuation.
        """
        fragments = re.split(r"\s+y\s+|,\s+", normalized(text).removesuffix("."))
        updates = {}
        for fragment in fragments:
            candidates = []
            for row in rows:
                provenance = row.provenance_json or {}
                if row.status != "pending_confirmation" or provenance.get("step_status") != "needs_input":
                    continue
                action = self.registry.action(provenance.get("action_capability_id"))
                for language in action.language:
                    if any((row.payload_json or {}).get(path) != value
                           for path, value in language.bindings if "." not in path):
                        continue
                    for slot in language.slots:
                        if "." in slot.path or (row.payload_json or {}).get(slot.path) not in (None, ""):
                            continue
                        if slot.path in updates.get(provenance["step_id"], {}):
                            continue
                        # Bare values are safe only if there is one missing slot;
                        # explicit units disambiguate across steps/domains.
                        value = self._number(fragment, slot)
                        if value is not None:
                            key = (provenance["step_id"], slot.path, value)
                            if key not in [candidate[0] for candidate in candidates]:
                                candidates.append((key, slot))
            if len(candidates) != 1:
                if not candidates and rows and re.fullmatch(r"\d+(?:[.,]\d+)?\s*[a-z%]+", fragment):
                    raise CapabilityError("invalid_action_unit", "La unidad no corresponde a los campos pendientes.", 422)
                return {}
            (step_id, path, (number, unit)), slot = candidates[0]
            arguments = updates.setdefault(step_id, {})
            if path in arguments:
                return {}
            arguments[path] = float(number) if "." in number else int(number)
            if slot.unit_field and unit is not None:
                arguments[slot.unit_field] = unit
        return updates
