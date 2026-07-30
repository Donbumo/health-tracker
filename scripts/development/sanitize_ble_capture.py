#!/usr/bin/env python3
"""Sanitize a local ble-capture-v1 export into a fictional fixture candidate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ble_capture_common import load_capture, sanitized_copy


def parse_range(value: str) -> tuple[int, int]:
    try:
        start_text, end_text = value.split(":", 1)
        start, end = int(start_text), int(end_text)
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError("range must be START_MS:END_MS") from exc
    if start < 0 or end < start:
        raise argparse.ArgumentTypeError("range must be non-negative and ordered")
    return start, end


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Sanitize a private ble-capture-v1 without overwriting the source.")
    value.add_argument("input", type=Path, help="Local capture JSON to sanitize")
    value.add_argument("output", type=Path, help="New fixture-candidate path (must not exist)")
    value.add_argument("--max-events", type=int, default=500, choices=range(1, 2001), metavar="1..2000")
    value.add_argument("--drop-range", action="append", default=[], type=parse_range, metavar="START_MS:END_MS")
    return value


def main() -> int:
    args = parser().parse_args()
    source = args.input.expanduser().resolve(strict=True)
    target = args.output.expanduser().resolve(strict=False)
    if source == target or target.exists():
        parser().error("output must be a new path different from the input")
    capture = load_capture(source)
    candidate = sanitized_copy(capture, args.max_events, args.drop_range)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print("WARNING: this is only a candidate fixture. Review every payload before adding it to Git.", file=sys.stderr)
    print(f"wrote {target} ({len(candidate['events'])} events); original was not modified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
