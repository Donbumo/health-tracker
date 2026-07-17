from pathlib import Path

import pytest


def test_context_router_and_active_handoff_are_compact_and_separated():
    repository_root = Path(__file__).resolve().parents[2]
    agents = repository_root / "AGENTS.md"
    handoff = repository_root / "docs" / "ACTIVE_HANDOFF.md"
    if not handoff.is_file():
        pytest.skip("Repository documentation is not copied into the production image")

    agents_content = agents.read_text(encoding="utf-8")
    handoff_content = handoff.read_text(encoding="utf-8")

    assert "No toques `/data`" in agents_content
    assert "user_id" in agents_content
    assert "docs/DOCUMENTATION_INDEX.md" in agents_content
    assert len(agents_content.splitlines()) <= 120

    for heading in (
        "## Estado actual",
        "## Trabajo en curso",
        "## Bloqueadores y riesgos",
        "## Siguiente paso",
        "## Pruebas relevantes",
    ):
        assert heading in handoff_content
    assert "DOCUMENTATION_INDEX.md" in handoff_content
    assert "## Actualización" not in handoff_content
    assert "Restore/import real aún no existe" not in handoff_content
    assert len(handoff_content.splitlines()) <= 80
