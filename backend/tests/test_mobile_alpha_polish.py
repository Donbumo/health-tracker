from pathlib import Path

from app.extensions import db
from app.models import User
from tests.conftest import login


def _css() -> str:
    return (
        Path(__file__).resolve().parents[1]
        / "app"
        / "static"
        / "css"
        / "app.css"
    ).read_text(encoding="utf-8")


def test_base_template_has_mobile_viewport_and_collapsed_mobile_navigation(client, user):
    login(client)
    response = client.get("/dashboard")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'name="viewport"' in html
    assert "width=device-width, initial-scale=1" in html
    assert 'class="nav-actions desktop-nav"' in html
    assert '<details class="mobile-menu">' in html
    assert '<summary aria-label="Abrir o cerrar menú principal">Menú</summary>' in html
    assert "Principal" in html
    assert "Datos" in html
    for label in (
        "Dashboard",
        "Wellness",
        "Peso",
        "Nutrici",
        "Energ",
        "Entrenamiento",
        "Sesiones",
        "Progreso",
        "Alacena",
        "Recetas",
        "Laboratorios",
        "Importar",
        "Historial imports",
        "Cerrar sesi",
        "Privacidad",
        "Alpha 0.8",
    ):
        assert label in html


def test_mobile_css_contains_responsive_nav_forms_tables_and_focus_rules():
    css = _css()

    assert "@media (max-width: 650px)" in css
    assert "focus-visible" in css
    assert ".desktop-nav { display: none; }" in css
    assert ".mobile-menu {" in css
    assert "display: contents" in css
    assert ".mobile-menu summary" in css
    assert ".mobile-menu-panel" in css
    assert "max-height: min(70vh, 32rem)" in css
    assert "overflow-y: auto" in css
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" not in css
    assert "min-height: 44px" in css
    assert "font-size: 16px" in css
    assert "-webkit-overflow-scrolling: touch" in css
    assert "table {" in css
    assert ".quick-actions" in css


def test_mobile_logout_remains_post_with_csrf(client, user):
    login(client)
    html = client.get("/dashboard").get_data(as_text=True)

    assert 'action="/logout" method="post"' in html
    assert 'name="csrf_token"' in html
    assert html.count('action="/logout" method="post"') == 2


def test_mobile_admin_links_follow_existing_permissions(app, client, user):
    with app.app_context():
        admin = User(username="mobile-admin", email="mobile-admin@example.com", role="admin")
        admin.set_password("admin-password")
        db.session.add(admin)
        db.session.commit()

    login(client)
    normal_html = client.get("/dashboard").get_data(as_text=True)

    assert 'href="/admin/users"' not in normal_html
    assert 'href="/admin/system"' not in normal_html
    assert "Administraci" not in normal_html

    client.post("/logout", data={"csrf_token": ""})
    login(client, "mobile-admin", "admin-password")
    admin_html = client.get("/dashboard").get_data(as_text=True)

    assert 'href="/admin/users"' in admin_html
    assert 'href="/admin/system"' in admin_html
    assert "Administraci" in admin_html


def test_mobile_smoke_routes_keep_forms_actions_and_responsive_wrappers(client, user):
    login(client)
    routes = (
        "/dashboard",
        "/admin/users",
        "/privacy",
        "/weigh-ins",
        "/daily-energy",
        "/daily-nutrition",
        "/training-sessions/new",
        "/imports/standard",
        "/imports/history",
    )

    for path in routes:
        response = client.get(path)
        if path == "/admin/users":
            assert response.status_code == 403
            continue
        assert response.status_code == 200, path

    dashboard = client.get("/dashboard").get_data(as_text=True)
    assert "quick-actions" in dashboard
    assert "checklist" in dashboard
    assert "Capturar peso" in dashboard

    standard_import = client.get("/imports/standard").get_data(as_text=True)
    assert "<form" in standard_import
    assert "Analizar sin guardar" in standard_import

    history = client.get("/imports/history").get_data(as_text=True)
    assert "table" in history or "Importar JSON" in history
