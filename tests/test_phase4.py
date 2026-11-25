from datetime import date

import jwt
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
from main import app, audit_limiter  # noqa: E402
from ratelimit import SlidingWindowLimiter  # noqa: E402
from recommend import build_pathway, first_term, next_term  # noqa: E402

OWNER = "s12345"


@pytest.fixture
def client():
    app.state.catalog = {}
    app.state.students = {}
    auth.reset_users()
    audit_limiter.reset()
    return TestClient(app)


def bearer(client, username, password="MyPass1!"):
    client.post("/api/v1/auth/register", json={"username": username, "password": password})
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def import_history(client, student, transcript_bytes, headers=None):
    return client.post(f"/api/v1/students/{student}/history/import", headers=headers or {},
                       files={"file": ("t.html", transcript_bytes, "text/html")})


@pytest.fixture
def owner(client, catalog_bytes, transcript_bytes):
    headers = bearer(client, OWNER)
    client.post("/api/v1/admin/catalog/import",
                files={"file": ("c.html", catalog_bytes, "text/html")})
    assert import_history(client, OWNER, transcript_bytes, headers).status_code == 201
    return headers


def test_register_and_login(client):
    creds = {"username": "alice", "password": "pw"}
    assert client.post("/api/v1/auth/register", json=creds).status_code == 201
    assert client.post("/api/v1/auth/register", json=creds).status_code == 409
    assert client.post("/api/v1/auth/register",
                       json={"username": " ", "password": "x"}).status_code == 422

    r = client.post("/api/v1/auth/login", json=creds)
    assert r.status_code == 200 and r.json()["token_type"] == "bearer"
    claims = jwt.decode(r.json()["access_token"], auth.SECRET_KEY, algorithms=["HS256"])
    assert claims["sub"] == "alice" and claims["role"] == "student"

    bad = {"username": "alice", "password": "nope"}
    assert client.post("/api/v1/auth/login", json=bad).status_code == 401
    assert client.post("/api/v1/auth/login",
                       json={"username": "ghost", "password": "x"}).status_code == 401


def test_password_is_hashed(client):
    client.post("/api/v1/auth/register", json={"username": "bob", "password": "secret"})
    stored = auth._users["bob"]["hash"]
    assert b"secret" not in stored and stored.startswith(b"$2")


def test_admin_is_seeded(client):
    assert client.post("/api/v1/auth/register",
                       json={"username": "admin", "password": "admin"}).status_code == 409
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin"})
    claims = jwt.decode(r.json()["access_token"], auth.SECRET_KEY, algorithms=["HS256"])
    assert claims["role"] == "admin"


def test_bola_on_history_import(client, transcript_bytes):
    mine = bearer(client, OWNER)
    other = bearer(client, "s99999")
    assert import_history(client, OWNER, transcript_bytes, mine).status_code == 201
    assert import_history(client, OWNER, transcript_bytes).status_code == 401
    assert import_history(client, OWNER, transcript_bytes, other).status_code == 401
    assert import_history(client, "s99999", transcript_bytes, mine).status_code == 401
    garbage = {"Authorization": "Bearer not-a-jwt"}
    assert import_history(client, OWNER, transcript_bytes, garbage).status_code == 401


def test_expired_token_rejected(client, transcript_bytes):
    token = jwt.encode({"sub": OWNER, "role": "student", "exp": 1}, auth.SECRET_KEY)
    headers = {"Authorization": f"Bearer {token}"}
    assert import_history(client, OWNER, transcript_bytes, headers).status_code == 401


@pytest.mark.parametrize("path", ["profile", "plan", "recommendations"])
def test_rbac(client, owner, path):
    url = f"/api/v1/students/{OWNER}/{path}"
    admin = bearer(client, "admin", "admin")
    assert client.get(url).status_code == 401
    assert client.get(url, headers=bearer(client, "intruder")).status_code == 401
    assert client.get(url, headers=owner).status_code == 200
    assert client.get(url, headers=admin).status_code == 200


def test_get_plan(client, owner):
    plan = {"planned_courses": [{"course_code": "COSC-3506", "term": "26F"}]}
    client.post(f"/api/v1/students/{OWNER}/plan", json=plan)
    body = client.get(f"/api/v1/students/{OWNER}/plan", headers=owner).json()
    assert body == {"student_id": OWNER, "plan": plan["planned_courses"]}


def test_audit_rate_limit(client, owner):
    url = f"/api/v1/students/{OWNER}/audit-report"
    codes = [client.get(url, headers=owner).status_code for _ in range(11)]
    assert codes == [200] * 10 + [429]
    # a different credential has its own window
    admin = bearer(client, "admin", "admin")
    assert client.get(url, headers=admin).status_code == 200


def test_sliding_window_expires():
    now = [0.0]
    limiter = SlidingWindowLimiter(limit=2, window_seconds=60, clock=lambda: now[0])
    assert limiter.allow("k") and limiter.allow("k")
    assert not limiter.allow("k")
    now[0] = 30
    assert not limiter.allow("k")
    now[0] = 60.5
    assert limiter.allow("k")


def test_recommendations_endpoint(client, owner):
    body = client.get(f"/api/v1/students/{OWNER}/recommendations", headers=owner).json()
    assert body == {"student_id": OWNER, "recommended_pathway": [
        {"term": "26F", "courses": ["COSC 2007"]},
        {"term": "27W", "courses": ["COSC 3506"]},
    ]}


def course(code, prereqs=()):
    return {"course_code": code, "prerequisites": list(prereqs)}


def test_pathway_orders_prerequisites():
    catalog = {
        "A1000": course("A 1000"),
        "B2000": course("B 2000", ["A 1000"]),
        "C3000": course("C 3000", ["B 2000", "A 1000"]),
        "D1000": course("D 1000", ["X 9999"]),
        "E4000": course("E 4000", ["F4000"]),
        "F4000": course("F 4000", ["E4000"]),
    }
    pathway = build_pathway([], catalog, today=date(2026, 11, 24))
    assert pathway == [
        {"term": "26F", "courses": ["A 1000", "D 1000"]},
        {"term": "27W", "courses": ["B 2000"]},
        {"term": "27F", "courses": ["C 3000"]},
    ]


def test_pathway_skips_completed():
    catalog = {"A1000": course("A 1000"), "B2000": course("B 2000", ["A1000"])}
    history = [{"course_code": "A-1000", "term": "25F", "credits_earned": 3,
                "status": "Completed"}]
    assert build_pathway(history, catalog) == [{"term": "26W", "courses": ["B 2000"]}]


def test_terms():
    assert next_term("26F") == "27W" and next_term("27W") == "27F"
    assert first_term([{"term": "25W"}]) == "25F"
    assert first_term([], today=date(2027, 2, 1)) == "27W"
    assert first_term([], today=date(2026, 9, 1)) == "26F"
