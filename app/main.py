from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.status import HTTP_302_FOUND
import sqlite3
from pathlib import Path
from datetime import datetime

from preflight_checklist import router as preflight_router
from measurement import router as measurement_router
from measurement_analisys import router as measurement_analisys_router
from measurement_report import router as measurement_report_router

from config import STATUS_CHOICES

from db import SCHEMA_SQL

APP_ROOT = Path(__file__).parent
DATA_DIR = APP_ROOT / "data"
DB_PATH = DATA_DIR / "surveys.db"

app = FastAPI(title="Site Surveys")

app.include_router(preflight_router)
app.include_router(measurement_router)
app.include_router(measurement_analisys_router)
app.include_router(measurement_report_router)

templates = Jinja2Templates(directory=str(APP_ROOT / "templates"))
if (APP_ROOT / "static").exists():
    app.mount("/static", StaticFiles(directory=str(APP_ROOT / "static")), name="static")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    path = APP_ROOT / "static" / "favicon.ico.png"
    if not path.exists():
        raise HTTPException(status_code=404, detail="favicon not found")
    return FileResponse(path)

if not DB_PATH.exists():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.executescript(SCHEMA_SQL)

    print(f"New database created: {DB_PATH}")



def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn



def fetch_survey_or_404(survey_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM site_surveys WHERE id = ?", (survey_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Site Survey not found")
    return row

@app.get("/", response_class=HTMLResponse)
def root():
    return RedirectResponse(url="/site-surveys", status_code=HTTP_302_FOUND)

@app.get("/site-surveys", response_class=HTMLResponse)
def list_site_surveys(request: Request):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name, code, description, status, created_at, updated_at "
            "FROM site_surveys ORDER BY updated_at DESC"
        ).fetchall()
    return templates.TemplateResponse("site_surveys_list.html", {"request": request, "surveys": rows})

@app.get("/site-surveys/new", response_class=HTMLResponse)
def new_site_survey(request: Request):
    return templates.TemplateResponse(
        "site_surveys_form.html",
        {
            "request": request,
            "action": "/site-surveys",
            "method": "post",
            "title": "New Site Survey",
            "survey": None,
            "statuses": STATUS_CHOICES,
        },
    )

@app.post("/site-surveys", response_class=HTMLResponse)
def create_site_survey(
    name: str = Form(...),
    code: str = Form(""),
    description: str = Form(""),
    status: str = Form("new"),
):
    if status not in STATUS_CHOICES:
        status = "new"
    now = datetime.utcnow().isoformat(timespec="seconds")
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO site_surveys (name, code, description, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, code, description, status, now, now),
        )
        survey_id = cur.lastrowid
        conn.commit()
    return RedirectResponse(url=f"/site-surveys/{survey_id}", status_code=HTTP_302_FOUND)

@app.get("/site-surveys/{survey_id}", response_class=HTMLResponse)
def site_survey_detail(survey_id: int, request: Request):
    row = fetch_survey_or_404(survey_id)
    return templates.TemplateResponse("site_surveys_detail.html", {"request": request, "s": row})

@app.get("/site-surveys/{survey_id}/edit", response_class=HTMLResponse)
def edit_site_survey(survey_id: int, request: Request):
    row = fetch_survey_or_404(survey_id)
    return templates.TemplateResponse(
        "site_surveys_form.html",
        {
            "request": request,
            "action": f"/site-surveys/{survey_id}/edit",
            "method": "post",
            "title": f"Edit Site Survey — {row['name']}",
            "survey": row,
            "statuses": STATUS_CHOICES,
        },
    )

@app.post("/site-surveys/{survey_id}/edit", response_class=HTMLResponse)
def update_site_survey(
    survey_id: int,
    name: str = Form(...),
    code: str = Form(""),
    description: str = Form(""),
    status: str = Form("new"),
):
    _ = fetch_survey_or_404(survey_id)
    if status not in STATUS_CHOICES:
        status = "new"
    now = datetime.utcnow().isoformat(timespec="seconds")
    with get_db() as conn:
        conn.execute(
            "UPDATE site_surveys SET name=?, code=?, description=?, status=?, updated_at=? WHERE id=?",
            (name, code, description, status, now, survey_id),
        )
        conn.commit()
    return RedirectResponse(url=f"/site-surveys/{survey_id}", status_code=HTTP_302_FOUND)

@app.post("/site-surveys/{survey_id}/delete", response_class=HTMLResponse)
def delete_site_survey(survey_id: int):
    _ = fetch_survey_or_404(survey_id)
    with get_db() as conn:
        conn.execute("DELETE FROM site_surveys WHERE id=?", (survey_id,))
        conn.commit()
    return RedirectResponse(url="/site-surveys", status_code=HTTP_302_FOUND)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8808,
        reload=True
    )
