"""Graduation pathway: Kahn's topological sort over the catalog prerequisite DAG."""

from datetime import date

from audit import TERM_PATTERN, completed_courses, term_key
from catalog import normalize_code


def next_term(term: str) -> str:
    """Regular academic terms only: 26F -> 27W -> 27F -> 28W ..."""
    year, season = int(term[:2]), term[2:]
    return f"{year + 1:02d}W" if season == "F" else f"{year:02d}F"


def first_term(history: list[dict], today: date | None = None) -> str:
    """The term after the student's latest recorded one, else the current term."""
    terms = [t for t in (e.get("term", "").strip().upper() for e in history)
             if TERM_PATTERN.fullmatch(t)]
    if terms:
        latest = max(terms, key=term_key)
        year, season = int(latest[:2]), latest[2:]
        if season != "F":
            return f"{year:02d}F"
        return next_term(latest)
    today = today or date.today()
    season = "W" if today.month <= 4 else "F"
    return f"{today.year % 100:02d}{season}"


def build_pathway(history: list[dict], catalog: dict[str, dict],
                  today: date | None = None) -> list[dict]:
    done = set(completed_courses(history))
    remaining = {code: course for code, course in catalog.items() if code not in done}

    # Edges only between remaining courses. A prerequisite that is completed is
    # already satisfied; one outside the catalog cannot be scheduled, so it is ignored.
    indegree = {code: 0 for code in remaining}
    dependents: dict[str, list[str]] = {code: [] for code in remaining}
    for code, course in remaining.items():
        for prereq in {normalize_code(p) for p in course.get("prerequisites", [])}:
            if prereq in remaining and prereq != code:
                dependents[prereq].append(code)
                indegree[code] += 1

    pathway = []
    term = first_term(history, today)
    level = sorted(code for code, degree in indegree.items() if degree == 0)
    while level:
        pathway.append({"term": term,
                        "courses": [remaining[code]["course_code"] for code in level]})
        unlocked = []
        for code in level:
            for child in dependents[code]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    unlocked.append(child)
        level = sorted(unlocked)
        term = next_term(term)
    # Courses caught in a prerequisite cycle never reach indegree 0 and are left out.
    return pathway
