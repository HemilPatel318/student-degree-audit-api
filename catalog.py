"""Course catalog parsing and lookup."""

import math
import re

from bs4 import BeautifulSoup

CODE_PATTERN = re.compile(r"\b([A-Za-z]+)[\s-]*(\d{3,4}[A-Za-z]?)\b")
FIELDS = ("course code", "title", "credits", "prerequisites", "cross-listed")


def normalize_code(value: str) -> str:
    return re.sub(r"[\s-]+", "", value or "").upper()


def display_code(value: str) -> str:
    """COSC3127, 'cosc 3127' and 'COSC-3127' all become 'COSC-3127'."""
    code = normalize_code(value)
    match = re.fullmatch(r"([A-Z]+)(\d.*)", code)
    return f"{match[1]}-{match[2]}" if match else code


def extract_course_codes(value: str) -> list[str]:
    return list(dict.fromkeys(
        f"{subject.upper()} {number.upper()}"
        for subject, number in CODE_PATTERN.findall(value)
    ))


def cell_text(cell) -> str:
    return " ".join(cell.get_text(" ", strip=True).split())


def parse_course_row(row, columns: dict[str, int]) -> dict:
    cells = row.find_all("td", recursive=False)
    if len(cells) <= max(columns.values()):
        raise ValueError("Course row is missing required cells")
    values = {name: cell_text(cells[index]) for name, index in columns.items()}
    match = CODE_PATTERN.fullmatch(values["course code"])
    if match is None or not values["title"]:
        raise ValueError("Course row has an invalid code or empty title")
    credits = float(values["credits"])
    if not math.isfinite(credits) or credits < 0:
        raise ValueError("Course credits must be a finite nonnegative number")
    return {
        "course_code": f"{match[1].upper()} {match[2].upper()}",
        "title": values["title"],
        "credits": credits,
        "prerequisites": extract_course_codes(values["prerequisites"]),
        "cross_listed": extract_course_codes(values["cross-listed"]),
    }


def parse_catalog(contents: bytes) -> dict[str, dict]:
    soup = BeautifulSoup(contents, "html.parser")
    parsed = {}
    for table in soup.find_all("table"):
        columns = None
        for row in table.find_all("tr"):
            if row.find_parent("table") is not table:
                continue
            headers = row.find_all("th", recursive=False)
            if headers:
                labels = [cell_text(cell).casefold() for cell in headers]
                columns = ({name: labels.index(name) for name in FIELDS}
                           if all(name in labels for name in FIELDS) else None)
                continue
            if columns is None or not row.find_all("td", recursive=False):
                continue
            course = parse_course_row(row, columns)
            key = normalize_code(course["course_code"])
            if key in parsed and parsed[key] != course:
                raise ValueError("Conflicting duplicate course records")
            parsed[key] = course
    if not parsed:
        raise ValueError("No courses found in a table with the required headers")
    return parsed
