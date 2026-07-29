#!/usr/bin/env python3
"""Smoke tests sanitizados para Alpha 1.5 RC1; read-only por defecto."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import ipaddress
import json
import os
import ssl
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
import uuid


WRITE_CONFIRMATION = "QA-ALPHA15-WRITE"


class SmokeFailure(RuntimeError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass
class Result:
    status: int
    data: Any
    elapsed_ms: int


class SmokeClient:
    def __init__(self, base_url: str, token: str, timeout: float = 10.0, allow_http: bool = False):
        parsed = urlsplit(base_url.strip())
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            raise SmokeFailure("base URL inválida")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise SmokeFailure("base URL no puede contener credenciales, consulta ni fragmento")
        if parsed.scheme != "https" and not allow_http:
            raise SmokeFailure("HTTPS es obligatorio; usa --allow-http solo para una LAN QA explícita")
        try:
            port = parsed.port
        except ValueError:
            raise SmokeFailure("puerto invalido") from None
        if port == 0:
            raise SmokeFailure("puerto invalido")
        path = unquote(parsed.path).rstrip("/")
        if "\\" in path or "//" in path or any(part in {".", ".."} for part in path.split("/")):
            raise SmokeFailure("ruta base ambigua")
        if parsed.scheme == "http" and not self._is_local_host(parsed.hostname):
            raise SmokeFailure("HTTP se limita a loopback, RFC1918, ULA o nombres .local")
        self.base_url = base_url.strip().rstrip("/")
        self.token = token
        self.timeout = timeout
        self.ssl_context = ssl.create_default_context()
        self.opener = build_opener(_NoRedirect(), HTTPSHandler(context=self.ssl_context))

    @staticmethod
    def _is_local_host(hostname: str) -> bool:
        normalized = hostname.rstrip(".").lower()
        if normalized == "localhost" or normalized.endswith(".local"):
            return True
        try:
            address = ipaddress.ip_address(normalized)
        except ValueError:
            return False
        if isinstance(address, ipaddress.IPv4Address):
            private_v4 = (
                ipaddress.ip_network("10.0.0.0/8"),
                ipaddress.ip_network("172.16.0.0/12"),
                ipaddress.ip_network("192.168.0.0/16"),
            )
            return address.is_loopback or address.is_link_local or any(address in network for network in private_v4)
        return address.is_loopback or address.is_link_local or address in ipaddress.ip_network("fc00::/7")

    def request(self, method: str, path: str, payload: dict | None = None, key: str | None = None,
                authenticated: bool = True) -> Result:
        headers = {"Accept": "application/json"}
        if authenticated:
            headers["Authorization"] = f"Bearer {self.token}"
        if key:
            headers["Idempotency-Key"] = key
        body = None
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        started = time.monotonic()
        try:
            with self.opener.open(
                Request(self.base_url + path, data=body, headers=headers, method=method),
                timeout=self.timeout,
            ) as response:
                raw = response.read(1_048_577)
                if len(raw) > 1_048_576:
                    raise SmokeFailure(f"respuesta demasiado grande en {path}")
                status = response.status
        except HTTPError as error:
            raise SmokeFailure(f"HTTP {error.code} en {path}") from None
        except (URLError, TimeoutError, ssl.SSLError):
            raise SmokeFailure(f"fallo de red/TLS sanitizado en {path}") from None
        try:
            decoded = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise SmokeFailure(f"respuesta no JSON o truncada en {path}") from None
        return Result(status, decoded, round((time.monotonic() - started) * 1000))


def _envelope(result: Result, path: str, expected: set[int] = {200}) -> Any:
    if result.status not in expected or not isinstance(result.data, dict):
        raise SmokeFailure(f"status/schema inesperado en {path}")
    if "data" not in result.data or not isinstance(result.data.get("meta"), dict):
        raise SmokeFailure(f"envelope inválido en {path}")
    return result.data["data"]


def run_read_only(client: SmokeClient, emit=print) -> None:
    today = date.today().isoformat()
    probes = [
        ("readiness", "GET", "/healthz", False),
        ("api_health", "GET", "/api/v1/health", False),
        ("profile", "GET", "/api/v1/me", True),
        ("negotiation_profile", "GET", "/api/v1/companion/profile", True),
        ("sync_status", "GET", "/api/v1/sync/status", True),
        ("history", "GET", "/api/v1/mobile/history?limit=1", True),
        ("progress", "GET", "/api/v1/mobile/progress/summary?range=30", True),
        ("health_summary", "GET", f"/api/v1/mobile/health/today?date={today}&timezone=UTC", True),
        ("exercise_catalog", "GET", "/api/v1/mobile/exercises?limit=1", True),
        ("food_catalog", "GET", "/api/v1/mobile/foods?limit=1", True),
    ]
    for label, method, path, authenticated in probes:
        result = client.request(method, path, authenticated=authenticated)
        if path == "/healthz":
            if result.status != 200 or result.data != {"app": "health-tracker", "status": "ok"}:
                raise SmokeFailure("readiness inválida")
        else:
            _envelope(result, path)
        emit(f"PASS {label} status={result.status} elapsed_ms={result.elapsed_ms}")
    emit("SKIP health_connect_settings: configuración local Android, sin endpoint servidor")


def _find(items: Any, public_id: str) -> dict | None:
    if not isinstance(items, list):
        return None
    return next((item for item in items if isinstance(item, dict) and item.get("id") == public_id), None)


def run_write(client: SmokeClient, emit=print) -> None:
    run_id = uuid.uuid4()
    body_id = str(uuid.uuid4())
    body_event = str(uuid.uuid4())
    step_id = str(uuid.uuid4())
    step_event = str(uuid.uuid4())
    qa_day = date.today() + timedelta(days=3650)
    recorded_at = datetime.combine(qa_day, datetime.min.time(), timezone.utc).replace(hour=12).isoformat().replace("+00:00", "Z")
    prefix = f"alpha15-smoke-{run_id}"
    body_revision = None
    step_revision = None
    try:
        body_payload = {
            "public_id": body_id, "client_event_id": body_event, "recorded_at": recorded_at,
            "weight_kg": "70", "source": "manual", "notes": "Fixture QA Alpha 1.5; eliminar",
        }
        first = client.request("POST", "/api/v1/mobile/body-stats", body_payload, prefix + "-body-create")
        if first.status == 201:
            body_revision = 1
        body = _envelope(first, "/api/v1/mobile/body-stats", {201})
        body_revision = body.get("revision")
        replay = _envelope(
            client.request("POST", "/api/v1/mobile/body-stats", body_payload, prefix + "-body-create"),
            "/api/v1/mobile/body-stats", {201},
        )
        if replay.get("id") != body_id:
            raise SmokeFailure("idempotencia corporal falló")
        body = _envelope(client.request(
            "PATCH", f"/api/v1/mobile/body-stats/{quote(body_id)}",
            {"base_revision": body_revision, "weight_kg": "70.1"}, prefix + "-body-update",
        ), "body update")
        body_revision = body.get("revision")
        listing = _envelope(client.request("GET", "/api/v1/mobile/body-stats?limit=100"), "body list")
        if _find(listing.get("items"), body_id) is None:
            raise SmokeFailure("medición QA no consultable")

        step_payload = {
            "public_id": step_id, "client_event_id": step_event, "date": qa_day.isoformat(),
            "steps": 1234, "source": "health_connect_aggregate",
        }
        step_result = client.request(
            "POST", "/api/v1/mobile/steps", step_payload, prefix + "-steps-create",
        )
        if step_result.status == 201:
            step_revision = 1
        step = _envelope(step_result, "steps create", {201})
        step_revision = step.get("revision")
        replay_step = _envelope(client.request(
            "POST", "/api/v1/mobile/steps", step_payload, prefix + "-steps-create",
        ), "steps replay", {201})
        if replay_step.get("id") != step_id:
            raise SmokeFailure("idempotencia de pasos falló")
        emit("PASS write create/idempotency/update/get (payloads sanitizados)")
    finally:
        if step_revision is not None:
            try:
                client.request("DELETE", f"/api/v1/mobile/steps/{quote(step_id)}",
                               {"base_revision": step_revision}, prefix + "-steps-delete")
            except SmokeFailure:
                pass
        if body_revision is not None:
            try:
                client.request("DELETE", f"/api/v1/mobile/body-stats/{quote(body_id)}",
                               {"base_revision": body_revision}, prefix + "-body-delete")
            except SmokeFailure:
                pass
    remaining_body = _envelope(client.request("GET", "/api/v1/mobile/body-stats?limit=100"), "body cleanup")
    remaining_steps = _envelope(client.request(
        "GET", f"/api/v1/mobile/steps?from={qa_day.isoformat()}&to={qa_day.isoformat()}&limit=100"
    ), "steps cleanup")
    if _find(remaining_body.get("items"), body_id) or _find(remaining_steps.get("items"), step_id):
        raise SmokeFailure("la limpieza QA no quedó confirmada")
    emit("PASS write cleanup verified")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("ALPHA15_BASE_URL"))
    parser.add_argument("--token", default=os.getenv("ALPHA15_BEARER_TOKEN"))
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--allow-http", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--confirm-write")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        if not args.base_url or not args.token:
            raise SmokeFailure("faltan base URL o Bearer token QA")
        if args.timeout <= 0 or args.timeout > 60:
            raise SmokeFailure("timeout fuera del rango 0-60 segundos")
        if args.write and args.confirm_write != WRITE_CONFIRMATION:
            raise SmokeFailure(f"modo write requiere --confirm-write {WRITE_CONFIRMATION}")
        client = SmokeClient(args.base_url, args.token, args.timeout, args.allow_http)
        run_read_only(client)
        if args.write:
            run_write(client)
        print("SMOKE PASS")
        return 0
    except SmokeFailure as error:
        print(f"SMOKE FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
