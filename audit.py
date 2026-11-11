"""Degree audit rules: prerequisites, cross-listings, retakes and credit totals."""

import re

from catalog import display_code, normalize_code

GRADUATION_CREDITS = 120
SEASONS = {"W": 0, "SP": 1, "S": 2, "F": 3}
TERM_PATTERN = re.compile(r"(\d{2})\s*(SP|W|S|F)", re.IGNORECASE)
UNKNOWN_TERM = (float("inf"), float("inf"))


def term_key(term: str) -> tuple:
    """Sort key for terms like 23F or 26SP. Unrecognised terms sort last."""
    match = TERM_PATTERN.fullmatch((term or "").strip())
    if match is None:
        return UNKNOWN_TERM
    return (int(match[1]), SEASONS[match[2].upper()])


def clean_number(value: float):
    return int(value) if float(value).is_integer() else value


def completed_courses(history: list[dict]) -> dict[str, dict]:
    """Collapse Completed entries per course: best credits, every term it was completed."""
    courses: dict[str, dict] = {}
    for entry in history:
        if entry.get("status", "").strip().lower() != "completed":
            continue
        code = normalize_code(entry["course_code"])
        record = courses.setdefault(code, {"credits": 0, "terms": []})
        record["credits"] = max(record["credits"], entry.get("credits_earned") or 0)
        record["terms"].append(term_key(entry.get("term", "")))
    return courses


def cross_listed_codes(code: str, catalog: dict[str, dict]) -> set[str]:
    """Cross-listings from either side of the catalog, normalised."""
    linked = set()
    course = catalog.get(code)
    if course:
        linked.update(normalize_code(c) for c in course.get("cross_listed", []))
    for other_code, other in catalog.items():
        if code in {normalize_code(c) for c in other.get("cross_listed", [])}:
            linked.add(other_code)
    linked.discard(code)
    return linked


def missing_prerequisites(planned: dict, catalog: dict, completed: dict) -> list[dict]:
    course = catalog.get(normalize_code(planned["course_code"]))
    if not course:
        return []
    planned_term = term_key(planned["term"])
    errors = []
    for prereq in course.get("prerequisites", []):
        record = completed.get(normalize_code(prereq))
        done_before = record and any(term < planned_term for term in record["terms"])
        if not done_before:
            errors.append({
                "course_code": planned["course_code"],
                "type": "MISSING_PREREQUISITE",
                "message": f"Missing prerequisite: {display_code(prereq)}",
            })
    return errors


def build_audit(student_id: str, history: list[dict], plan: list[dict],
                catalog: dict[str, dict], strict: bool = False) -> dict:
    completed = completed_courses(history)

    errors_by_term: dict[str, list] = {}
    cross_list_violations = []
    for planned in plan:
        errors = missing_prerequisites(planned, catalog, completed)
        if errors:
            errors_by_term.setdefault(planned["term"].strip().upper(), []).extend(errors)
        code = normalize_code(planned["course_code"])
        for linked in sorted(cross_listed_codes(code, catalog)):
            if linked in completed:
                cross_list_violations.append({
                    "course_code": planned["course_code"],
                    "type": "CROSS_LIST_CONFLICT",
                    "message": f"Cross-listed with completed course {display_code(linked)}",
                })

    timeline = [
        {"term": term, "errors": errors_by_term[term]}
        for term in sorted(errors_by_term, key=lambda t: (term_key(t), t))
    ]

    planned_codes = {normalize_code(p["course_code"]) for p in plan}
    total_planned = sum(catalog[c]["credits"] for c in planned_codes if c in catalog)
    total_earned = sum(record["credits"] for record in completed.values())
    remaining = max(0, GRADUATION_CREDITS - total_earned - total_planned)

    if timeline or cross_list_violations:
        status = "failed" if strict else "warning"
    else:
        status = "ok"

    return {
        "student_id": student_id,
        "status": status,
        "timeline_validation": timeline,
        "cross_list_violations": cross_list_violations,
        "credit_summary": {
            "total_earned": clean_number(total_earned),
            "total_planned": clean_number(total_planned),
            "total_remaining_for_graduation": clean_number(remaining),
        },
    }
