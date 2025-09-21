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





def _load_embed_asset(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _data_uri(content: Optional[bytes], mime: Optional[str]) -> str:
    if not content or not mime:
        return ""
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _text_data_uri(text: Optional[str]) -> str:
    data = (text or "").encode("utf-8")
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:text/plain;base64,{encoded}"

# ---- Static THR (validation parameters)
THR = {
    "pss": {"g":  1.5, "w":  2.0, "p":  5.0}, # Project Set Scatter (µGal)
    "tu":  {"g": 11.0, "w": 12.0, "p": 13.0}, # Total Uncertainty (µGal)
    "ups": {"g": 15.0, "w": 20.0, "p": 65.0}, # Uncertainty / Set (µGal)
    "ss":  {"g": 50.0, "w": 60.0, "p": 70.0}, # Set Scatter (µGal)
    "ssov":{"g":  5.0, "w":  7.0, "p": 10.0}, # Set Scatter overall (µGal)
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
    static_report_dir = APP_ROOT / "static" / "report"
    header_html = _load_embed_asset(static_report_dir / "header.html")
    footer_html = _load_embed_asset(static_report_dir / "footer.html")

    with _db() as con:
        survey = con.execute("SELECT * FROM site_surveys WHERE id=?", (survey_id,)).fetchone()
        if not survey:
            raise HTTPException(status_code=404, detail="Site Survey not found")
        measurement = con.execute(
            "SELECT * FROM measurements WHERE id=? AND survey_id=?",
            (measurement_id, survey_id),
        ).fetchone()
        if not measurement:
            raise HTTPException(status_code=404, detail="Measurement not found")

        survey_dict = dict(survey)
        measurement_dict = dict(measurement)

        project_row = con.execute(
            "SELECT filename, raw_text, meta_json, imported_at FROM measurement_project WHERE measurement_id=?",
            (measurement_id,),
        ).fetchone()
        set_row = con.execute(
            "SELECT filename, raw_text, meta_json, imported_at FROM measurement_set WHERE measurement_id=?",
            (measurement_id,),
        ).fetchone()
        image_rows = con.execute(
            "SELECT filename, mime_type, caption, imported_at, image_blob FROM measurement_images WHERE measurement_id=? ORDER BY id ASC",
            (measurement_id,),
        ).fetchall()
        graph_rows = con.execute(
            "SELECT filename, mime_type, note, imported_at, graph_blob FROM measurement_graphs WHERE measurement_id=? ORDER BY id ASC",
            (measurement_id,),
        ).fetchall()

    project_meta = _load_json(project_row["meta_json"]) if project_row else {}
    set_meta = _load_json(set_row["meta_json"]) if set_row else {}

    site = project_meta.get("site", {}) if project_meta else {}
    keys = project_meta.get("keys", {}) if project_meta else {}
    qm = project_meta.get("qm", {}) if project_meta else {}

    def _parse_float(value: Any) -> Optional[float]:
        import re
        if value is None:
            return None
        text = str(value).replace(",", ".")
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        return float(match.group(0)) if match else None

    def _metric(name: str, label: str, unit: str = "µGal") -> Dict[str, Any]:
        value = _parse_float(qm.get(name))
        threshold_map = {
            "project_set_scatter": THR.get("pss", {}),
            "total_uncertainty":   THR.get("tu", {}),
            "set_scatter_overall": THR.get("ssov", {}),
            "uncertainty_per_set": THR.get("ups", {}),
        }
        thresholds = threshold_map.get(name, {})
        status = "unknown"
        if value is not None and thresholds:
            good = thresholds.get("g")
            warn = thresholds.get("w")
            if good is not None and value <= good:
                status = "good"
            elif warn is not None and value <= warn:
                status = "warn"
            else:
                status = "poor"
        return {
            "label": label,
            "value": value,
            "unit": unit if value is not None else "",
            "status": status,
            "thresholds": thresholds,
        }

    metrics = [
        _metric("project_set_scatter", "Project Set Scatter (Measurement Precision)"),
        _metric("total_uncertainty", "Total Uncertainty"),
        _metric("set_scatter_overall", "Set Scatter (overall)"),
        # _metric("uncertainty_per_set", "Uncertainty / Set"),
    ]
    gravity_value = site.get("Gravity (µGal)") or site.get("Gravity (?Gal)") or site.get("Gravity (uGal)")

    metrics.append({
        "label": "Gravity",
        "value": _parse_float(gravity_value),
        "unit": "µGal",
        "status": "info",
        "thresholds": {},
    })

    summary_items = [
        ("Survey", survey_dict.get("name")),
        ("Survey Code", survey_dict.get("code")),
        ("Measurement", measurement_dict.get("title")),
        ("Measurement ID", measurement_dict.get("id")),
        ("Created", measurement_dict.get("created_at")),
        ("Status", survey_dict.get("status")),
        ("Note", measurement_dict.get("note")),
    ]

    site_fields = [
        ("Project Name", "Project Name"),
        ("Station / Site Name", "Station / Site Name"),
        ("Site Code", "Site Code"),
        ("Latitude", "Latitude (dd,+N)"),
        ("Longitude", "Longitude (dd, +E)"),
        ("Elevation (m)", "Elevation (m)"),
        ("Gradient (uGal/cm)", "Gradient (µGal/cm)"),
        ("Setup Height (cm)", "Setup Height (cm)"),
        ("Transfer Height (cm)", "Transfer Height (cm)"),
        ("Factory Height (cm)", "Factory Height (cm)"),
        ("Instrument", "Instrument"),
        ("Instrument S/N", "Instrument S/N"),
        ("Acquisition Version", "Acquisition Version"),
        ("Processing Version", "Processing Version"),
        ("Processing Date", "Processing Date"),
        ("Processing Time", "Processing Time"),
    ]
    site_details = [(label, site.get(key) or site.get(key.replace("?", "u")) or "-" ) for label, key in site_fields]

    key_fields = [
        ("Number of Sets", "Number of Sets"),
        ("Number of Drops", "Number of Drops"),
        ("Sets Processed", "Set #s Processed"),
        ("Sets Ignored", "Number of Sets NOT Processed"),
        ("Drops Accepted", "Total Drops Accepted"),
        ("Drops Rejected", "Total Drops Rejected"),
        ("Fringes Acquired", "Total Fringes Acquired"),
        ("Fringe Start", "Fringe Start"),
        ("Processed Fringes", "Processed Fringes"),
        ("TDC Fringe Divider", "TDC Fringe Divider"),
    ]
    totals_details = [(label, keys.get(src) or "-") for label, src in key_fields]

    set_rows = set_meta.get("rows", []) if set_meta else []

    image_entries = []
    for row in image_rows:
        data_url = _data_uri(row["image_blob"], row["mime_type"])
        if not data_url:
            continue
        image_entries.append({
            "filename": row["filename"],
            "data_url": data_url,
            "caption": row["caption"] or "",
            "imported_at": row["imported_at"],
        })
    primary_image = image_entries[0] if image_entries else None
    gallery_images = image_entries[1:] if len(image_entries) > 1 else []

    graph_images = []
    graph_docs = []
    for row in graph_rows:
        data_url = _data_uri(row["graph_blob"], row["mime_type"])
        if row["mime_type"] and row["mime_type"].startswith("image/"):
            if data_url:
                graph_images.append({
                    "filename": row["filename"],
                    "data_url": data_url,
                    "note": row["note"] or "",
                    "imported_at": row["imported_at"],
                })
        else:
            if data_url:
                graph_docs.append({
                    "filename": row["filename"],
                    "data_url": data_url,
                    "note": row["note"] or "",
                    "imported_at": row["imported_at"],
                })

    project_attachment = None
    if project_row:
        project_attachment = {
            "label": "g9 Project",
            "filename": project_row["filename"],
            "download_url": _text_data_uri(project_row["raw_text"]),
            "imported_at": project_row["imported_at"],
        }

    set_attachment = None
    if set_row:
        set_attachment = {
            "label": "g9 Set",
            "filename": set_row["filename"],
            "download_url": _text_data_uri(set_row["raw_text"]),
            "imported_at": set_row["imported_at"],
        }

    attachments = [a for a in [project_attachment, set_attachment] if a]

    checklist_rows = _collect_checklist_answers(survey_id)
    stages = []
    from collections import OrderedDict
    grouped = OrderedDict()
    for row in checklist_rows:
        grouped.setdefault(row["stage_title"], []).append(row)
    for title, items in grouped.items():
        stages.append({
            "title": title,
            "entries": items,
        })

    context = {
        "request": request,
        "generated_at": _now_iso(),
        "survey": survey_dict,
        "measurement": measurement_dict,
        "summary_items": summary_items,
        "metrics": metrics,
        "site_details": site_details,
        "totals_details": totals_details,
        "set_rows": set_rows,
        "primary_image": primary_image,
        "gallery_images": gallery_images,
        "graph_images": graph_images,
        "graph_docs": graph_docs,
        "attachments": attachments,
        "checklist_stages": stages,
        "header_html": header_html,
        "footer_html": footer_html,
    }

    return TEMPLATES.TemplateResponse("measurement_report_print.html", context)
