import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize("built", [False, True])
def test_root_schema_is_independent_of_frontend_build(monkeypatch, tmp_path, client, built):
    from api.main import create_app

    if built:
        (tmp_path / "index.html").write_text('<html><div id="app"></div></html>')
    monkeypatch.setenv("WEB_DIST_DIR", str(tmp_path))
    application = create_app()
    assert "/" not in application.openapi()["paths"]
    assert "/api" in application.openapi()["paths"]
    with TestClient(application) as root_client:
        response = root_client.get("/")
        info = root_client.get("/api").json()
    assert response.status_code == 200
    if built:
        assert '<div id="app">' in response.text
        assert "text/html" in response.headers["content-type"]
    else:
        assert response.json() == info
        assert "application/json" in response.headers["content-type"]
