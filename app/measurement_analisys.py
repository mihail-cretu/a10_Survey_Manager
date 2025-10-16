from __future__ import annotations

import json
import math
import sqlite3
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

APP_ROOT = Path(__file__).parent
DATA_DIR = APP_ROOT / "data"
DB_PATH = DATA_DIR / "surveys.db"

TEMPLATES = Jinja2Templates(directory=str(APP_ROOT / "templates"))

router = APIRouter(
    prefix="/site-surveys/{survey_id}/analisys",
    tags=["Analysis"],
)


# ---- DB helpers -----------------------------------------------------------

def _db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _get_survey(survey_id: int):
    with _db() as con:
        row = con.execute("SELECT * FROM site_surveys WHERE id=?", (survey_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Site Survey not found")
    return row


# ---- Parsing helpers ------------------------------------------------------

def _parse_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).replace(",", ".")
    import re

    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group(0)) if match else None


def _parse_int(value: Any) -> Optional[int]:
    number = _parse_float(value)
    if number is None or math.isnan(number):
        return None
    return int(round(number))


@dataclass
class MeasurementSummary:
    id: int
    title: str
    created_at: str
    gravity: Optional[float]
    tu: Optional[float]
    drops_accepted: Optional[int]
    drops_rejected: Optional[int]
    accepted_pct: Optional[float]


def _safe_load_meta(meta_json: Optional[str]) -> Dict[str, Any]:
    if not meta_json:
        return {}
    try:
        return json.loads(meta_json)
    except Exception:
        return {}


def _collect_measurements(survey_id: int) -> List[MeasurementSummary]:
    with _db() as con:
        rows = con.execute(
            """
            SELECT m.id, m.title, m.created_at, mp.meta_json
            FROM measurements AS m
            LEFT JOIN measurement_project AS mp ON mp.measurement_id = m.id
            WHERE m.survey_id = ?
            ORDER BY m.title ASC
            """,
            (survey_id,),
        ).fetchall()

    summaries: List[MeasurementSummary] = []
    for row in rows:
        meta = _safe_load_meta(row["meta_json"])
        site_data = meta.get("site") or {}
        quality_metrics = meta.get("qm") or {}
        keys = meta.get("keys") or {}

        gravity = _parse_float(site_data.get("Gravity (µGal)"))
        tu = _parse_float(quality_metrics.get("total_uncertainty"))
        drops_accepted = _parse_int(keys.get("Total Drops Accepted"))
        drops_rejected = _parse_int(keys.get("Total Drops Rejected"))

        accepted_pct: Optional[float] = None
        if drops_accepted is not None and drops_rejected is not None:
            total_drops = drops_accepted + drops_rejected
            if total_drops > 0:
                accepted_pct = round((drops_accepted * 100.0) / total_drops, 1)

        summaries.append(
            MeasurementSummary(
                id=row["id"],
                title=row["title"],
                created_at=row["created_at"],
                gravity=gravity,
                tu=tu,
                drops_accepted=drops_accepted,
                drops_rejected=drops_rejected,
                accepted_pct=accepted_pct,
            )
        )

    return summaries


# ---- Statistics helpers ---------------------------------------------------

def _clean(values: Iterable[Optional[float]]) -> List[float]:
    return [v for v in values if v is not None and not math.isnan(v)]


def _calc_stats(values: Iterable[Optional[float]]) -> Dict[str, Optional[float]]:
    cleaned = _clean(values)
    if not cleaned:
        return {
            "count": 0,
            "min": None,
            "max": None,
            "avg": None,
            "stdev": None,
        }

    if len(cleaned) == 1:
        stdev = 0.0
    else:
        try:
            stdev = statistics.stdev(cleaned)
        except statistics.StatisticsError:
            stdev = None

    return {
        "count": len(cleaned),
        "min": min(cleaned),
        "max": max(cleaned),
        "avg": statistics.fmean(cleaned),
        "stdev": stdev,
    }


def _inverted_weighted_average(pairs: Iterable[Sequence[Optional[float]]]) -> Optional[float]:
    weighted_values: List[float] = []
    weights: List[float] = []
    for value, uncertainty in pairs:
        if value is None or uncertainty is None or uncertainty <= 0:
            continue
        weight = 1.0 / uncertainty
        weights.append(weight)
        weighted_values.append(value * weight)

    if not weights:
        return None

    return sum(weighted_values) / sum(weights)


def _build_chart_payload(selected: List[MeasurementSummary]) -> Dict[str, Any]:
    labels = [m.title for m in selected]
    gravity_values = [m.gravity for m in selected]
    tu_values = [m.tu for m in selected]

    open_prices: List[Optional[float]] = []
    close_prices: List[Optional[float]] = []
    high_values: List[Optional[float]] = []
    low_values: List[Optional[float]] = []
    for gravity, tu in zip(gravity_values, tu_values):
        if gravity is None or tu is None:
            open_prices.append(None)
            close_prices.append(None)
            high_values.append(None)
            low_values.append(None)
            continue
        open_prices.append(gravity - tu)
        close_prices.append(gravity + tu)
        high_values.append(gravity + tu)
        low_values.append(gravity - tu)

    gravity_stats = _calc_stats(gravity_values)

    shapes = []
    avg_value = gravity_stats.get("avg")
    weighted = _inverted_weighted_average(
        [(m.gravity, m.tu) for m in selected]
    )
    min_value = gravity_stats.get("min")
    max_value = gravity_stats.get("max")

    def horizontal_shape(y: Optional[float], color: str, dash: str = "solid") -> Optional[Dict[str, Any]]:
        if y is None:
            return None
        return {
            "type": "line",
            "xref": "paper",
            "x0": 0,
            "x1": 1,
            "y0": y,
            "y1": y,
            "line": {"color": color, "width": 2, "dash": dash},
        }

    for shape in [
        horizontal_shape(avg_value, "#dc2626"),
        horizontal_shape(weighted, "#7c3aed"),
        horizontal_shape(min_value, "#0ea5e9", dash="dot"),
        horizontal_shape(max_value, "#0ea5e9", dash="dot"),
    ]:
        if shape:
            shapes.append(shape)

    return {
        "labels": labels,
        "gravity": gravity_values,
        "tu_open": open_prices,
        "tu_close": close_prices,
        "tu_high": high_values,
        "tu_low": low_values,
        "lines": {
            "avg": avg_value,
            "weighted": weighted,
            "min": min_value,
            "max": max_value,
        },
        "shapes": shapes,
    }


def _render_response(
    request: Request,
    survey_id: int,
    selected_ids: Sequence[int],
) -> HTMLResponse:
    survey = dict(_get_survey(survey_id))
    measurements = _collect_measurements(survey_id)
    selected_map = {mid for mid in selected_ids}
    selected = [m for m in measurements if m.id in selected_map]

    gravity_stats = _calc_stats([m.gravity for m in selected])
    tu_stats = _calc_stats([m.tu for m in selected])
    drops_stats = _calc_stats([float(m.drops_accepted) if m.drops_accepted is not None else None for m in selected])
    accepted_pct_stats = _calc_stats([m.accepted_pct for m in selected])
    gravity_weighted = _inverted_weighted_average(
        [(m.gravity, m.tu) for m in selected]
    )

    chart_payload = _build_chart_payload(selected) if selected else None

    context = {
        "request": request,
        "survey": survey,
        "survey_id": survey_id,
        "measurements": measurements,
        "selected_ids": selected_map,
        "stats": {
            "gravity": {**gravity_stats, "weighted": gravity_weighted},
            "tu": tu_stats,
            "drops": drops_stats,
            "accepted_pct": accepted_pct_stats,
        },
        "chart_payload": json.dumps(chart_payload) if chart_payload else None,
    }
    return TEMPLATES.TemplateResponse("measurement_analisys.html", context)


# ---- Routes ---------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
def analisys_page(
    request: Request,
    survey_id: int,
    measurement_id: Optional[List[int]] = Query(default=None),
):
    selected_ids = measurement_id or []
    return _render_response(request, survey_id, selected_ids)


@router.post("", response_class=HTMLResponse)
def analisys_submit(
    request: Request,
    survey_id: int,
    measurement_ids: List[int] = Form(default=[]),
):
    return _render_response(request, survey_id, measurement_ids)

