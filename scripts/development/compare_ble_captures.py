#!/usr/bin/env python3
"""Compare BLE capture structure and byte variability without claiming semantics."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from ble_capture_common import load_capture, payload_bytes


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Compare BLE event structure, lengths and candidate variable offsets.")
    value.add_argument("left", type=Path)
    value.add_argument("right", type=Path)
    return value


def payloads(capture: dict) -> list[bytes]:
    return [payload_bytes(event) for event in capture["events"] if event.get("payload") is not None]


def main() -> int:
    args = parser().parse_args()
    left, right = load_capture(args.left), load_capture(args.right)
    left_payloads, right_payloads = payloads(left), payloads(right)
    pairs = list(zip(left_payloads, right_payloads))
    compared = min(len(left_payloads), len(right_payloads))
    equal_lengths = sum(len(a) == len(b) for a, b in pairs)
    common_offsets: Counter[int] = Counter()
    variable_offsets: Counter[int] = Counter()
    for first, second in pairs:
        for offset, (a_byte, b_byte) in enumerate(zip(first, second)):
            (common_offsets if a_byte == b_byte else variable_offsets)[offset] += 1
    repeated_left = sum(count - 1 for count in Counter(left_payloads).values() if count > 1)
    repeated_right = sum(count - 1 for count in Counter(right_payloads).values() if count > 1)
    print(f"structure.events={len(left['events'])}:{len(right['events'])}")
    print(f"structure.payload_events={len(left_payloads)}:{len(right_payloads)}")
    print(f"lengths={sorted(map(len, left_payloads))}:{sorted(map(len, right_payloads))}")
    print(f"paired={compared} equal_length_pairs={equal_lengths}")
    print("constant_offsets=" + ",".join(str(offset) for offset, count in sorted(common_offsets.items()) if count == compared and compared > 0))
    print("variable_offsets=" + ",".join(f"{offset}:{count}" for offset, count in sorted(variable_offsets.items())))
    print(f"repeated_sequences={repeated_left}:{repeated_right}")
    print("candidate_offsets_only=true; no unit, weight, impedance or composition semantics are inferred")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
