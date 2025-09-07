# measurement_report.py
from __future__ import annotations
from pathlib import Path
from typing import Optional, List, Dict, Any
import sqlite3, base64, json, datetime

from fastapi import APIRouter, Request, HTTPException
from fastapi.templating import Jinja2Templates

APP_ROOT = Path(__file__).parent
DATA_DIR = APP_ROOT / "data"
DB_PATH = DATA_DIR / "surveys.db"
CHECKLIST_PATH = DATA_DIR / "checklist_v3.json"

TEMPLATES = Jinja2Templates(directory=str(APP_ROOT / "templates"))

router = APIRouter(
    prefix="/site-surveys/{survey_id}/measurements/{measurement_id}/report",
    tags=["Measurement Report"],
)

# Static thresholds
THR = {
    "pss": {"g":  1.5, "w":  2.0, "p":  3.0}, # Project Set Scatter (µGal)
    "tu":  {"g": 11.0, "w": 12.0, "p": 13.0}, # Total Uncertainty (µGal)
    "ups": {"g": 15.0, "w": 20.0, "p": 65.0}, # Uncertainty / Set (µGal)
    "ss":  {"g": 50.0, "w": 60.0, "p": 70.0}, # Set Scatter (µGal)
    "ssov":{"g":  3.0, "w":  4.0, "p": 10.0}, # Set Scatter overall (µGal)
    "acc": {"g": 95.0, "w": 85.0, "p": 75.0}, # Acceptance (%)
}

def _db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def _load_json(text: Optional[str]) -> Dict[str, Any]:
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        return {}

def _data_url(content: bytes, mime: Optional[str]) -> Optional[str]:
    if not content:
        return None
    if not mime:
        return None
    # Only embed images (png/jpg/webp/gif/tiff/bmp)
    if not mime.startswith("image/"):
        return None
    b64 = base64.b64encode(content).decode("ascii")
    return f"data:{mime};base64,{b64}"

def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")

def _load_checklist_template() -> Dict[str, Any]:
    with CHECKLIST_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if "stages" not in data or not isinstance(data["stages"], list):
        return {"stages": []}
    # normalize step codes to strings
    for stg in data["stages"]:
        for st in stg.get("steps", []):
            st["step"] = str(st.get("step", ""))
    return data

def _collect_checklist_answers(survey_id: int) -> List[Dict[str, Any]]:
    """
    Returns a list of rows to render in the report table:
      [{ "stage_index": int, "stage_title": str, "step": "1.2",
         "action": str, "expected": str, "value": str }, ...]
    Only includes answers with a non-empty value.
    """
    tpl = _load_checklist_template()
    steps_map: Dict[str, Dict[str, Any]] = {}
    for i, stg in enumerate(tpl["stages"]):
        for st in stg.get("steps", []):
            steps_map[st["step"]] = {
                "stage_index": i,
                "stage_title": stg.get("title", f"Stage {i}"),
                "step": st["step"],
                "action": st.get("action", ""),
                "expected": st.get("expected", ""),
            }

    with _db() as con:
        rows = con.execute(
            "SELECT step_code, value FROM preflight_answers WHERE survey_id=?",
            (survey_id,),
        ).fetchall()

    out: List[Dict[str, Any]] = []
    for r in rows:
        code = str(r["step_code"])
        val = (r["value"] or "").strip()
        if not val:
            continue
        meta = steps_map.get(code)
        if not meta:
            continue
        out.append({
            **meta,
            "value": val,
        })

    # sort by stage then by step code (numeric-aware-ish)
    def _key(rec: Dict[str, Any]):
        def _num(s: str):
            try:
                return float(s)
            except Exception:
                return 1e9
        return (rec["stage_index"], _num(rec["step"]))
    out.sort(key=_key)
    return out

@router.get("")
def render_report(request: Request, survey_id: int, measurement_id: int):
    with _db() as con:
        m = con.execute("SELECT * FROM measurements WHERE id=? AND survey_id=?",
                        (measurement_id, survey_id)).fetchone()
        if not m:
            raise HTTPException(status_code=404, detail="Measurement not found")

        g9p = con.execute("SELECT * FROM measurement_project WHERE measurement_id=?",
                          (measurement_id,)).fetchone()
        g9s = con.execute("SELECT * FROM measurement_set WHERE measurement_id=?",
                          (measurement_id,)).fetchone()

        imgs = con.execute(
            "SELECT filename, mime_type, image_blob FROM measurement_images WHERE measurement_id=? ORDER BY id ASC",
            (measurement_id,)
        ).fetchall()
        graphs = con.execute(
            "SELECT filename, mime_type, graph_blob FROM measurement_graphs WHERE measurement_id=? ORDER BY id ASC",
            (measurement_id,)
        ).fetchall()

    # Parse meta JSON (done in Python, not in Jinja)
    g9p_meta = _load_json(g9p["meta_json"]) if g9p else {}
    g9s_meta = _load_json(g9s["meta_json"]) if g9s else {}

    # Build general section from g9 project 'site' block
    keys = g9p_meta.get("keys", {}) if g9p_meta else {}
    site = g9p_meta.get("site", {}) if g9p_meta else {}
    qm   = g9p_meta.get("qm",   {}) if g9p_meta else {}


    # One primary site image (first) + list of images (all embedded)
    embedded_images: List[Dict[str, str]] = []
    for r in imgs or []:
        url = _data_url(r["image_blob"], r["mime_type"])
        if url:
            embedded_images.append({"filename": r["filename"], "data_url": url})

    # Graphs: embed only images; PDFs stay as links
    embedded_graphs: List[Dict[str, str]] = []
    linked_pdfs: List[Dict[str, str]] = []
    for r in graphs or []:
        if r["mime_type"] and r["mime_type"].startswith("image/"):
            url = _data_url(r["graph_blob"], r["mime_type"])
            if url:
                embedded_graphs.append({"filename": r["filename"], "data_url": url})
        else:
            # for PDFs, we cannot embed as <img>; leave to main app streaming URL
            linked_pdfs.append({"filename": r["filename"]})

    # Checklist answers (value-only rows)
    checklist_rows = _collect_checklist_answers(survey_id)

    print(keys)
    print(site)
    print(qm)

    ctx = {
        "request": request,
        "generated_at": _now_iso(),
        "survey_id": survey_id,
        "measurement": dict(m),
        "files": {
            "project": g9p["filename"] if g9p else None,
            "set": g9s["filename"] if g9s else None,
        },
        "keys": keys,
        "site": site,
        "qm": qm,
        "thr": THR,
        "sets": g9s_meta.get("rows", []) if g9s_meta else [],
        "images": embedded_images,
        "graphs": embedded_graphs,
        "pdfs": linked_pdfs,  # listed by filename only
        "checklist": checklist_rows,
    }
    return TEMPLATES.TemplateResponse("measurement_report.html", ctx)
