import base64
import binascii
import os
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


TOKEN_PREFIX = "v1."
ALLOWED_STRAVA_SCOPES = {"read", "activity:read", "activity:read_all"}


class IntegrationSecurityError(RuntimeError):
    pass


def decode_encryption_key(encoded: str) -> bytes:
    if not isinstance(encoded, str) or not encoded.strip():
        raise IntegrationSecurityError("integration token encryption is not configured")
    try:
        key = base64.urlsafe_b64decode(encoded.strip().encode("ascii"))
    except (ValueError, UnicodeEncodeError, binascii.Error) as error:
        raise IntegrationSecurityError("integration token encryption key is invalid") from error
    if len(key) != 32:
        raise IntegrationSecurityError("integration token encryption key must decode to 32 bytes")
    return key


class IntegrationTokenCipher:
    def __init__(self, encoded_key: str):
        self._cipher = AESGCM(decode_encryption_key(encoded_key))

    def encrypt(self, plaintext: str, *, associated_data: str) -> str:
        if not isinstance(plaintext, str) or not plaintext:
            raise IntegrationSecurityError("provider credential is missing")
        nonce = os.urandom(12)
        ciphertext = self._cipher.encrypt(
            nonce,
            plaintext.encode("utf-8"),
            associated_data.encode("utf-8"),
        )
        return TOKEN_PREFIX + base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")

    def decrypt(self, value: str, *, associated_data: str) -> str:
        if not isinstance(value, str) or not value.startswith(TOKEN_PREFIX):
            raise IntegrationSecurityError("stored provider credential is invalid")
        try:
            payload = base64.urlsafe_b64decode(value[len(TOKEN_PREFIX):].encode("ascii"))
            plaintext = self._cipher.decrypt(
                payload[:12], payload[12:], associated_data.encode("utf-8")
            )
            return plaintext.decode("utf-8")
        except Exception as error:
            raise IntegrationSecurityError("stored provider credential could not be decrypted") from error


def validate_integration_config(config) -> None:
    if not config.get("STRAVA_ENABLED"):
        return
    missing = [
        name
        for name in (
            "STRAVA_CLIENT_ID",
            "STRAVA_CLIENT_SECRET",
            "STRAVA_WEBHOOK_VERIFY_TOKEN",
            "INTEGRATION_TOKEN_ENCRYPTION_KEY",
            "PUBLIC_BASE_URL",
        )
        if not config.get(name)
    ]
    if missing:
        raise RuntimeError(
            "STRAVA_ENABLED requires complete integration configuration: "
            + ", ".join(missing)
        )
    if not str(config["STRAVA_CLIENT_ID"]).isdigit():
        raise RuntimeError("STRAVA_CLIENT_ID must be numeric")
    decode_encryption_key(config["INTEGRATION_TOKEN_ENCRYPTION_KEY"])
    scopes = tuple(config.get("STRAVA_SCOPES") or ())
    if set(scopes) - ALLOWED_STRAVA_SCOPES:
        raise RuntimeError("STRAVA_SCOPES contains a non-read-only scope")
    if "read" not in scopes or not ({"activity:read", "activity:read_all"} & set(scopes)):
        raise RuntimeError("STRAVA_SCOPES must include read and an activity read scope")
    base = urlsplit(str(config["PUBLIC_BASE_URL"]))
    if (
        base.scheme not in {"http", "https"}
        or not base.netloc
        or base.username
        or base.password
        or base.query
        or base.fragment
    ):
        raise RuntimeError("PUBLIC_BASE_URL must be an absolute http(s) URL without credentials or query")
    bounds = {
        "STRAVA_INITIAL_SYNC_DAYS": (1, 3650),
        "STRAVA_SYNC_OVERLAP_SECONDS": (0, 7 * 86400),
        "STRAVA_SYNC_MAX_PAGES": (1, 500),
        "STRAVA_HTTP_TIMEOUT_SECONDS": (1, 60),
    }
    for name, (minimum, maximum) in bounds.items():
        value = config.get(name)
        if type(value) is not int or not minimum <= value <= maximum:
            raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
