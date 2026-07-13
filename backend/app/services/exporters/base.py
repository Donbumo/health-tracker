import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable


class ExportError(ValueError):
    pass


@dataclass(frozen=True)
class ExportArtifact:
    content: bytes
    mimetype: str
    extension: str
    warning: str | None = None
    inline: bool = False


@dataclass(frozen=True)
class ExportCapability:
    supported: bool
    reason: str | None = None
    warnings: tuple[str, ...] = ()
    lossy_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExportPreview:
    domain: str
    format_name: str
    extension: str
    media_type: str
    filename: str
    capability: ExportCapability


@dataclass(frozen=True)
class ExportSpec:
    domain: str
    format_name: str
    extension: str
    media_type: str
    render: Callable[[Any, int, dict[str, Any]], ExportArtifact]
    filename: Callable[[Any, dict[str, Any]], str]
    capability: Callable[[Any, int, dict[str, Any]], ExportCapability]
    exporter_version: str = "1.0"


class BaseExporter(ABC):
    format_name: str

    @abstractmethod
    def export(self, resource: Any, user_id: int) -> ExportArtifact:
        """Serialize one user-owned resource into an export artifact."""

    @staticmethod
    def ensure_owner(resource: Any, user_id: int) -> None:
        if resource.user_id != user_id:
            raise ExportError("Resource does not belong to this user")


def serialize_json(document: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


# TODO: Add an ExportRecord model if persisted export auditing becomes a product
# requirement. UploadedFile is intentionally reserved for input/source artifacts.
