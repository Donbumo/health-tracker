"""Shared helpers for read-only standard JSON generators."""

from __future__ import annotations

from copy import deepcopy
from datetime import time
from decimal import Decimal, InvalidOperation
import re
from typing import Any


def records_at_path(payload: dict[str, Any], path: str) -> list[dict[str, Any]]:
    node = value_at_path(payload, path)

    if isinstance(node, list):
        return [
            deepcopy(item)
            for item in node
            if isinstance(item, dict)
        ]

    if isinstance(node, dict):
        return [deepcopy(node)]

    return []


def value_at_path(payload: dict[str, Any], path: str) -> Any:
    if path in {"", "$"}:
        return payload

    current: Any = payload
    for token in path_tokens(path):
        if isinstance(token, str):
            if not isinstance(current, dict):
                return None
            current = current.get(token)
        else:
            if not isinstance(current, list):
                return None
            if token < 0 or token >= len(current):
                return None
            current = current[token]

    return current


def path_tokens(path: str) -> list[str | int]:
    tokens: list[str | int] = []

    for part in path.split("."):
        if not part:
            continue

        match = re.fullmatch(r"([^\[]+)(?:\[(\d+)\])?", part)
        if not match:
            tokens.append(part)
            continue

        key, index = match.groups()
        tokens.append(key)
        if index is not None:
            tokens.append(int(index))

    return tokens


def coerce_number(value: Any) -> int | float | None:
    if value is None:
        return None

    if isinstance(value, bool):
        return None

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        return value

    try:
        decimal_value = Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, AttributeError):
        return None

    if decimal_value == decimal_value.to_integral_value():
        return int(decimal_value)

    return float(decimal_value)


def coerce_datetime(
    date_value: Any,
    time_value: Any = None,
    *,
    default_timezone: str,
) -> Any:
    if date_value is None:
        return None

    text = str(date_value).strip()
    if not text:
        return None

    if "T" in text:
        if has_timezone(text):
            return text
        return f"{text}{default_timezone}"

    time_text = coerce_time_text(time_value) or "00:00:00"
    return f"{text}T{time_text}{default_timezone}"


def coerce_time_text(value: Any) -> str | None:
    if value is None:
        return None

    if isinstance(value, time):
        return value.strftime("%H:%M:%S")

    text = str(value).strip()
    if not text:
        return None

    if re.fullmatch(r"\d{2}:\d{2}", text):
        return f"{text}:00"

    if re.fullmatch(r"\d{2}:\d{2}:\d{2}", text):
        return text

    return None


def has_timezone(value: str) -> bool:
    if value.endswith("Z"):
        return True
    return bool(re.search(r"[+-]\d{2}:\d{2}$", value))


def drop_none(document: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in document.items()
        if value is not None
    }
