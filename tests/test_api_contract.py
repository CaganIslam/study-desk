"""Contract suite: status, shape and field names only, never exact values."""


def test_health_shape(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"status", "version", "data_root_configured", "setup_complete", "boot"}
    assert isinstance(body["status"], str)
    assert isinstance(body["version"], str)
    assert isinstance(body["data_root_configured"], bool)
    assert isinstance(body["setup_complete"], bool)
    assert isinstance(body["boot"], str)


def test_unknown_api_path_uses_error_shape(client):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    error = response.json()["error"]
    assert set(error) == {"code", "message"}


def test_index_page_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_strings_file_is_served(client):
    response = client.get("/strings.tr.json")
    assert response.status_code == 200
    assert isinstance(response.json(), dict)
