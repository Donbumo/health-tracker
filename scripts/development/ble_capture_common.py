"""Small, dependency-free helpers for fictional or locally exported BLE captures."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_EVENTS = 10_000
ALLOWED_TOP_LEVEL = {
    "formatVersion",
    "sourceType",
    "captureId",
    "deviceFingerprint",
    "sessionStart",
    "events",
    "expectedResult",
    "fixtureFictional",
}
ALLOWED_EVENT = {
    "serviceUuid",
    "characteristicUuid",
    "eventType",
    "relativeTimestampMs",
    "payload",
    "connectionState",
    "error",
}


def load_capture(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve(strict=True)
    if not resolved.is_file():
        raise ValueError("capture path is not a file")
    if resolved.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("capture exceeds the 2 MiB tool limit")
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("capture is not valid UTF-8 JSON") from exc
    validate_capture(value)
    return value


def validate_capture(value: Any) -> None:
    if not isinstance(value, dict):
        raise ValueError("capture root must be an object")
    if value.get("formatVersion") != "ble-capture-v1":
        raise ValueError("unsupported capture format")
    if value.get("sourceType") != "xiaomi_s400_ble_experimental":
        raise ValueError("unsupported sourceType")
    if value.get("sessionStart", 0) != 0:
        raise ValueError("absolute session timestamps are forbidden")
    events = value.get("events")
    if not isinstance(events, list) or len(events) > MAX_EVENTS:
        raise ValueError("events must be a bounded list")
    previous = -1
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("each event must be an object")
        timestamp = event.get("relativeTimestampMs")
        if not isinstance(timestamp, int) or timestamp < previous:
            raise ValueError("event timestamps must be monotonic integers")
        previous = timestamp
        payload = event.get("payload")
        if payload is not None:
            try:
                base64.b64decode(payload, validate=True)
            except (ValueError, TypeError) as exc:
                raise ValueError("event payload is not valid base64") from exc


def payload_bytes(event: dict[str, Any]) -> bytes:
    payload = event.get("payload")
    return base64.b64decode(payload, validate=True) if payload is not None else b""


def short_fingerprint(value: bytes | str) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()[:24]


def sanitized_copy(value: dict[str, Any], maximum_events: int, drops: list[tuple[int, int]]) -> dict[str, Any]:
    events = []
    for event in value["events"]:
        timestamp = event["relativeTimestampMs"]
        if any(start <= timestamp <= end for start, end in drops):
            continue
        clean = {key: event[key] for key in ALLOWED_EVENT if key in event}
        if "error" in clean:
            clean["error"] = "sanitized_error"
        events.append(clean)
        if len(events) >= maximum_events:
            break
    origin = events[0]["relativeTimestampMs"] if events else 0
    for event in events:
        event["relativeTimestampMs"] -= origin
    result = {key: value[key] for key in ALLOWED_TOP_LEVEL if key in value and key not in {"events", "captureId", "deviceFingerprint", "expectedResult"}}
    result.update(
        {
            "formatVersion": "ble-capture-v1",
            "sourceType": "xiaomi_s400_ble_experimental",
            "captureId": "fixture_candidate_" + short_fingerprint(json.dumps(events, sort_keys=True))[:12],
            "deviceFingerprint": "f1c710a1f1c710a1f1c710a1",
            "sessionStart": 0,
            "events": events,
            "fixtureFictional": True,
            "expectedResult": {"protocolState": "awaiting_evidence", "fixtureFictional": True},
        }
    )
    return result
