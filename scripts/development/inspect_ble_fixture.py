#!/usr/bin/env python3
"""Inspect BLE capture structure without printing payload content by default."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from ble_capture_common import load_capture, payload_bytes, short_fingerprint


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Inspect version, timing, UUIDs and lengths in a ble-capture-v1.")
    value.add_argument("capture", type=Path)
    value.add_argument("--show-payload", action="store_true", help="Print decoded payload hex (may expose sensitive data)")
    return value


def main() -> int:
    args = parser().parse_args()
    capture = load_capture(args.capture)
    if args.show_payload:
        print("WARNING: payload output may contain sensitive health or device data.", file=sys.stderr)
    events = capture["events"]
    lengths = Counter(len(payload_bytes(event)) for event in events if event.get("payload") is not None)
    uuids = sorted(
        {
            value
            for event in events
            for value in (event.get("serviceUuid"), event.get("characteristicUuid"))
            if value
        }
    )
    states = Counter(event.get("connectionState") for event in events if event.get("connectionState"))
    errors = Counter(event.get("error") for event in events if event.get("error"))
    duration = events[-1]["relativeTimestampMs"] if events else 0
    print(f"version={capture['formatVersion']}")
    print(f"fixture_fictional={str(capture.get('fixtureFictional', False)).lower()}")
    print(f"events={len(events)} duration_ms={duration}")
    print("payload_lengths=" + ",".join(f"{length}:{count}" for length, count in sorted(lengths.items())))
    print("uuids=" + ",".join(uuids))
    print("fingerprints=" + ",".join(short_fingerprint(payload_bytes(event)) for event in events if event.get("payload") is not None))
    print("states=" + ",".join(f"{key}:{count}" for key, count in sorted(states.items())))
    print("errors=" + ",".join(f"{key}:{count}" for key, count in sorted(errors.items())))
    if args.show_payload:
        for index, event in enumerate(events):
            if event.get("payload") is not None:
                print(f"payload[{index}]={payload_bytes(event).hex()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
