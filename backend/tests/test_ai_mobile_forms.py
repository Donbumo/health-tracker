"""UI-only fixtures: render the real templates without an app, DB or provider."""
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as Row
from urllib.parse import urlencode

from jinja2 import Environment, FileSystemLoader, select_autoescape


APP = Path(__file__).resolve().parents[1] / "app"


def render_operator_fixture():
    def url_for(endpoint, **values):
        if endpoint == "static":
            filename = values.pop("filename")
            return "/static/" + filename + ("?" + urlencode(values) if values else "")
        return "/qa/" + endpoint

    env = Environment(loader=FileSystemLoader(APP / "templates"), autoescape=select_autoescape())
    env.globals.update(
        url_for=url_for, csrf_token=lambda: "fictional-qa-csrf",
        get_flashed_messages=lambda **kwargs: [],
    )
    def draft(kind, index, payload, fields=()):
        return Row(
            public_id=f"qa-draft-{index}", status="pending_confirmation", draft_type=kind,
            payload_json=payload, provenance_json={
                "plan_id": "qa-plan", "plan_summary": "Plan QA de controles editables",
                "step_index": index, "step_status": "ready", "action_label": kind,
                "preview": {"fields": fields},
            },
        )
    drafts = [
        draft("body_measurement", 1, {"weight": "82.5", "unit": "kg", "recorded_at": "2026-09-12T12:00:00", "missing_fields": ["QA: campo opcional pendiente"]}),
        draft("food_entry", 2, {"meal_type": "breakfast", "items": [
            {"name": "Desayuno QA", "calories_kcal": 500, "protein_g": 30},
            {"name": "Segundo elemento QA"},
        ]}),
        draft("action", 3, {}, [
            {"name": "target_value", "label": "Objetivo QA", "kind": "number", "value": 10000},
            {"name": "unit", "label": "Unidad QA", "kind": "text", "value": "step"},
            {"name": "date", "label": "Fecha QA", "kind": "date", "value": "2026-09-12"},
            {"name": "details", "label": "Detalles QA", "kind": "json", "value": {"qa": True}},
        ]),
    ]
    message = Row(role="assistant", content="Plan preparado. Ningún cambio se aplicó.",
                  drafts=drafts, evidence_json=[], created_at=datetime.now(timezone.utc))
    return env.get_template("ai/conversation.html").render(
        conversation=Row(public_id="qa-conversation", title="QA móvil · Operator", messages=[message]),
        current_user=Row(is_authenticated=True, is_admin=False, display_name="QA", username="QA"),
        request=Row(endpoint="ai.conversation"), release_label="QA local sin DB",
        config=Row(AI_MAX_INPUT_CHARS=4000), ai_status=Row(state="available"),
        active_title=None, prepared_prompt="", selection_fields={}, template_followups=[],
    )


def test_operator_fixture_keeps_legacy_and_generic_controls_and_actions():
    html = render_operator_fixture()
    assert '<input name="weight"' in html  # Default text inputs must stay supported.
    assert '<fieldset><legend>Elemento 1</legend>' in html
    assert '<fieldset><legend>Elemento 2</legend>' in html
    assert 'type="number"' in html and 'type="date"' in html
    assert 'aria-label="Plan preparado"' in html
    assert html.count('>Editar</button>') == html.count('>Confirmar</button>') == html.count('>Rechazar</button>') == 3
    assert 'class="checkbox"' in html


def test_operator_stylesheet_cache_key_matches_release():
    assert '/static/css/app.css?v=ai-operator-mobile-1' in render_operator_fixture()
