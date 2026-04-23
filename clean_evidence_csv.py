# === AI REVIEWER - READ BEFORE EDITING ==============================
# Before changing this file, read the master workspace README at
#   d:\Proton Drive\My files\Code\README.md   ("AI Session Rules" section)
# and the README(s) for this project and sub-product. Those documents
# are the single source of truth for venvs, path conventions,
# archive/backup rules, markdown conventions, and every repo-wide rule.
# Do not guess - reference the READMEs first.
# =====================================================================

"""
clean_evidence_csv.py
=====================
Project : Crosier_Bowker — Legal Evidence Review
Case    : Tennessee Board of Professional Responsibility, Complaint No. 105302-2026-CAP
Purpose : Post-processing step for the output of scan_mbox_for_evidence.py.
          Reads the raw evidence CSV, strips HTML tags from the `exact_text` column,
          and collapses excess whitespace so hits are readable in a spreadsheet or
          when pasted into correspondence.

Input   : INPUT_FILE  — mbox_evidence_hits_clean.csv  (output of scan_mbox_for_evidence.py)
Output  : OUTPUT_FILE — mbox_evidence_hits_clean2.csv (cleaned, ready for review)

Usage   : python clean_evidence_csv.py

Note    : This script is non-destructive; the original CSV is not modified.

Author  : Jonathan David Bowker
Created : 2025-12-30
"""

# --- auto-deps bootstrap (Code/scripts/_bootstrap.py) ---
from pathlib import Path as _P
import sys as _s
_boot_dir = next((_p / "scripts" for _p in _P(__file__).resolve().parents
                  if (_p / "scripts" / "_bootstrap.py").exists()), None)
if _boot_dir and str(_boot_dir) not in _s.path:
    _s.path.insert(0, str(_boot_dir))
from _bootstrap import ensure_requirements as _ensure_reqs  # noqa: E402
_ensure_reqs(__file__)
# --- end bootstrap ---

import pandas as pd
import re

INPUT_FILE  = "mbox_evidence_hits_clean.csv"
OUTPUT_FILE = "mbox_evidence_hits_clean2.csv"


def clean_text(text):
    """Remove HTML tags and normalize whitespace in a text value."""
    if pd.isna(text):
        return ""
    # Strip HTML tags
    text = re.sub(r"<[^>]+>", " ", str(text))
    # Collapse runs of whitespace to a single space
    text = re.sub(r"\s+", " ", text)
    return text.strip()


if __name__ == "__main__":
    df = pd.read_csv(INPUT_FILE)
    original_rows = len(df)

    df["exact_text"] = df["exact_text"].apply(clean_text)

    df.to_csv(OUTPUT_FILE, index=False)
    print(f"Done. {original_rows:,} rows cleaned → {OUTPUT_FILE}")
