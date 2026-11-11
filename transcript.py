"""Transcript HTML parsing (Phase 2 rules, unchanged)."""

import re

from bs4 import BeautifulSoup


def grade_rank(grade: str) -> tuple[int, float]:
    grade = grade.strip().upper()
    if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)\s*%?", grade):
        return (2, float(grade.rstrip("%").strip()))
    if re.fullmatch(r"[A-F][+-]?", grade):
        return (1, 0.0)
    return (0, 0.0)


def parse_credits(value: str) -> int:
    try:
        number = float(value.strip())
        return int(number) if number >= 0 and number.is_integer() else 0
    except (ValueError, OverflowError):
        return 0


def parse_transcript(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    selected = {}
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        headers = None
        header_row_index = None
        for index, row in enumerate(rows):
            cells = row.find_all(["th", "td"], recursive=False)
            names = [" ".join(cell.stripped_strings).strip().lower() for cell in cells]
            candidates = {
                name: names.index(name) if name in names else None
                for name in ("status", "course", "grade", "term", "credits")
            }
            if all(position is not None for position in candidates.values()):
                headers = candidates
                header_row_index = index
                break
        if headers is None:
            continue
        for row in rows[header_row_index + 1:]:
            cells = row.find_all(["td", "th"], recursive=False)
            if len(cells) <= max(headers.values()):
                continue
            values = {
                name: " ".join(cells[pos].stripped_strings).strip()
                for name, pos in headers.items()
            }
            if values["status"] not in {"Completed", "In-Progress", "Attempted"}:
                continue
            if not values["term"] or not values["course"]:
                continue
            credits = parse_credits(values["credits"])
            course = {
                "course_code": values["course"],
                "term": values["term"],
                "credits_earned": credits,
                "status": values["status"],
            }
            key = (course["course_code"], course["term"])
            score = (grade_rank(values["grade"]), credits)
            if key not in selected or score > selected[key][0]:
                selected[key] = (score, course)
    return [item[1] for item in selected.values()]
