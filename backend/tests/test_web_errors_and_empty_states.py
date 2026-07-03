from tests.conftest import login


def test_custom_403_and_404_pages_are_clear(client, user):
    login(client)
    forbidden = client.get("/admin/users")
    assert forbidden.status_code == 403
    assert b"Acceso denegado" in forbidden.data
    assert b"Volver al dashboard" in forbidden.data

    missing = client.get("/this-route-does-not-exist")
    assert missing.status_code == 404
    assert b"P" in missing.data and b"gina no encontrada" in missing.data
    assert b"no existe o no est" in missing.data


def test_empty_primary_lists_offer_real_actions(client, user):
    login(client)
    expectations = (
        ("/daily-energy", b"Capturar nuevo", b'href="/manual/energy"'),
        ("/daily-nutrition", b"Capturar nuevo", b'href="/manual/nutrition"'),
        ("/weigh-ins", b"Capturar nuevo", b'href="/manual/weigh-in"'),
        ("/training-plans", b"Importar JSON", b'href="/training-plans/import"'),
        ("/training-sessions", b"Capturar nuevo", b'href="/training-sessions/new"'),
        ("/uploads", b"Seleccionar archivo", b'href="#upload-form"'),
    )
    for path, label, target in expectations:
        response = client.get(path)
        assert response.status_code == 200
        assert label in response.data
        assert target in response.data
