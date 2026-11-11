"""Boot-level check against a running server.

Usage: python scripts/run_integration.py [base_url]
"""

import sys
import time
from pathlib import Path

import httpx

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
STUDENT = "770001"


def wait_until_up(client: httpx.Client, attempts: int = 30) -> None:
    for _ in range(attempts):
        try:
            if client.get("/").status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(1)
    raise SystemExit("Server never came up")


def check(label: str, condition: bool) -> bool:
    print(f"{'PASS' if condition else 'FAIL'}  {label}")
    return condition


def upload(client: httpx.Client, path: str, fixture: str) -> httpx.Response:
    content = (FIXTURES / fixture).read_bytes()
    return client.post(path, files={"file": (fixture, content, "text/html")})


def main(base_url: str) -> int:
    results = []
    with httpx.Client(base_url=base_url, timeout=30) as client:
        wait_until_up(client)
        student = f"/api/v1/students/{STUDENT}"

        r = upload(client, "/api/v1/admin/catalog/import", "sample_catalog.html")
        results.append(check("catalog import", r.status_code == 200))
        r = client.get("/api/v1/catalog/courses/COSC3506")
        results.append(check("catalog lookup", r.status_code == 200))

        r = upload(client, f"{student}/history/import", "transcript.html")
        results.append(check("transcript import -> 201", r.status_code == 201))

        plan = {"planned_courses": [{"course_code": "COSC-3506", "term": "26F"}]}
        r = client.post(f"{student}/plan", json=plan)
        results.append(check("plan saved", r.status_code == 200))

        report = client.get(f"{student}/audit-report").json()
        errors = [e for t in report.get("timeline_validation", []) for e in t["errors"]]
        results.append(check("audit status warning", report.get("status") == "warning"))
        results.append(check("missing prerequisite flagged",
                             any(e["type"] == "MISSING_PREREQUISITE" for e in errors)))
        results.append(check("cross-list conflict flagged",
                             len(report.get("cross_list_violations", [])) == 1))
        expected = {"total_earned": 9, "total_planned": 3, "total_remaining_for_graduation": 108}
        results.append(check("credit summary", report.get("credit_summary") == expected))

        strict = client.get(f"{student}/audit-report", params={"strict": "true"}).json()
        results.append(check("strict=true -> failed", strict.get("status") == "failed"))

        r = client.get("/api/v1/students/does-not-exist/audit-report")
        results.append(check("unknown student -> 404", r.status_code == 404))

    passed = sum(results)
    print(f"\n{passed}/{len(results)} integration checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"))
