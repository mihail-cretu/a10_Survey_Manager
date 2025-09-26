"""Shared configuration constants for the Site Survey Manager app."""

from __future__ import annotations

import re

# ---- Static thresholds for quality classification (µGal, %, etc.)

THR_desc = {"g":  "GOOD", "w":  "WARN", "p":  "POOR", "b": "BAD", "u":  "UNUSABLE"}

STATUS_LADDER = [ ("g", "good"),    ("w", "warn"),    ("p", "poor"),    ("b", "bad"),    ("u", "unusable") ]

THR = {
    "pss":  {"g":  1.5, "w":  2.0, "p":  5.0, "b": 10.0, "u":  20.0},   # Project Set Scatter (µGal)
    "tu":   {"g": 11.0, "w": 12.0, "p": 13.0, "b": 20.0, "u":  25.0},   # Total Uncertainty (µGal)
    "ups":  {"g": 15.0, "w": 20.0, "p": 65.0, "b": 70.0, "u":  75.0},   # Uncertainty / Set (µGal)
    "ss":   {"g": 50.0, "w": 60.0, "p": 70.0, "b": 80.0, "u": 100.0},   # Set Scatter (µGal)
    "ssov": {"g":  5.0, "w":  7.0, "p": 10.0, "b": 15.0, "u":  20.0},   # Set Scatter overall (µGal)
    "acc":  {"g": 95.0, "w": 85.0, "p": 75.0, "b": 65.0, "u":  55.0},   # Acceptance (%)
}

# ---- Encoding preferences used when decoding uploaded text files
PREFERRED_ENCODINGS = (
    "utf-8",
    "utf-16",
    "utf-16le",
    "utf-16be",
    "cp1252",
    "latin-1",
)

# ---- Regex utilities
KV_RE = re.compile(r"^\s*([^:]{1,128})\s*:\s*(.+?)\s*$")

# ---- Survey status enumeration
STATUS_CHOICES = ["new", "preflight", "measurements", "completed", "archived", "deleted", "error", "locked" ]


