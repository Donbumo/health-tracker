from __future__ import annotations

from dataclasses import dataclass

from app.services.importers.standard_json_generator import SUPPORTED_TARGETS
from app.services.real_file_imports import MAX_REAL_FILE_BYTES


@dataclass(frozen=True)
class ImportAdapterSpec:
    adapter_id: str
    label: str
    data_domains: tuple[str, ...]
    file_extensions: tuple[str, ...]
    mime_types: tuple[str, ...]
    schema_version: str
    max_bytes: int
    capabilities: tuple[str, ...]
    unsupported_fields: tuple[str, ...] = ()


class ImportAdapterRegistry:
    """Declarative public inventory for the existing import pipelines.

    Parsing, preview, validation and execution remain in their domain services;
    this registry prevents the web UI from hard-coding a second support matrix.
    """

    def __init__(self) -> None:
        self._specs = {spec.adapter_id: spec for spec in _specs()}

    def get(self, adapter_id: str) -> ImportAdapterSpec | None:
        return self._specs.get(adapter_id)

    @property
    def specs(self) -> tuple[ImportAdapterSpec, ...]:
        return tuple(self._specs.values())


def _specs() -> tuple[ImportAdapterSpec, ...]:
    return (
        ImportAdapterSpec(
            adapter_id="standard_json",
            label="JSON de Health Tracker o JSON asistido",
            data_domains=tuple(sorted(SUPPORTED_TARGETS)),
            file_extensions=(".json",),
            mime_types=("application/json", "text/json"),
            schema_version="1.0",
            max_bytes=10 * 1024 * 1024,
            capabilities=("detect", "preview", "validate", "deduplicate", "confirm", "atomic"),
        ),
        ImportAdapterSpec(
            adapter_id="activity_files",
            label="Actividad o ruta",
            data_domains=("activity", "route"),
            file_extensions=(".fit", ".gpx", ".tcx"),
            mime_types=(
                "application/octet-stream",
                "application/gpx+xml",
                "application/vnd.garmin.tcx+xml",
                "application/xml",
                "text/xml",
            ),
            schema_version="1.0",
            max_bytes=MAX_REAL_FILE_BYTES,
            capabilities=("signature_detect", "preview", "validate", "deduplicate", "confirm", "atomic"),
            unsupported_fields=("vendor_private_api", "executable_content"),
        ),
        ImportAdapterSpec(
            adapter_id="wellness_csv",
            label="CSV de peso o energía diaria",
            data_domains=("weigh_in_batch", "daily_energy"),
            file_extensions=(".csv", ".tsv", ".txt"),
            mime_types=("text/csv", "text/tab-separated-values", "text/plain"),
            schema_version="1.0",
            max_bytes=MAX_REAL_FILE_BYTES,
            capabilities=("column_detect", "preview", "validate", "deduplicate", "confirm", "atomic"),
            unsupported_fields=("ambiguous_us_date_without_explicit_profile",),
        ),
    )
