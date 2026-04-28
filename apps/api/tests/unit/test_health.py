def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_readiness_ok(client):
    r = client.get("/ready")
    assert r.status_code == 200
