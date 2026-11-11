import pytest

from audit import build_audit, clean_number, cross_listed_codes, term_key
from catalog import display_code, extract_course_codes, normalize_code, parse_catalog
from transcript import grade_rank, parse_credits, parse_transcript


@pytest.fixture
def catalog(catalog_bytes):
    return parse_catalog(catalog_bytes)


@pytest.fixture
def history(transcript_bytes):
    return parse_transcript(transcript_bytes.decode())


def completed(code, term, credits=3):
    return {"course_code": code, "term": term, "credits_earned": credits, "status": "Completed"}


# Course codes and terms

@pytest.mark.parametrize("raw", ["COSC 3506", "COSC-3506", "cosc3506", " cosc - 3506 "])
def test_codes_compare_format_insensitively(raw):
    assert normalize_code(raw) == "COSC3506"
    assert display_code(raw) == "COSC-3506"


def test_extract_codes_handles_hyphens_and_none():
    assert extract_course_codes("COSC-2006 and MATH 1056") == ["COSC 2006", "MATH 1056"]
    assert extract_course_codes("None") == []


def test_term_order():
    terms = ["26F", "24W", "26SP", "23F", "26S", "26W"]
    assert sorted(terms, key=term_key) == ["23F", "24W", "26W", "26SP", "26S", "26F"]
    assert term_key("sp26") > term_key("99F")


def test_clean_number():
    assert clean_number(3.0) == 3 and isinstance(clean_number(3.0), int)
    assert clean_number(1.5) == 1.5


# Catalog parsing

def test_catalog_parse(catalog):
    assert set(catalog) == {"COSC1047", "COSC2006", "COSC2007", "COSC3506", "ITEC3506"}
    assert catalog["COSC3506"]["prerequisites"] == ["COSC 2007"]
    assert catalog["COSC3506"]["cross_listed"] == ["ITEC 3506"]
    assert catalog["COSC2006"]["prerequisites"] == []


def test_catalog_rejects_bad_input():
    with pytest.raises(ValueError):
        parse_catalog(b"<html><p>no tables</p></html>")
    bad_row = (b"<table><tr><th>Course Code</th><th>Title</th><th>Credits</th>"
               b"<th>Prerequisites</th><th>Cross-listed</th></tr>"
               b"<tr><td>???</td><td>X</td><td>3</td><td></td><td></td></tr></table>")
    with pytest.raises(ValueError):
        parse_catalog(bad_row)


def test_catalog_rejects_conflicting_duplicates():
    head = (b"<table><tr><th>Course Code</th><th>Title</th><th>Credits</th>"
            b"<th>Prerequisites</th><th>Cross-listed</th></tr>")
    rows = (b"<tr><td>COSC 1000</td><td>A</td><td>3</td><td></td><td></td></tr>"
            b"<tr><td>COSC-1000</td><td>B</td><td>3</td><td></td><td></td></tr></table>")
    with pytest.raises(ValueError):
        parse_catalog(head + rows)


def test_catalog_rejects_short_rows_and_negative_credits():
    head = (b"<table><tr><th>Course Code</th><th>Title</th><th>Credits</th>"
            b"<th>Prerequisites</th><th>Cross-listed</th></tr>")
    with pytest.raises(ValueError):
        parse_catalog(head + b"<tr><td>COSC 1000</td><td>A</td></tr></table>")
    negative = b"<tr><td>COSC 1000</td><td>A</td><td>-3</td><td></td><td></td></tr></table>"
    with pytest.raises(ValueError):
        parse_catalog(head + negative)


# Transcript parsing

def test_transcript_parse(history):
    statuses = {(c["course_code"], c["term"]): c["status"] for c in history}
    assert statuses[("COSC-2006", "24W")] == "Attempted"
    assert statuses[("COSC-2006", "24F")] == "Completed"
    assert all(c["status"] != "Fulfilled" for c in history)
    lab_dedup = [c for c in history if c["course_code"] == "COSC-2006" and c["term"] == "24F"]
    assert lab_dedup == [completed("COSC-2006", "24F")]


def test_grade_and_credit_helpers():
    assert grade_rank("85") > grade_rank("A+") > grade_rank("P")
    assert parse_credits("3") == 3
    assert parse_credits("abc") == 0
    assert parse_credits("1.5") == 0


# Audit rules

def test_prerequisite_must_be_completed_in_an_earlier_term(catalog):
    hist = [completed("COSC-2007", "26F")]
    plan = [{"course_code": "COSC-3506", "term": "26F"}]
    report = build_audit("1", hist, plan, catalog)
    assert report["timeline_validation"] == [{
        "term": "26F",
        "errors": [{
            "course_code": "COSC-3506",
            "type": "MISSING_PREREQUISITE",
            "message": "Missing prerequisite: COSC-2007",
        }],
    }]
    ok = build_audit("1", [completed("COSC 2007", "26S")], plan, catalog)
    assert ok["timeline_validation"] == []


def test_in_progress_does_not_satisfy_prerequisite(catalog):
    hist = [{"course_code": "COSC-2006", "term": "24F", "credits_earned": 3,
             "status": "In-Progress"}]
    plan = [{"course_code": "COSC2007", "term": "26W"}]
    assert build_audit("1", hist, plan, catalog)["status"] == "warning"


def test_timeline_is_chronological(catalog):
    plan = [
        {"course_code": "COSC-3506", "term": "27F"},
        {"course_code": "COSC-2007", "term": "26SP"},
        {"course_code": "ITEC-3506", "term": "26W"},
    ]
    report = build_audit("1", [], plan, catalog)
    assert [t["term"] for t in report["timeline_validation"]] == ["26W", "26SP", "27F"]


def test_cross_list_conflict_both_directions(catalog):
    hist = [completed("COSC-3506", "25F")]
    report = build_audit("1", hist, [{"course_code": "ITEC-3506", "term": "26W"}], catalog)
    assert report["cross_list_violations"] == [{
        "course_code": "ITEC-3506",
        "type": "CROSS_LIST_CONFLICT",
        "message": "Cross-listed with completed course COSC-3506",
    }]
    one_sided = {k: dict(v) for k, v in catalog.items()}
    one_sided["COSC3506"]["cross_listed"] = []
    assert cross_listed_codes("COSC3506", one_sided) == {"ITEC3506"}


def test_retakes_are_not_double_counted(catalog):
    hist = [
        {"course_code": "COSC-2006", "term": "24W", "credits_earned": 0, "status": "Attempted"},
        completed("COSC-2006", "24F"),
        completed("COSC 2006", "25W"),
        completed("COSC-1047", "23F", 0),
        completed("COSC-1047", "24W"),
    ]
    summary = build_audit("1", hist, [], catalog)["credit_summary"]
    assert summary["total_earned"] == 6


def test_credit_summary(catalog):
    hist = [completed("COSC-1047", "23F"), completed("COSC-2006", "23F")]
    plan = [
        {"course_code": "COSC-2007", "term": "24W"},
        {"course_code": "COSC 2007", "term": "24F"},
        {"course_code": "MATH-9999", "term": "24F"},
    ]
    summary = build_audit("1", hist, plan, catalog)["credit_summary"]
    assert summary == {"total_earned": 6, "total_planned": 3,
                       "total_remaining_for_graduation": 111}
    big = [completed(f"ZZZZ-{n:04d}", "23F", 10) for n in range(13)]
    capped = build_audit("1", big, [], catalog)["credit_summary"]
    assert capped["total_remaining_for_graduation"] == 0


def test_status_and_strict(catalog, history):
    plan = [{"course_code": "COSC-3506", "term": "26F"}]
    assert build_audit("1", history, plan, catalog)["status"] == "warning"
    assert build_audit("1", history, plan, catalog, strict=True)["status"] == "failed"
    clean = build_audit("1", history, [{"course_code": "COSC-2007", "term": "26F"}], catalog,
                        strict=True)
    assert clean["status"] == "ok"
    assert clean["timeline_validation"] == [] and clean["cross_list_violations"] == []
