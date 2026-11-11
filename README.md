# Student Degree Audit API

FastAPI service that ingests a course catalog and a student transcript, stores a
course plan, and audits that plan against the program rules.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/admin/catalog/import` | Upload catalog HTML |
| GET | `/api/v1/catalog/courses/{course_code}` | Look up one course |
| POST | `/api/v1/students/{id}/history/import` | Upload transcript HTML (creates the student) |
| PUT / DELETE | `/api/v1/students/{id}/history` | Replace or clear history |
| POST / PUT / DELETE | `/api/v1/students/{id}/plan` | Save, replace or clear the plan |
| GET | `/api/v1/students/{id}/profile` | History and plan |
| GET | `/api/v1/students/{id}/audit-report?strict=<bool>` | Degree audit |

## Audit rules

- Course codes match after upper-casing and removing spaces and hyphens.
- Terms sort by year, then season: `W < SP < S < F`.
- Each prerequisite of a planned course needs a `Completed` entry in a strictly
  earlier term, otherwise a `MISSING_PREREQUISITE` error is reported under the
  planned term. Terms in `timeline_validation` are in chronological order.
- Planning a course that is cross-listed (from either side of the catalog) with
  a completed course gives a `CROSS_LIST_CONFLICT`.
- `total_earned` counts each completed course once, using its best
  `credits_earned`. Non-completed attempts add nothing.
- `total_planned` sums catalog credits for distinct planned courses.
  `total_remaining_for_graduation = max(0, 120 - earned - planned)`.
- `status` is `ok` with no issues, otherwise `warning`, or `failed` when
  `strict=true`.

Data lives in memory, so a restart clears it. Run a single worker.

## Running locally

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

Checks:

```bash
flake8 .
pytest --cov=. --cov-report=term-missing --cov-fail-under=80
python scripts/run_integration.py http://127.0.0.1:8000   # server must be running
```

## CI

`.github/workflows/ci.yml` runs on every push: flake8, pytest with an 80%
coverage gate, then boots the API with uvicorn and runs the integration script
against it.

## Deploying on Render

Create a Python web service from this repository (or use `render.yaml`):

- Build: `pip install -r requirements.txt`
- Start: `uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1`
