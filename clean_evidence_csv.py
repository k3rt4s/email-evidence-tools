# === AI REVIEWER - READ BEFORE EDITING ==============================
# Before changing this file, read the master workspace README at
#   C:\Code\README.md   ("AI Session Rules" section)
# and the README(s) for this project and sub-product. Those documents
# are the single source of truth for venvs, path conventions,
# archive/backup rules, markdown conventions, and every repo-wide rule.
# Do not guess - reference the READMEs first.
# =====================================================================

"""
clean_evidence_csv.py
=====================
Project : email-evidence-tools
Purpose : Post-processing step for the output of scan_mbox_for_evidence.py.
          Reads the raw evidence CSV, strips HTML tags from the `exact_text` column,
          and collapses excess whitespace so hits are readable in a spreadsheet or
          when pasted into correspondence.

Input   : --input-file or INPUT_FILE
Output  : --output-file or OUTPUT_FILE

Usage   : python clean_evidence_csv.py --input-file evidence_hits.csv --output-file evidence_hits_clean.csv

Note    : This script is non-destructive; the original CSV is not modified.
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
import os
import argparse

DEFAULT_INPUT_FILE = "mbox_evidence_hits.csv"
DEFAULT_OUTPUT_FILE = "mbox_evidence_hits_clean.csv"


def clean_text(text):
    """Remove HTML tags and normalize whitespace in a text value."""
    if pd.isna(text):
        return ""
    # Strip HTML tags
    text = re.sub(r"<[^>]+>", " ", str(text))
    # Collapse runs of whitespace to a single space
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_args():
    """Parse command-line arguments and environment-variable fallbacks."""
    parser = argparse.ArgumentParser(
        description="Clean text fields in an evidence CSV."
    )
    parser.add_argument(
        "--input-file",
        default=os.getenv("INPUT_FILE", DEFAULT_INPUT_FILE),
        help=f"Input CSV path. Defaults to INPUT_FILE or {DEFAULT_INPUT_FILE}.",
    )
    parser.add_argument(
        "--output-file",
        default=os.getenv("OUTPUT_FILE", DEFAULT_OUTPUT_FILE),
        help=f"Output CSV path. Defaults to OUTPUT_FILE or {DEFAULT_OUTPUT_FILE}.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    df = pd.read_csv(args.input_file)
    original_rows = len(df)

    df["exact_text"] = df["exact_text"].apply(clean_text)

    df.to_csv(args.output_file, index=False)
    print(f"Done. {original_rows:,} rows cleaned -> {args.output_file}")
