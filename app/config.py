"""Shared configuration constants for the Site Survey Manager app."""

from __future__ import annotations

import re

# ---- Static thresholds for quality classification (µGal, %, etc.)

THR_desc = {"g":  "GOOD", "w":  "WARN", "p":  "POOR", "b": "BAD", "u":  "UNUSABLE"}

STATUS_LADDER = [ ("g", "good"),    ("w", "warn"),    ("p", "poor"),    ("b", "bad"),    ("u", "unusable") ]

# Thresholds for laboratory surveys
THR_laboratory = {
    "pss":  {"g":  1.5, "w":  2.0, "p":  5.0, "b": 10.0, "u":  20.0},      # Project Set Scatter (µGal)
    "tu":   {"g": 11.0, "w": 12.0, "p": 13.0, "b": 20.0, "u":  25.0},      # Total Uncertainty (µGal)
    "ups":  {"g": 15.0, "w": 20.0, "p": 65.0, "b": 70.0, "u":  75.0},      # Uncertainty / Set (µGal)
    "ss":   {"g": 50.0, "w": 60.0, "p": 70.0, "b": 80.0, "u": 100.0},      # Set Scatter (µGal)
    "ssov": {"g":  5.0, "w":  7.0, "p": 10.0, "b": 15.0, "u":  20.0},      # Set Scatter overall (µGal)
    "acc":  {"g": 95.0, "w": 85.0, "p": 75.0, "b": 65.0, "u":  55.0},      # Acceptance (%)
}

# Thresholds for field surveys
THR_FieldSurvey = {
    "pss":  {"g":  5.0, "w": 10.0,  "p": 15.0,  "b": 20.0,  "u":  30.0},   # Project Set Scatter (µGal)
    "tu":   {"g": 15.0, "w": 20.0,  "p": 25.0,  "b": 30.0,  "u":  40.0},   # Total Uncertainty (µGal)
    "ups":  {"g": 25.0, "w": 35.0,  "p": 50.0,  "b": 65.0,  "u":  80.0},   # Uncertainty / Set (µGal)
    "ss":   {"g": 80.0, "w": 100.0, "p": 120.0, "b": 150.0, "u": 200.0},   # Set Scatter (µGal)
    "ssov": {"g": 10.0, "w": 15.0,  "p": 20.0,  "b": 25.0,  "u":  30.0},   # Set Scatter overall (µGal)
    "acc":  {"g": 90.0, "w": 80.0,  "p": 70.0,  "b": 60.0,  "u":  50.0},   # Acceptance (%)
}

# Thresholds for recon surveys
THR_Recon = {
    "pss":  {"g": 10.0,  "w":  15.0, "p":  25.0, "b":  35.0, "u":  50.0},  # Project Set Scatter (µGal)
    "tu":   {"g": 25.0,  "w":  30.0, "p":  40.0, "b":  50.0, "u":  70.0},  # Total Uncertainty (µGal)
    "ups":  {"g": 40.0,  "w":  55.0, "p":  75.0, "b": 100.0, "u": 120.0},  # Uncertainty / Set (µGal)
    "ss":   {"g": 120.0, "w": 150.0, "p": 180.0, "b": 220.0, "u": 300.0},  # Set Scatter (µGal)
    "ssov": {"g": 20.0,  "w":  25.0, "p":  30.0, "b":  40.0, "u":  50.0},  # Set Scatter overall (µGal)
    "acc":  {"g": 85.0,  "w":  75.0, "p":  65.0, "b":  55.0, "u":  45.0},  # Acceptance (%)
}

# Default thresholds
THR = THR_laboratory 


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
STATUS_CHOICES = ["new", "preflight", "measurements", "completed", "archived", "deleted", "error", "locked"]


