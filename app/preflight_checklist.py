# preflight_checklist.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
import sqlite3

APP_ROOT = Path(__file__).parent
DATA_DIR = APP_ROOT / "data"

TEMPLATES = Jinja2Templates(directory=str(APP_ROOT / "templates"))

CHECKLIST_PATH = DATA_DIR / "checklist_v3.json"

router = APIRouter(
    prefix="/site-surveys/{survey_id}/preflight",
    tags=["Preflight Checklist"],
)

# -------- helpers --------
def load_checklist() -> Dict[str, Any]:
    """Load the v3 checklist JSON. Raises if missing/invalid."""
    with CHECKLIST_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    # normalize: ensure each stage has 'steps'
    stages = data.get("stages") or []
    for s in stages:
        s.setdefault("steps", [])
        s.setdefault("issues", [])
        s.setdefault("refs", [])
        # ensure each step has a stable key
        for st in s["steps"]:
            # make a form-safe key like "1.3" -> "s1_3"
            st_code = str(st.get("step", "")).strip()
            safe = "s" + st_code.replace(".", "_").replace(" ", "_")
            st["_safe"] = safe
    return {"stages": stages}

def clamp_stage_index(stages: List[Dict[str, Any]], idx: int) -> int:
    if idx < 0:
        return 0
    if idx >= len(stages):
        return len(stages) - 1
    return idx

DB_PATH = DATA_DIR / "surveys.db"

def _db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def _upsert_answer(con: sqlite3.Connection, survey_id: int, step_code: str, value: str, checked: bool):
    con.execute("""
        INSERT INTO preflight_answers (survey_id, step_code, value, checked)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(survey_id, step_code) DO UPDATE SET
            value=excluded.value,
            checked=excluded.checked
    """, (survey_id, step_code, value, 1 if checked else 0))

# --- Stage completion helpers ---
def _is_stage_complete(stage: dict, answers: dict) -> bool:
    for st in stage.get("steps", []):
        code = str(st.get("step", ""))
        a = answers.get(code)
        if not a or not bool(a.get("checked")):
            return False
    return True


# -------- routes --------
@router.get("/start")
def start_checklist(request: Request, survey_id: int):
    """Convenience redirect to stage 1 (index 0)."""
    return RedirectResponse(
        url=f"/site-surveys/{survey_id}/preflight/stage/1", status_code=302
    )

@router.get("/stage/{stage_no}")
def get_stage(
    request: Request,
    survey_id: int,
    stage_no: int,
    error: Optional[str] = None,
):
    data = load_checklist()
    stages = data["stages"]
    if not stages:
        return TEMPLATES.TemplateResponse(
            "preflight/wizard_error.html",
            {"request": request, "survey_id": survey_id, "message": "Checklist template has no stages."},
        )

    idx = clamp_stage_index(stages, stage_no - 1)
    stage = stages[idx]

    # Progress counts
    progress = {
        "total": len(stages),
        "current": idx + 1,
        "items": [{"n": i + 1, "title": s.get("title", f"Stage {i+1}")} for i, s in enumerate(stages)],
    }

    # Load saved answers
    with _db() as con:
        rows = con.execute(
            "SELECT step_code, value, checked FROM preflight_answers WHERE survey_id = ?",
            (survey_id,),
        ).fetchall()
    answers = { r["step_code"]: {"value": r["value"] or "", "checked": bool(r["checked"])} for r in rows }

    # Build vertical nav: only completed stages (and the current stage) are clickable
    base = f"/site-surveys/{survey_id}/preflight/stage"
    nav = []
    for i, stg in enumerate(stages):
        complete = _is_stage_complete(stg, answers)
        current = (i == idx)
        enabled = complete or current  # only completed stages (and current) are navigable
        nav.append({
            "n": i + 1,                             # 1-based label
            "title": stg.get("title", f"Stage {i+1}"),
            "url": f"{base}/{i+1}",
            "complete": complete,
            "current": current,
            "enabled": enabled,
        })

    return TEMPLATES.TemplateResponse(
        "preflight/wizard_stage.html",
        {
            "request": request,
            "survey_id": survey_id,
            "stage": stage,
            "stage_index": idx,
            "progress": progress,
            "answers": answers,
            "nav": nav,                # <<< pass to template
            "error": error,
        },
    )

@router.post("/stage/{stage_no}")
def post_stage(request: Request,survey_id: int,stage_no: int):
    # dynamic step checkboxes will arrive as form fields named by step["_safe"]

    """
    Validate that all steps in the current stage are checked, then advance.
    Values for steps with value_type are accepted but not persisted yet.
    """
    form = request.scope.get("_form")  # not set by default; we’ll use request.form() instead
    # We can’t await here (sync def), so switch to a small helper:
    # FastAPI allows reading form in sync path via starlette’s Request
    # using request._receive is messy; instead, make endpoint async:
    return RedirectResponse(
        url=f"/site-surveys/{survey_id}/preflight/stage/{stage_no}",
        status_code=302,
    )

# Make the POST endpoint async so we can read form data cleanly
@router.post("/stage/{stage_no}/submit")
async def post_stage_submit(request: Request, survey_id: int, stage_no: int):
    data = load_checklist()
    stages = data["stages"]
    idx = clamp_stage_index(stages, stage_no - 1)
    stage = stages[idx]

    form = await request.form()

    # validate all checked
    missing = []
    for st in stage.get("steps", []):
        safe = st.get("_safe")
        if form.get(f"{safe}__chk") != "on":
            missing.append(st.get("step") or "?")

    if missing:
        progress = {
            "total": len(stages),
            "current": idx + 1,
            "items": [{"n": i + 1, "title": s.get("title", f"Stage {i+1}")} for i, s in enumerate(stages)],
        }
        return TEMPLATES.TemplateResponse(
            "preflight/wizard_stage.html",
            {
                "request": request,
                "survey_id": survey_id,
                "stage": stage,
                "stage_index": idx,
                "progress": progress,
                "error": f"All steps must be checked to continue. Missing: {', '.join(missing)}",
                "sticky": dict(form),
            },
            status_code=400,
        )

    # save answers
    with _db() as con:
        for st in stage.get("steps", []):
            code = str(st.get("step", ""))
            safe = st.get("_safe")
            val = (form.get(f"{safe}__val") or "").strip()
            _upsert_answer(con, survey_id, code, val, True)

        # if this was the final stage → bump survey status to 'measurements'
        if idx + 1 >= len(stages):
            con.execute(
                "UPDATE site_surveys SET status = 'measurements', updated_at = datetime('now') WHERE id = ?",
                (survey_id,)
            )

        con.commit()

    # last stage? show complete page
    if idx + 1 >= len(stages):
        return TEMPLATES.TemplateResponse(
            "preflight/wizard_complete.html",
            {"request": request, "survey_id": survey_id},
        )

    # otherwise → advance
    return RedirectResponse(
        url=f"/site-surveys/{survey_id}/preflight/stage/{idx+2}",
        status_code=302,
    )

@router.post("/stage/{stage_no}/check-all")
def post_check_all(survey_id: int, stage_no: int):
    data = load_checklist()
    stages = data["stages"]
    idx = clamp_stage_index(stages, stage_no - 1)
    stage = stages[idx]
    with _db() as con:
        for st in stage.get("steps", []):
            code = str(st.get("step", ""))
            _upsert_answer(con, survey_id, code, value="", checked=True)
        con.commit()
    return RedirectResponse(url=f"/site-surveys/{survey_id}/preflight/stage/{stage_no}", status_code=302)
