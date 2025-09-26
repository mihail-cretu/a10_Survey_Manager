# measurement.py
from __future__ import annotations
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
import sqlite3, json, hashlib, datetime, re

from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException, status
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from config import THR, THR_desc, PREFERRED_ENCODINGS, KV_RE

# ---- Paths (aligned with your project layout)
APP_ROOT = Path(__file__).parent
DATA_DIR = APP_ROOT / "data"
DB_PATH = DATA_DIR / "surveys.db"
TEMPLATES = Jinja2Templates(directory=str(APP_ROOT / "templates"))

TEMPLATES.env.filters["loadjson"] = json.loads

router = APIRouter(
    prefix="/site-surveys/{survey_id}/measurements",
    tags=["Measurements"],
)

# ---- DB helpers
def _db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")

def _sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def _decode_text(data: bytes) -> str:
    for encoding in PREFERRED_ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")

def init_measurement_tables():
    with _db() as con:
        cur = con.cursor()
        # measurement header
        cur.execute("""
        CREATE TABLE IF NOT EXISTS measurements (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          survey_id INTEGER NOT NULL,
          title TEXT NOT NULL,
          note TEXT,
          created_at TEXT NOT NULL
        )""")
        # g9 project (one per measurement)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS measurement_project (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          measurement_id INTEGER NOT NULL,
          filename TEXT NOT NULL,
          raw_text TEXT NOT NULL,
          meta_json TEXT NOT NULL,
          imported_at TEXT NOT NULL,
          UNIQUE(measurement_id),
          FOREIGN KEY(measurement_id) REFERENCES measurements(id) ON DELETE CASCADE
        )""")
        # g9 set (one per measurement)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS measurement_set (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          measurement_id INTEGER NOT NULL,
          filename TEXT NOT NULL,
          raw_text TEXT NOT NULL,
          meta_json TEXT NOT NULL,
          imported_at TEXT NOT NULL,
          UNIQUE(measurement_id),
          FOREIGN KEY(measurement_id) REFERENCES measurements(id) ON DELETE CASCADE
        )""")
        # site images (many)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS measurement_images (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          measurement_id INTEGER NOT NULL,
          filename TEXT NOT NULL,
          mime_type TEXT,
          size_bytes INTEGER,
          sha256_hex TEXT,
          caption TEXT,
          imported_at TEXT NOT NULL,
          image_blob BLOB NOT NULL,
          FOREIGN KEY(measurement_id) REFERENCES measurements(id) ON DELETE CASCADE
        )""")
        # g9 graphs (many; images or PDF)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS measurement_graphs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          measurement_id INTEGER NOT NULL,
          filename TEXT NOT NULL,
          mime_type TEXT,
          size_bytes INTEGER,
          sha256_hex TEXT,
          note TEXT,
          imported_at TEXT NOT NULL,
          graph_blob BLOB NOT NULL,
          FOREIGN KEY(measurement_id) REFERENCES measurements(id) ON DELETE CASCADE
        )""")
        # site files (general attachments)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS site_files (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          measurement_id INTEGER NOT NULL,
          filename TEXT NOT NULL,
          mime_type TEXT,
          size_bytes INTEGER,
          sha256_hex TEXT,
          note TEXT,
          imported_at TEXT NOT NULL,
          file_blob BLOB NOT NULL,
          FOREIGN KEY(measurement_id) REFERENCES measurements(id) ON DELETE CASCADE
        )""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_site_files_measurement ON site_files(measurement_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_site_files_sha256 ON site_files(sha256_hex)")
        con.commit()

# init_measurement_tables()

# ---- Parsing (tolerant)

def parse_project_text(text: str) -> Dict[str, Any]:
    """
    Tolerant Key: Value parser for *.project.txt.
    Returns:
      {
        "keys": {...},      # raw KV map
        "site": {...},      # normalized selection
        "qm": {...}         # quality metrics (floats if found)
      }
    """
    keys: Dict[str, str] = {}
    for line in text.splitlines():
        m = KV_RE.match(line.strip("\n"))
        if m:
            k = m.group(1).strip()
            v = m.group(2).strip()
            if k not in keys:
                keys[k] = v

    def latlon_split(text: Optional[str]):
        if not text:
            return "", "", ""
        pattern = r"^([\d.+-]+)\s+Long:\s+([\d.+-]+)\s+Elev:\s+([\d.+-]+)"
        match = re.search(pattern, text)
        if not match:
            return text, "", ""
        lat, lon, elev = match.groups()
        return lat, lon, elev

    def pick(*names):
        for n in names:
            if n in keys and str(keys[n]).strip():
                return keys[n]
        return ""

    def nfloat(s: Optional[str]) -> Optional[float]:
        if s is None: return None
        t = str(s).replace(",", ".")
        m = re.search(r"-?\d+(?:\.\d+)?", t)
        return float(m.group(0)) if m else None

    lat, lon, elev = latlon_split(pick("Latitude (dd,+N)", "Lat", "Latitude"))

    site = {
        "Project Name": pick("Project Name"),
        "Station / Site Name": pick("Site Name", "Name"),
        "Site Code": pick("Site Code"),
        "Latitude (dd,+N)": lat,
        "Longitude (dd, +E)": lon,
        "Elevation (m)": elev,
        "Gradient (µGal/cm)": pick("Gradient"),
        "Setup Height (cm)": pick("Setup Height (cm)", "Setup Height"),
        "Transfer Height (cm)": pick("Transfer Height (cm)", "Transfer Height"),
        "Factory Height (cm)": pick("Factory Height (cm)", "Factory Height"),
        "Barometer Factor (µGal/mBar)": pick("Barometer Factor (µGal/mBar)", "Barometric Admittance Factor"),
        "Polar X (arc sec)": pick("Polar X (arc sec)", "Polar X"),
        "Polar Y (arc sec)": pick("Polar Y (arc sec)", "Polar Y"),
        "Operator": pick("Operator"),
        "Instrument": pick("Meter Type", "Instrument"),
        "Instrument S/N": pick("Meter S/N", "Serial"),
        "Acquisition Version": pick("g Acquisition Version"),
        "Processing Version": pick("g Processing Version"),
        "Processing Date": pick("Date"),
        "Processing Time": pick("Time"),
        "Gravity (µGal)": pick("Gravity (µGal)", "Gravity"),
    }

    qm = {
        "project_set_scatter": nfloat(pick("Project Set Scatter (µGal)", "Measurement Precision", "Project Set Scatter")),
        "set_scatter_overall": nfloat(pick("Set Scatter (µGal)", "Set Scatter")),
        "uncertainty_per_set": nfloat(pick("Uncertainty per Set (µGal)", "Uncertainty per Set")),
        "total_uncertainty":   nfloat(pick("Total Uncertainty", "Overall Uncertainty")),
        "gravity":             pick("Gravity (µGal)", "Gravity") or None,
    }

    return {"keys": keys, "site": site, "qm": qm}

def parse_sets_text(text: str) -> Dict[str, Any]:
    """
    Tolerant parser for *.set.txt exported by g9.
    Assumes header row around line 4 (tab-delimited), but tolerates variants.
    Returns: {"rows": [ {id, set_scatter, set_sigma, drop_rms, drop_accept}, ... ]}
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 5:
        return {"rows": []}

    # detect header line: choose the first line that contains keywords
    hdr_idx = None
    for i, ln in enumerate(lines[:10]):
        if ("Set" in ln and "\t" in ln) or ("Set" in ln and "," in ln):
            hdr_idx = i
            break
    if hdr_idx is None:
        hdr_idx = 3 if len(lines) > 4 else 0

    sep = "\t" if ("\t" in lines[hdr_idx]) else ","
    hdr = [c.strip() for c in lines[hdr_idx].split(sep)]

    def col(name: str) -> int:
        try:
            return hdr.index(name)
        except ValueError:
            return -1

    idx = {
        "set": col("Set"),
        "scatter": col("Sigma") if "Sigma" in hdr else col("Set Scatter"),
        "sigma": col("Error"),
        "rms": col("Uncert"),
        "acc": col("Accept"),
        "rej": col("Reject"),
    }

    def nfloat(s: Optional[str]) -> Optional[float]:
        if s is None:
            return None
        t = str(s).replace(",", ".")
        m = re.search(r"-?\d+(?:\.\d+)?", t)
        return float(m.group(0)) if m else None

    rows = []
    for ln in lines[hdr_idx+1:]:
        cols = [c.strip() for c in ln.split(sep)]
        if len(cols) < 2: continue
        def get(i):
            if i is None or i < 0:
                return ""
            return cols[i] if 0 <= i < len(cols) else ""
        acc_val = nfloat(get(idx["acc"]))
        rej_val = nfloat(get(idx["rej"]))
        ratio = None
        if acc_val is not None and rej_val is not None:
            total = acc_val + rej_val
            if total > 0:
                ratio = round((acc_val * 100.0) / total, 1)
        rows.append({
            "id": get(idx["set"]) or str(len(rows)+1),
            "set_scatter": nfloat(get(idx["scatter"])),
            "set_sigma": nfloat(get(idx["sigma"])),
            "drop_rms": nfloat(get(idx["rms"])),
            "drop_accept": acc_val,
            "drop_reject": rej_val,
            "drop_acc_ratio": ratio,
        })
    return {"rows": rows}

# ---- CRUD helpers (minimal)

def _ensure_survey_exists(survey_id: int):
    with _db() as con:
        row = con.execute("SELECT id FROM site_surveys WHERE id=?", (survey_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Site Survey not found")


def _get_survey(survey_id: int):
    with _db() as con:
        row = con.execute("SELECT * FROM site_surveys WHERE id=?", (survey_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Site Survey not found")
    return row

def _get_measurement(measurement_id: int):
    with _db() as con:
        row = con.execute("SELECT * FROM measurements WHERE id=?", (measurement_id,)).fetchone()
        return row

# ---- Routes


@router.get("")
def list_measurements(request: Request, survey_id: int):
    survey_row = _get_survey(survey_id)
    with _db() as con:
        rows = con.execute(
            """
            SELECT m.*,
                   mp.meta_json AS project_meta
            FROM measurements m
            LEFT JOIN measurement_project mp ON mp.measurement_id = m.id
            WHERE m.survey_id = ?
            ORDER BY m.title ASC
            """,
            (survey_id,),
        ).fetchall()

    def safe_load(s):
        try:
            return json.loads(s) if s else {}
        except Exception:
            return {}

    def nfloat(x):
        if x is None:
            return None
        t = str(x).replace(",", ".")
        import re as _re
        match = _re.search(r"-?\d+(?:\.\d+)?", t)
        return float(match.group(0)) if match else None

    def nint(x):
        f = nfloat(x)
        return int(round(f)) if f is not None else None

    STATUS_LADDER = [
        ("g", "good"),
        ("w", "warn"),
        ("p", "poor"),
        ("b", "bad"),
    ]

    def classify_threshold(value: Optional[float], thresholds: Dict[str, float], higher_is_better: bool = False) -> Optional[str]:
        if value is None or not thresholds:
            return None

        if higher_is_better:
            for key, label in STATUS_LADDER:
                limit = thresholds.get(key)
                if limit is None:
                    continue
                if value >= limit:
                    return label
            lower_bound = thresholds.get("u")
            if lower_bound is not None and value < lower_bound:
                return "unusable"
            if thresholds.get("b") is not None:
                return "bad"
            if thresholds.get("p") is not None:
                return "poor"
            return "warn"

        for key, label in STATUS_LADDER:
            limit = thresholds.get(key)
            if limit is None:
                continue
            if value <= limit:
                return label
        upper_bound = thresholds.get("u")
        if upper_bound is not None and value > upper_bound:
            return "unusable"
        if thresholds.get("b") is not None:
            return "bad"
        if thresholds.get("p") is not None:
            return "poor"
        return "warn"

    def format_threshold_tooltip(value: Optional[float], thresholds: Dict[str, float], unit: str = "", higher_is_better: bool = False) -> str:
        if not thresholds:
            return ""

        def fmt(val: Optional[float], decimals: int = 2) -> Optional[str]:
            if val is None:
                return None
            text = f"{val:.{decimals}f}"
            return f"{text}{(' ' + unit) if unit else ''}"

        parts = []
        comparator = "≥" if higher_is_better else "≤"
        for key, _ in STATUS_LADDER:
            limit = thresholds.get(key)
            if limit is None:
                continue
            label = THR_desc.get(key, key.upper())
            parts.append(f"{label} {comparator} {fmt(limit)}")

        unusable_limit = thresholds.get("u")
        if unusable_limit is not None:
            unusable_label = THR_desc.get("u", "UNUSABLE")
            unusable_comparator = "<" if higher_is_better else ">"
            parts.append(f"{unusable_label} {unusable_comparator} {fmt(unusable_limit)}")

        return " • ".join(parts)

    items = []
    for r in rows:
        pm = safe_load(r["project_meta"])
        site = (pm.get("site") or {})
        qm = (pm.get("qm") or {})
        keys = (pm.get("keys") or {})

        pss = qm.get("project_set_scatter")
        ssov = qm.get("set_scatter_overall")
        gravity = site.get("Gravity (uGal)")

        sets_total = nint(keys.get("Number of Sets"))
        drops_total = nint(keys.get("Number of Drops"))
        sets_processed = keys.get("Set #s Processed") or None
        sets_ignored = keys.get("Number of Sets NOT Processed") or None
        drops_accepted = nint(keys.get("Total Drops Accepted"))
        drops_rejected = nint(keys.get("Total Drops Rejected"))

        acc_pct = None
        if drops_accepted is not None and drops_rejected is not None and (drops_accepted + drops_rejected) > 0:
            acc_pct = round(drops_accepted * 100.0 / (drops_accepted + drops_rejected), 1)

        items.append(
            {
                "id": r["id"],
                "title": r["title"],
                "note": r["note"],
                "created_at": r["created_at"],
                "keys": keys,
                "pss": pss,
                "pss_status": classify_threshold(pss, THR.get("pss", {})),
                "pss_tooltip": format_threshold_tooltip(pss, THR.get("pss", {}), unit="µGal"),
                "ssov": ssov,
                "ssov_status": classify_threshold(ssov, THR.get("ssov", {})),
                "ssov_tooltip": format_threshold_tooltip(ssov, THR.get("ssov", {}), unit="µGal"),
                "gravity": gravity,
                "sets_at_drops": f"{sets_total}@{drops_total}" if (sets_total is not None and drops_total is not None) else "-",
                "sets_processed": sets_processed or "-",
                "sets_ignored": sets_ignored or "-",
                "drops_accepted": drops_accepted,
                "drops_rejected": drops_rejected,
                "accepted_pct": acc_pct,
                "accepted_status": classify_threshold(acc_pct, THR.get("acc", {}), higher_is_better=True),
                "accepted_tooltip": format_threshold_tooltip(acc_pct, THR.get("acc", {}), unit="%", higher_is_better=True),
            }
        )

    survey = dict(survey_row)
    return TEMPLATES.TemplateResponse(
        "measurements_list.html",
        {"request": request, "survey_id": survey_id, "survey": survey, "items": items},
    )



@router.get("/new")
def new_measurement_form(request: Request, survey_id: int):
    survey = dict(_get_survey(survey_id))
    return TEMPLATES.TemplateResponse(
        "measurement_new.html",
        {
            "request": request,
            "survey_id": survey_id,
            "survey": survey,
            "title": "New Measurement",
            "action": f"/site-surveys/{survey_id}/measurements/new",
            "measurement": None,
        },
    )


@router.post("/new")
def create_measurement(survey_id: int, title: str = Form(...), note: str = Form("")):
    _ensure_survey_exists(survey_id)
    with _db() as con:
        cur = con.execute(
            "INSERT INTO measurements (survey_id, title, note, created_at) VALUES (?, ?, ?, ?)",
            (survey_id, title, note, _now()),
        )
        mid = cur.lastrowid
        con.commit()
    return RedirectResponse(url=f"/site-surveys/{survey_id}/measurements/{mid}", status_code=303)

@router.get("/{measurement_id}/edit")
def edit_measurement_form(request: Request, survey_id: int, measurement_id: int):
    survey = dict(_get_survey(survey_id))
    meas = _get_measurement(measurement_id)
    if not meas or meas["survey_id"] != survey_id:
        raise HTTPException(status_code=404, detail="Measurement not found")
    return TEMPLATES.TemplateResponse(
        "measurement_new.html",
        {"request": request, "survey_id": survey_id, "survey": survey, "title": f"Edit Measurement - {meas['title']}", "action": f"/site-surveys/{survey_id}/measurements/{measurement_id}/edit", "measurement": dict(meas)},
    )

@router.post("/{measurement_id}/edit")
def update_measurement(survey_id: int, measurement_id: int, title: str = Form(...), note: str = Form("")):
    _get_survey(survey_id)  # ensure survey exists
    meas = _get_measurement(measurement_id)
    if not meas or meas["survey_id"] != survey_id:
        raise HTTPException(status_code=404, detail="Measurement not found")
    with _db() as con:
        con.execute("UPDATE measurements SET title=?, note=? WHERE id=?", (title, note, measurement_id))
        con.commit()
    return RedirectResponse(
        url=f"/site-surveys/{survey_id}/measurements/{measurement_id}",
        status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/{measurement_id}")
def measurement_detail(request: Request, survey_id: int, measurement_id: int):
    survey_row = _get_survey(survey_id)
    meas = _get_measurement(measurement_id)
    if not meas or meas["survey_id"] != survey_id:
        raise HTTPException(status_code=404, detail="Measurement not found")

    with _db() as con:
        g9p = con.execute("SELECT * FROM measurement_project WHERE measurement_id=?", (measurement_id,)).fetchone()
        g9s = con.execute("SELECT * FROM measurement_set     WHERE measurement_id=?", (measurement_id,)).fetchone()
        imgs = con.execute("SELECT id, filename FROM measurement_images WHERE measurement_id=? ORDER BY id DESC", (measurement_id,)).fetchall()
        graphs = con.execute("SELECT id, filename, mime_type FROM measurement_graphs WHERE measurement_id=? ORDER BY id DESC", (measurement_id,)).fetchall()
        site_files = con.execute(
            "SELECT id, filename, mime_type, size_bytes, note FROM site_files WHERE measurement_id=? ORDER BY id DESC",
            (measurement_id,),
        ).fetchall()

    qm = None
    if g9p:
        try:
            meta = json.loads(g9p["meta_json"])
            qm = meta.get("qm", None)
        except Exception:
            qm = None

    survey = dict(survey_row)
    return TEMPLATES.TemplateResponse(
        "measurement_detail.html",
        {
            "request": request,
            "survey_id": survey_id,
            "survey": survey,
            "m": meas,
            "g9p": g9p,
            "g9s": g9s,
            "imgs": imgs,
            "graphs": graphs,
            "site_files": site_files,
            "thr": THR,
            "qm": qm,
        },
    )


@router.post("/{measurement_id}/upload/project")
async def upload_project(survey_id: int, measurement_id: int, file: UploadFile = File(...)):
    meas = _get_measurement(measurement_id)
    if not meas or meas["survey_id"] != survey_id:
        raise HTTPException(status_code=404, detail="Measurement not found")
    if not file.filename.lower().endswith(".project.txt"):
        raise HTTPException(status_code=400, detail="Expected a *.project.txt")

    text = _decode_text(await file.read())
    meta = parse_project_text(text)
    with _db() as con:
        # ensure single row (replace if exists)
        con.execute("DELETE FROM measurement_project WHERE measurement_id=?", (measurement_id,))
        con.execute(
            "INSERT INTO measurement_project (measurement_id, filename, raw_text, meta_json, imported_at) VALUES (?, ?, ?, ?, ?)",
            (measurement_id, file.filename, text, json.dumps(meta, ensure_ascii=False), _now()),
        )
        con.commit()
    return RedirectResponse(url=f"/site-surveys/{survey_id}/measurements/{measurement_id}", status_code=303)

@router.post("/{measurement_id}/upload/set")
async def upload_set(survey_id: int, measurement_id: int, file: UploadFile = File(...)):
    meas = _get_measurement(measurement_id)
    if not meas or meas["survey_id"] != survey_id:
        raise HTTPException(status_code=404, detail="Measurement not found")
    if not file.filename.lower().endswith(".set.txt"):
        raise HTTPException(status_code=400, detail="Expected a *.set.txt")

    text = _decode_text(await file.read())
    meta = parse_sets_text(text)
    with _db() as con:
        con.execute("DELETE FROM measurement_set WHERE measurement_id=?", (measurement_id,))
        con.execute(
            "INSERT INTO measurement_set (measurement_id, filename, raw_text, meta_json, imported_at) VALUES (?, ?, ?, ?, ?)",
            (measurement_id, file.filename, text, json.dumps(meta, ensure_ascii=False), _now()),
        )
        con.commit()
    return RedirectResponse(url=f"/site-surveys/{survey_id}/measurements/{measurement_id}", status_code=303)

ALLOWED_IMG = {".jpg",".jpeg",".png",".webp",".tif",".tiff",".bmp",".gif"}
ALLOWED_GRAPH = ALLOWED_IMG | {".pdf"}

def _ext(name: str) -> str:
    return Path(name).suffix.lower()

@router.post("/{measurement_id}/project/delete")
def delete_project(survey_id: int, measurement_id: int):
    meas = _get_measurement(measurement_id)
    if not meas or meas["survey_id"] != survey_id:
        raise HTTPException(status_code=404, detail="Measurement not found")
    with _db() as con:
        cur = con.execute("DELETE FROM measurement_project WHERE measurement_id=?", (measurement_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Project file not found")
        con.commit()
    return RedirectResponse(
        url=f"/site-surveys/{survey_id}/measurements/{measurement_id}",
        status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/{measurement_id}/set/delete")
def delete_set(survey_id: int, measurement_id: int):
    meas = _get_measurement(measurement_id)
    if not meas or meas["survey_id"] != survey_id:
        raise HTTPException(status_code=404, detail="Measurement not found")
    with _db() as con:
        cur = con.execute("DELETE FROM measurement_set WHERE measurement_id=?", (measurement_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Set file not found")
        con.commit()
    return RedirectResponse(
        url=f"/site-surveys/{survey_id}/measurements/{measurement_id}",
        status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/{measurement_id}/upload/images")
async def upload_images(
    survey_id: int,
    measurement_id: int,
    files: List[UploadFile] = File(...),
    caption: Optional[str] = Form(""),
):
    meas = _get_measurement(measurement_id)
    if not meas or meas["survey_id"] != survey_id:
        raise HTTPException(status_code=404, detail="Measurement not found")
    with _db() as con:
        for uf in files:
            if _ext(uf.filename) not in ALLOWED_IMG:
                continue
            content = await uf.read()
            con.execute("""
                INSERT INTO measurement_images (measurement_id, filename, mime_type, size_bytes, sha256_hex, caption, imported_at, image_blob)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (measurement_id, uf.filename, uf.content_type, len(content), _sha256_hex(content), caption or "", _now(), content))
        con.commit()
    return RedirectResponse(url=f"/site-surveys/{survey_id}/measurements/{measurement_id}", status_code=303)

@router.post("/{measurement_id}/upload/graphs")
async def upload_graphs(
    survey_id: int,
    measurement_id: int,
    files: List[UploadFile] = File(...),
    note: Optional[str] = Form(""),
):
    meas = _get_measurement(measurement_id)
    if not meas or meas["survey_id"] != survey_id:
        raise HTTPException(status_code=404, detail="Measurement not found")
    with _db() as con:
        for uf in files:
            if _ext(uf.filename) not in ALLOWED_GRAPH:
                continue
            content = await uf.read()
            con.execute("""
                INSERT INTO measurement_graphs (measurement_id, filename, mime_type, size_bytes, sha256_hex, note, imported_at, graph_blob)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (measurement_id, uf.filename, uf.content_type, len(content), _sha256_hex(content), note or "", _now(), content))
        con.commit()
    return RedirectResponse(url=f"/site-surveys/{survey_id}/measurements/{measurement_id}", status_code=303)


@router.post("/{measurement_id}/upload/files")
async def upload_site_files(
    survey_id: int,
    measurement_id: int,
    files: List[UploadFile] = File(...),
    note: Optional[str] = Form(""),
):
    meas = _get_measurement(measurement_id)
    if not meas or meas["survey_id"] != survey_id:
        raise HTTPException(status_code=404, detail="Measurement not found")

    with _db() as con:
        for uf in files:
            content = await uf.read()
            if not content:
                continue
            con.execute(
                """
                INSERT INTO site_files (measurement_id, filename, mime_type, size_bytes, sha256_hex, note, imported_at, file_blob)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    measurement_id,
                    uf.filename,
                    uf.content_type,
                    len(content),
                    _sha256_hex(content),
                    note or "",
                    _now(),
                    content,
                ),
            )
        con.commit()
    return RedirectResponse(url=f"/site-surveys/{survey_id}/measurements/{measurement_id}", status_code=303)

# ---- Blob streaming (inline)
@router.get("/{measurement_id}/image/{image_id}")
def get_image(survey_id: int, measurement_id: int, image_id: int):
    meas = _get_measurement(measurement_id)
    if not meas or meas["survey_id"] != survey_id:
        raise HTTPException(status_code=404, detail="Measurement not found")
    with _db() as con:
        row = con.execute("SELECT filename, mime_type, image_blob FROM measurement_images WHERE id=? AND measurement_id=?", (image_id, measurement_id)).fetchone()
        if not row: raise HTTPException(status_code=404, detail="Image not found")
    return Response(content=row["image_blob"], media_type=row["mime_type"] or "application/octet-stream",
                    headers={"Content-Disposition": f'inline; filename="{row["filename"]}"'})

@router.post("/{measurement_id}/image/{image_id}/delete")
def delete_image(survey_id: int, measurement_id: int, image_id: int):
    meas = _get_measurement(measurement_id)
    if not meas or meas["survey_id"] != survey_id:
        raise HTTPException(status_code=404, detail="Measurement not found")
    with _db() as con:
        cur = con.execute("DELETE FROM measurement_images WHERE id=? AND measurement_id=?", (image_id, measurement_id))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Image not found")
        con.commit()
    return RedirectResponse(
        url=f"/site-surveys/{survey_id}/measurements/{measurement_id}",
        status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/{measurement_id}/graph/{graph_id}/delete")
def delete_graph(survey_id: int, measurement_id: int, graph_id: int):
    meas = _get_measurement(measurement_id)
    if not meas or meas["survey_id"] != survey_id:
        raise HTTPException(status_code=404, detail="Measurement not found")
    with _db() as con:
        cur = con.execute("DELETE FROM measurement_graphs WHERE id=? AND measurement_id=?", (graph_id, measurement_id))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Graph not found")
        con.commit()
    return RedirectResponse(
        url=f"/site-surveys/{survey_id}/measurements/{measurement_id}",
        status_code=status.HTTP_303_SEE_OTHER
    )

@router.get("/{measurement_id}/graph/{graph_id}")
def get_graph(survey_id: int, measurement_id: int, graph_id: int):
    meas = _get_measurement(measurement_id)
    if not meas or meas["survey_id"] != survey_id:
        raise HTTPException(status_code=404, detail="Measurement not found")
    with _db() as con:
        row = con.execute("SELECT filename, mime_type, graph_blob FROM measurement_graphs WHERE id=? AND measurement_id=?", (graph_id, measurement_id)).fetchone()
        if not row: raise HTTPException(status_code=404, detail="Graph not found")
    return Response(content=row["graph_blob"], media_type=row["mime_type"] or "application/octet-stream",
                    headers={"Content-Disposition": f'inline; filename="{row["filename"]}"'})


@router.get("/{measurement_id}/file/{file_id}")
def get_site_file(survey_id: int, measurement_id: int, file_id: int):
    meas = _get_measurement(measurement_id)
    if not meas or meas["survey_id"] != survey_id:
        raise HTTPException(status_code=404, detail="Measurement not found")
    with _db() as con:
        row = con.execute(
            "SELECT filename, mime_type, file_blob FROM site_files WHERE id=? AND measurement_id=?",
            (file_id, measurement_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="File not found")
    return Response(
        content=row["file_blob"],
        media_type=row["mime_type"] or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{row["filename"]}"'},
    )


@router.post("/{measurement_id}/file/{file_id}/delete")
def delete_site_file(survey_id: int, measurement_id: int, file_id: int):
    meas = _get_measurement(measurement_id)
    if not meas or meas["survey_id"] != survey_id:
        raise HTTPException(status_code=404, detail="Measurement not found")
    with _db() as con:
        cur = con.execute("DELETE FROM site_files WHERE id=? AND measurement_id=?", (file_id, measurement_id))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="File not found")
        con.commit()
    return RedirectResponse(
        url=f"/site-surveys/{survey_id}/measurements/{measurement_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )

@router.post("/{measurement_id}/delete")
def delete_measurement(survey_id: int, measurement_id: int):
    meas = _get_measurement(measurement_id)
    if not meas or meas["survey_id"] != survey_id:
        raise HTTPException(status_code=404, detail="Measurement not found")

    with _db() as con:
        con.execute("DELETE FROM measurements WHERE id=?", (measurement_id,))
        con.commit()

    return RedirectResponse(
        url=f"/site-surveys/{survey_id}/measurements",
        status_code=status.HTTP_303_SEE_OTHER
    )
