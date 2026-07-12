"""Generate tiny fictitious FIT fixtures for Health Tracker QA.

These files are synthetic and contain no real user/device data.  The builder is
small on purpose: it writes only the message/field subset needed by the tests
and relies on fitdecode's CRC implementation so the resulting files are parsed
by the same real decoder used by the application.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import struct

from fitdecode.utils import compute_crc


ROOT = Path(__file__).resolve().parent
FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)

UINT8 = 0x02
UINT16 = 0x84
UINT32 = 0x86
SINT32 = 0x85

SPORT_CYCLING = 2
SUB_SPORT_ROAD = 6


def fit_timestamp(value: str) -> int:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return int((dt - FIT_EPOCH).total_seconds())


def semicircles(degrees: float) -> int:
    return int(round(degrees * (2**31) / 180))


def altitude(raw_meters: float) -> int:
    return int(round((raw_meters + 500) * 5))


def meters_100(raw_meters: float) -> int:
    return int(round(raw_meters * 100))


def seconds_1000(raw_seconds: float) -> int:
    return int(round(raw_seconds * 1000))


def speed_1000(raw_mps: float) -> int:
    return int(round(raw_mps * 1000))


def definition(local_id: int, global_id: int, fields: list[tuple[int, int, int]]) -> bytes:
    payload = bytearray([0x40 | local_id, 0, 0])
    payload += struct.pack("<H", global_id)
    payload.append(len(fields))
    for number, size, base_type in fields:
        payload += bytes([number, size, base_type])
    return bytes(payload)


def data(local_id: int, values: list[tuple[str, int | float]]) -> bytes:
    payload = bytearray([local_id])
    for fmt, value in values:
        payload += struct.pack("<" + fmt, value)
    return bytes(payload)


def fit_file(records: list[bytes], *, profile_version: int = 2121) -> bytes:
    data_bytes = b"".join(records)
    header = bytearray(14)
    header[0] = 14
    header[1] = 16
    header[2:4] = struct.pack("<H", profile_version)
    header[4:8] = struct.pack("<I", len(data_bytes))
    header[8:12] = b".FIT"
    header[12:14] = struct.pack("<H", compute_crc(header[:12]))
    body = bytes(header) + data_bytes
    return body + struct.pack("<H", compute_crc(body))


def valid_activity(*, gps: bool = True, unknown: bool = False, invalid_coordinates: bool = False) -> bytes:
    started = fit_timestamp("2026-07-12T08:00:00+00:00")
    mid = fit_timestamp("2026-07-12T08:15:00+00:00")
    ended = fit_timestamp("2026-07-12T08:30:00+00:00")
    records: list[bytes] = []

    file_id_fields = [(0, 1, UINT8), (1, 2, UINT16), (2, 2, UINT16), (4, 4, UINT32)]
    records += [
        definition(0, 0, file_id_fields),
        data(0, [("B", 4), ("H", 1), ("H", 1), ("I", started)]),
    ]

    device_fields = [(253, 4, UINT32), (2, 2, UINT16), (4, 2, UINT16), (3, 4, UINT32)]
    records += [
        definition(1, 23, device_fields),
        data(1, [("I", started), ("H", 1), ("H", 1), ("I", 123456)]),
    ]

    sport_fields = [(0, 1, UINT8), (1, 1, UINT8)]
    records += [
        definition(2, 12, sport_fields),
        data(2, [("B", SPORT_CYCLING), ("B", SUB_SPORT_ROAD)]),
    ]

    record_fields = [(253, 4, UINT32), (2, 2, UINT16), (3, 1, UINT8), (4, 1, UINT8), (5, 4, UINT32), (6, 2, UINT16), (7, 2, UINT16)]
    record_format = [("I", started), ("H", altitude(2240)), ("B", 120), ("B", 80), ("I", meters_100(0)), ("H", speed_1000(0)), ("H", 150)]
    record_mid = [("I", mid), ("H", altitude(2248)), ("B", 130), ("B", 85), ("I", meters_100(6000)), ("H", speed_1000(6.6)), ("H", 180)]
    record_end = [("I", ended), ("H", altitude(2255)), ("B", 140), ("B", 90), ("I", meters_100(12000)), ("H", speed_1000(7.2)), ("H", 220)]
    if gps:
        first_lat = 100.0 if invalid_coordinates else 19.4326
        record_fields = [(253, 4, UINT32), (0, 4, SINT32), (1, 4, SINT32), *record_fields[1:]]
        record_format = [("I", started), ("i", semicircles(first_lat)), ("i", semicircles(-99.1332)), *record_format[1:]]
        record_mid = [("I", mid), ("i", semicircles(19.4330)), ("i", semicircles(-99.1340)), *record_mid[1:]]
        record_end = [("I", ended), ("i", semicircles(19.4340)), ("i", semicircles(-99.1350)), *record_end[1:]]
    if unknown:
        record_fields.append((99, 1, UINT8))
        record_format.append(("B", 7))
        record_mid.append(("B", 8))
        record_end.append(("B", 9))
    records.append(definition(3, 20, record_fields))
    records += [data(3, record_format), data(3, record_mid), data(3, record_end)]

    lap_fields = [
        (253, 4, UINT32), (2, 4, UINT32), (7, 4, UINT32), (8, 4, UINT32),
        (9, 4, UINT32), (11, 2, UINT16), (13, 2, UINT16), (14, 2, UINT16),
        (15, 1, UINT8), (16, 1, UINT8), (17, 1, UINT8), (18, 1, UINT8),
        (19, 2, UINT16), (20, 2, UINT16), (21, 2, UINT16), (22, 2, UINT16),
    ]
    records.append(definition(4, 19, lap_fields))
    records.append(data(4, [("I", mid), ("I", started), ("I", seconds_1000(900)), ("I", seconds_1000(900)), ("I", meters_100(6000)), ("H", 150), ("H", speed_1000(6.6)), ("H", speed_1000(7.0)), ("B", 125), ("B", 135), ("B", 82), ("B", 88), ("H", 165), ("H", 190), ("H", 8), ("H", 1)]))
    records.append(data(4, [("I", ended), ("I", mid), ("I", seconds_1000(900)), ("I", seconds_1000(900)), ("I", meters_100(6000)), ("H", 170), ("H", speed_1000(6.8)), ("H", speed_1000(7.2)), ("B", 135), ("B", 140), ("B", 88), ("B", 92), ("H", 200), ("H", 240), ("H", 7), ("H", 0)]))

    session_fields = [
        (253, 4, UINT32), (2, 4, UINT32), (7, 4, UINT32), (8, 4, UINT32),
        (9, 4, UINT32), (11, 2, UINT16), (14, 2, UINT16), (15, 2, UINT16),
        (16, 1, UINT8), (17, 1, UINT8), (18, 1, UINT8), (19, 1, UINT8),
        (20, 2, UINT16), (21, 2, UINT16), (22, 2, UINT16), (23, 2, UINT16),
        (5, 1, UINT8), (6, 1, UINT8),
    ]
    records += [
        definition(5, 18, session_fields),
        data(5, [("I", ended), ("I", started), ("I", seconds_1000(1800)), ("I", seconds_1000(1800)), ("I", meters_100(12000)), ("H", 320), ("H", speed_1000(6.7)), ("H", speed_1000(7.2)), ("B", 132), ("B", 140), ("B", 86), ("B", 92), ("H", 182), ("H", 240), ("H", 15), ("H", 1), ("B", SPORT_CYCLING), ("B", SUB_SPORT_ROAD)]),
    ]

    activity_fields = [(253, 4, UINT32), (0, 4, UINT32), (1, 2, UINT16), (2, 1, UINT8), (3, 1, UINT8), (4, 1, UINT8)]
    records += [
        definition(6, 34, activity_fields),
        data(6, [("I", ended), ("I", seconds_1000(1800)), ("H", 1), ("B", 0), ("B", 26), ("B", 1)]),
    ]

    return fit_file(records)


def main() -> None:
    (ROOT / "valid_activity.fit").write_bytes(valid_activity(gps=True))
    (ROOT / "valid_activity_no_gps.fit").write_bytes(valid_activity(gps=False))
    (ROOT / "valid_activity_unknown_field.fit").write_bytes(valid_activity(gps=True, unknown=True))
    (ROOT / "invalid_coordinates.fit").write_bytes(valid_activity(gps=True, invalid_coordinates=True))
    valid = valid_activity(gps=True)
    (ROOT / "truncated.fit").write_bytes(valid[:-8])
    invalid_crc = bytearray(valid)
    invalid_crc[-1] ^= 0xFF
    (ROOT / "invalid_crc.fit").write_bytes(bytes(invalid_crc))
    invalid_header = bytearray(valid)
    invalid_header[8:12] = b"NOPE"
    (ROOT / "invalid_header.fit").write_bytes(bytes(invalid_header))


if __name__ == "__main__":
    main()
