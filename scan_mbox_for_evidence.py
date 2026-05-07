# === AI REVIEWER - READ BEFORE EDITING ==============================
# Before changing this file, read the master workspace README at
#   C:\Code\README.md   ("AI Session Rules" section)
# and the README(s) for this project and sub-product. Those documents
# are the single source of truth for venvs, path conventions,
# archive/backup rules, markdown conventions, and every repo-wide rule.
# Do not guess - reference the READMEs first.
# =====================================================================

"""
scan_mbox_for_evidence.py
=========================
Project : email-evidence-tools
Purpose : Parses an .mbox email archive and scans every message body for keyword
          categories relevant to an evidence review. The default keyword set is
          intentionally generic and can be edited for each matter or workflow.
          Writes one CSV row per (message, category, matched term, matching sentence).

Input   : --mbox-file or MBOX_FILE
Output  : --output-file or OUTPUT_FILE (default: mbox_evidence_hits.csv)

Usage   : python scan_mbox_for_evidence.py --mbox-file "<path-to-export.mbox>"

Post-processing: Run clean_evidence_csv.py to strip HTML tags from the exact_text column.
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

import mailbox
import email
import csv
import re
import os
import argparse
from email.utils import parsedate_to_datetime

DEFAULT_OUTPUT_FILE = "mbox_evidence_hits.csv"

# =============================
# SEARCH TERMS
# Each key is a named evidence category; values are keyword phrases searched
# (case-insensitive) against the normalized message body.
# =============================
SEARCH_TERMS = {

    # ---- BILLING ----
    "billing_promises": [
        "reduce", "reduction", "adjustment", "courtesy",
        "discount", "write off", "credit"
    ],
    "billing_errors": [
        "mistake", "error", "shouldn't have billed",
        "will correct", "overbilled"
    ],
    "billing_cost_concerns": [
        "expensive", "high", "afford", "budget",
        "cost", "retainer"
    ],
    "billing_review_promises": [
        "review the billing", "review invoice",
        "look at the invoice", "go through the charges",
        "billing meeting"
    ],
    "payment_pressure": [
        "past due", "overdue", "payment", "balance", "owe"
    ],

    # ---- SETTLEMENT / STRATEGY ----
    "settlement_phrases": [
        "stop settlement", "stop negotiating",
        "no settlement", "do not settle",
        "instead of settlement", "take her to court",
        "file instead", "court instead of settlement"
    ],
    "settlement_terms": [
        "settlement", "negotiate", "negotiating", "negotiation"
    ],
    "court_action_requests": [
        "file", "motion", "court", "enforcement",
        "contempt", "hearing"
    ],
    "strategy_disagreement": [
        "disagree", "don't want", "not comfortable",
        "prefer", "instead", "change strategy"
    ],
    "stop_indicators": [
        "stop", "not", "no longer", "rather", "instead"
    ],

    # ---- COMMUNICATION ----
    "follow_ups": [
        "following up", "still waiting", "haven't heard",
        "any update", "checking in"
    ],
    "urgent_requests": [
        "urgent", "emergency", "asap", "immediately",
        "time sensitive", "deadline"
    ],
    "requests_for_explanation": [
        "why", "explain", "don't understand",
        "can you clarify", "confused"
    ],

    # ---- CHILD / PARENTING ----
    "parenting_violations": [
        "violation", "not following", "breach",
        "contempt", "ignoring order"
    ],
    "lost_parenting_time": [
        "missed", "didn't get", "couldn't see",
        "denied", "cancelled"
    ],
    "child_urgency": [
        "kids", "children", "parenting time",
        "visitation", "access"
    ],

    # ---- TERMINATION / CONDUCT ----
    "pre_termination_frustration": [
        "frustrated", "disappointed", "concerned",
        "worried", "unhappy"
    ],
    "request_change_approach": [
        "different approach", "change course",
        "try something else", "not working"
    ],
    "termination_language": [
        "new attorney", "different lawyer",
        "find someone else", "find new counsel",
        "retain"
    ],

    # ---- PROMISES / DELAYS ----
    "promises_general": [
        "i will", "i'll", "we will", "we'll"
    ],
    "deadline_commitments": [
        "by friday", "by monday", "this week",
        "next week", "by end of"
    ],
    "document_delivery_promises": [
        "send you", "forward", "attach", "dropbox", "share"
    ],

    # ---- EVIDENCE / DISCLOSURE ----
    "evidence_provided": [
        "attached", "here is", "i'm sending",
        "evidence", "proof", "documentation"
    ],
    "evidence_use_requests": [
        "use this", "include this", "show the judge",
        "file this", "submit this"
    ],
    "confidentiality_concerns": [
        "confidential", "private", "shouldn't know",
        "how did he", "disclosed"
    ]
}

# =============================
# HELPERS
# =============================

def get_body(msg):
    """Extract plain-text body from a message, handling multipart structures."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    return part.get_payload(decode=True).decode(errors="ignore")
                except Exception:
                    return ""
    else:
        try:
            return msg.get_payload(decode=True).decode(errors="ignore")
        except Exception:
            return ""
    return ""


def normalize(text):
    """Lowercase and collapse whitespace for consistent matching."""
    return re.sub(r"\s+", " ", text.lower())


def extract_sentences(text):
    """Split text into sentences on sentence-ending punctuation."""
    return re.split(r'(?<=[.!?])\s+', text)


def parse_args():
    """Parse command-line arguments and environment-variable fallbacks."""
    parser = argparse.ArgumentParser(
        description="Scan an mbox export for evidence keyword hits."
    )
    parser.add_argument(
        "--mbox-file",
        default=os.getenv("MBOX_FILE"),
        help="Path to the source .mbox file. Defaults to MBOX_FILE.",
    )
    parser.add_argument(
        "--output-file",
        default=os.getenv("OUTPUT_FILE", DEFAULT_OUTPUT_FILE),
        help=f"CSV output path. Defaults to OUTPUT_FILE or {DEFAULT_OUTPUT_FILE}.",
    )
    args = parser.parse_args()
    if not args.mbox_file:
        parser.error("--mbox-file is required unless MBOX_FILE is set.")
    return args


# =============================
# MAIN
# =============================
if __name__ == "__main__":
    args = parse_args()

    with open(args.output_file, "w", newline="", encoding="utf-8") as out:
        writer = csv.writer(out)
        writer.writerow([
            "date", "from", "to", "subject",
            "category", "matched_term", "exact_text"
        ])

        mbox = mailbox.mbox(args.mbox_file)
        total_hits = 0

        for msg in mbox:
            date_raw = msg.get("date", "")
            try:
                date = parsedate_to_datetime(date_raw).isoformat()
            except Exception:
                date = date_raw

            sender    = msg.get("from", "")
            recipient = msg.get("to", "")
            subject   = msg.get("subject", "")

            body      = get_body(msg)
            norm_body = normalize(body)
            sentences = extract_sentences(body)

            for category, terms in SEARCH_TERMS.items():
                for term in terms:
                    if term in norm_body:
                        for sentence in sentences:
                            if term in sentence.lower():
                                writer.writerow([
                                    date, sender, recipient, subject,
                                    category, term, sentence.strip()
                                ])
                                total_hits += 1

    print(f"Done. {total_hits:,} evidence hits written to {args.output_file}")
    print("Next step: run clean_evidence_csv.py to strip HTML from the exact_text column.")
