import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402

BASE = "/api/v1/students/770001"


@pytest.fixture
def client():
    app.state.catalog = {}
    app.state.students = {}
    return TestClient(app)


def upload(client, path, content, name="file.html"):
    return client.post(path, files={"file": (name, content, "text/html")})


@pytest.fixture
def loaded(client, catalog_bytes, transcript_bytes):
    assert upload(client, "/api/v1/admin/catalog/import", catalog_bytes).status_code == 200
    assert upload(client, f"{BASE}/history/import", transcript_bytes).status_code == 201
    return client


def test_root(client):
    assert client.get("/").status_code == 200


def test_catalog_endpoints(client, catalog_bytes):
    response = upload(client, "/api/v1/admin/catalog/import", catalog_bytes)
    assert response.json()["courses_imported"] == 5
    assert client.get("/api/v1/catalog/courses/cosc-3506").json()["credits"] == 3
    assert client.get("/api/v1/catalog/courses/NOPE1000").status_code == 404
    assert upload(client, "/api/v1/admin/catalog/import", b"  ").status_code == 400
    assert upload(client, "/api/v1/admin/catalog/import", b"<p>x</p>").status_code == 400


def test_history_plan_profile(loaded):
    plan = {"planned_courses": [{"course_code": "COSC-3506", "term": "26F"}]}
    assert loaded.post(f"{BASE}/plan", json=plan).json()["planned_courses_saved"] == 1
    assert loaded.put(f"{BASE}/plan", json=plan).status_code == 200
    profile = loaded.get(f"{BASE}/profile").json()
    assert profile["plan"] == plan["planned_courses"]
    assert len(profile["history"]) == 5

    history = {"history": [{"course_code": "COSC-2007", "term": "25F",
                            "credits_earned": 3, "status": "Completed"}]}
    assert loaded.put(f"{BASE}/history", json=history).status_code == 200
    assert loaded.delete(f"{BASE}/plan").json() == {"status": "success"}
    assert loaded.delete(f"{BASE}/history").json() == {"status": "success"}
    assert loaded.get(f"{BASE}/profile").json()["history"] == []


def test_unknown_student_is_404(client):
    assert client.get("/api/v1/students/nobody/profile").status_code == 404
    assert client.get("/api/v1/students/nobody/audit-report").status_code == 404
    assert client.post("/api/v1/students/nobody/plan",
                       json={"planned_courses": []}).status_code == 404


def test_audit_report(loaded):
    plan = {"planned_courses": [{"course_code": "COSC 3506", "term": "26F"}]}
    loaded.post(f"{BASE}/plan", json=plan)

    report = loaded.get(f"{BASE}/audit-report").json()
    assert set(report) == {"student_id", "status", "timeline_validation",
                           "cross_list_violations", "credit_summary"}
    assert report["student_id"] == "770001"
    assert report["status"] == "warning"
    assert report["timeline_validation"][0]["errors"][0]["type"] == "MISSING_PREREQUISITE"
    assert report["cross_list_violations"][0]["type"] == "CROSS_LIST_CONFLICT"
    assert report["credit_summary"] == {"total_earned": 9, "total_planned": 3,
                                        "total_remaining_for_graduation": 108}

    assert loaded.get(f"{BASE}/audit-report?strict=true").json()["status"] == "failed"
    assert loaded.get(f"{BASE}/audit-report?strict=false").json()["status"] == "warning"


def test_audit_ok(loaded):
    loaded.post(f"{BASE}/plan", json={"planned_courses": [
        {"course_code": "COSC-2007", "term": "26F"}]})
    assert loaded.get(f"{BASE}/audit-report?strict=true").json()["status"] == "ok"
