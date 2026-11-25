"""Student degree-audit API: catalog, academic history, plan and audit report."""

from threading import RLock

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

import auth
from audit import build_audit
from catalog import normalize_code, parse_catalog
from ratelimit import SlidingWindowLimiter
from recommend import build_pathway
from transcript import parse_transcript

app = FastAPI(title="Student Degree Audit API")
app.state.catalog = {}
app.state.students = {}
app.state.lock = RLock()
audit_limiter = SlidingWindowLimiter(limit=10, window_seconds=60)


class Credentials(BaseModel):
    username: str
    password: str


class PastCourse(BaseModel):
    course_code: str
    term: str
    credits_earned: int
    status: str


class HistoryPayload(BaseModel):
    history: list[PastCourse]


class PlannedCourse(BaseModel):
    course_code: str
    term: str


class PlanPayload(BaseModel):
    planned_courses: list[PlannedCourse]


def require_student(student_id: str) -> dict:
    student = app.state.students.get(student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    return student


@app.get("/")
def root():
    return {"message": "Student Degree Audit API is running"}


# Phase 4: authentication

@app.post("/api/v1/auth/register", status_code=201)
def register(body: Credentials):
    if not body.username.strip() or not body.password:
        raise HTTPException(status_code=422, detail="Username and password are required")
    if not auth.register_user(body.username, body.password):
        raise HTTPException(status_code=409, detail="Username already exists")
    return {"status": "registered"}


@app.post("/api/v1/auth/login")
def login(body: Credentials):
    role = auth.authenticate(body.username, body.password)
    if role is None:
        raise auth.unauthorized("Invalid username or password")
    return {"access_token": auth.create_token(body.username, role), "token_type": "bearer"}


# Phase 1: catalog

@app.post("/api/v1/admin/catalog/import")
async def import_catalog(file: UploadFile = File(...)):
    try:
        contents = await file.read()
    finally:
        await file.close()
    if not contents.strip():
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    try:
        parsed = parse_catalog(contents)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    with app.state.lock:
        app.state.catalog = parsed
    return {"message": "Catalog imported successfully", "courses_imported": len(parsed)}


@app.get("/api/v1/catalog/courses/{course_code}")
def get_course(course_code: str):
    course = app.state.catalog.get(normalize_code(course_code))
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


# Phase 2: history, plan, profile

@app.post("/api/v1/students/{student_id}/history/import", status_code=201)
async def import_history(student_id: str, file: UploadFile = File(...),
                         claims: dict = Depends(auth.current_claims)):
    auth.require_owner(student_id, claims)
    html = (await file.read()).decode("utf-8-sig", errors="replace")
    history = parse_transcript(html)
    with app.state.lock:
        student = app.state.students.setdefault(student_id, {"history": [], "plan": []})
        student["history"] = history
    return {"status": "success", "past_courses_imported": len(history)}


@app.put("/api/v1/students/{student_id}/history")
def replace_history(student_id: str, payload: HistoryPayload):
    with app.state.lock:
        require_student(student_id)["history"] = [c.model_dump() for c in payload.history]
    return {"status": "success", "message": "Academic history updated successfully"}


@app.delete("/api/v1/students/{student_id}/history")
def delete_history(student_id: str):
    with app.state.lock:
        require_student(student_id)["history"] = []
    return {"status": "success"}


def store_plan(student_id: str, payload: PlanPayload) -> dict:
    with app.state.lock:
        planned = [c.model_dump() for c in payload.planned_courses]
        require_student(student_id)["plan"] = planned
    return {"status": "success", "planned_courses_saved": len(planned)}


@app.post("/api/v1/students/{student_id}/plan")
def save_plan(student_id: str, payload: PlanPayload):
    return store_plan(student_id, payload)


@app.put("/api/v1/students/{student_id}/plan")
def replace_plan(student_id: str, payload: PlanPayload):
    return store_plan(student_id, payload)


@app.get("/api/v1/students/{student_id}/plan")
def get_plan(student_id: str, claims: dict = Depends(auth.current_claims)):
    auth.require_owner_or_admin(student_id, claims)
    with app.state.lock:
        plan = [dict(c) for c in require_student(student_id)["plan"]]
    return {"student_id": student_id, "plan": plan}


@app.delete("/api/v1/students/{student_id}/plan")
def delete_plan(student_id: str):
    with app.state.lock:
        require_student(student_id)["plan"] = []
    return {"status": "success"}


@app.get("/api/v1/students/{student_id}/profile")
def get_profile(student_id: str, claims: dict = Depends(auth.current_claims)):
    auth.require_owner_or_admin(student_id, claims)
    with app.state.lock:
        student = require_student(student_id)
        return {
            "student_id": student_id,
            "history": [dict(c) for c in student["history"]],
            "plan": [dict(c) for c in student["plan"]],
        }


# Phase 3: audit (Phase 4 adds the rate limit)

def rate_key(request: Request, claims) -> str:
    """Per JWT subject when a valid token is sent, otherwise per client IP."""
    if claims and claims.get("sub"):
        return f"user:{claims['sub']}"
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip() or (request.client.host if request.client else "")
    return f"ip:{ip}"


@app.get("/api/v1/students/{student_id}/audit-report")
def audit_report(request: Request, student_id: str, strict: bool = False,
                 claims=Depends(auth.optional_claims)):
    if not audit_limiter.allow(rate_key(request, claims)):
        raise HTTPException(status_code=429, detail="Too many requests, try again in a minute",
                            headers={"Retry-After": "60"})
    with app.state.lock:
        student = require_student(student_id)
        return build_audit(
            student_id,
            list(student["history"]),
            list(student["plan"]),
            dict(app.state.catalog),
            strict=strict,
        )


# Phase 4: recommendations

@app.get("/api/v1/students/{student_id}/recommendations")
def recommendations(student_id: str, claims: dict = Depends(auth.current_claims)):
    auth.require_owner_or_admin(student_id, claims)
    with app.state.lock:
        history = list(require_student(student_id)["history"])
        catalog = dict(app.state.catalog)
    return {"student_id": student_id, "recommended_pathway": build_pathway(history, catalog)}
