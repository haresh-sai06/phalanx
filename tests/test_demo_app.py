"""Direct HTTP tests against RideLite (no browser)."""
import pytest
from demo_app.app import app, reset

@pytest.fixture(autouse=True)
def client():
    reset()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c

def test_health(client):
    assert client.get("/api/health").json["ok"] is True

def test_help_is_404(client):
    assert client.get("/help").status_code == 404

def test_admin_open_and_passwords(client):
    r = client.get("/admin")
    assert r.status_code == 200
    assert b"alice123" in r.data

def test_xss_reflected(client):
    r = client.get("/estimate", query_string={"q": '<script>alert(1)</script>'})
    assert b"<script>alert(1)</script>" in r.data

def test_sqli_error(client):
    r = client.get("/search", query_string={"q": "x' OR 1=1--"})
    assert r.status_code == 500 and b"OperationalError" in r.data

def test_idor_and_cancel(client):
    client.post("/login", data={"username": "alice", "password": "alice123"})
    client.post("/book", data={"pickup": "A", "dropoff": "B"})
    client.get("/logout")
    client.post("/login", data={"username": "bob", "password": "bob123"})
    rides = client.get("/rides").data
    assert b"alice" in rides
    detail = client.get("/rides/1")
    assert b"Owner:" in detail.data and b"alice" in detail.data
    client.post("/rides/1/cancel")
    assert b"cancelled" in client.get("/rides/1").data

def test_negative_tip(client):
    client.post("/login", data={"username": "alice", "password": "alice123"})
    client.post("/book", data={"pickup": "A", "dropoff": "B"})
    client.post("/rides/1/tip", data={"amount": "-100"})
    assert b"$-87.50" in client.get("/rides/1").data

def test_api_idor_unauthenticated(client):
    client.post("/login", data={"username": "alice", "password": "alice123"})
    client.post("/book", data={"pickup": "A", "dropoff": "B"})
    client.get("/logout")
    r = client.get("/api/rides/1")
    assert r.status_code == 200 and r.json["owner"] == "alice"

def test_open_redirect(client):
    client.post("/login", data={"username": "alice", "password": "alice123"})
    r = client.get("/profile", query_string={"saved": "1", "next": "https://evil.example"}, follow_redirects=False)
    assert r.status_code in (302, 301) and r.headers["Location"] == "https://evil.example"
