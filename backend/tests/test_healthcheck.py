from sqlalchemy.exc import OperationalError

from app.extensions import db


def test_healthcheck_is_public_and_checks_database(client):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.mimetype == "application/json"
    assert response.get_json() == {"app": "health-tracker", "status": "ok"}


def test_healthcheck_returns_generic_503_when_database_fails(app, client, monkeypatch):
    def fail_query(*_args, **_kwargs):
        raise OperationalError("SELECT 1", {}, RuntimeError("fictional DB failure"))

    monkeypatch.setattr(db.session, "execute", fail_query)
    response = client.get("/healthz")

    assert response.status_code == 503
    assert response.get_json() == {"app": "health-tracker", "status": "error"}
    assert b"fictional DB failure" not in response.data
