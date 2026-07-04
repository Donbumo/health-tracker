from pathlib import Path

import pytest


def test_active_handoff_exists_and_carries_required_safety_context():
    handoff = Path(__file__).resolve().parents[2] / "docs" / "ACTIVE_HANDOFF.md"
    if not handoff.is_file():
        pytest.skip("Repository documentation is not copied into the production image")
    content = handoff.read_text(encoding="utf-8")

    assert "AGENTS.md" in content
    assert "docs/PROJECT_CONTEXT.md" in content
    assert "No tocar `/data`" in content
    assert "user_id" in content
    assert "Restore/import real aún no existe" in content
