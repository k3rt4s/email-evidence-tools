"""
scan_mbox_for_evidence.py
=========================
Project : email-evidence-tools
Purpose : Parses an .mbox email archive and scans every message body for
          keyword categories. Designed as a generic content-scanner for use
          cases like security-operations email triage, phishing/exfiltration
          review, internal investigations, or legal evidence review. The
          default keyword set targets security ops (phishing, data
          exfiltration, policy violations, incident response language) and
          should be edited per workflow.
          Writes one CSV row per (message, category, matched term, matching sentence).

Input   : --mbox-file or MBOX_FILE
Output  : --output-file or OUTPUT_FILE (default: mbox_evidence_hits.csv)

Usage   : python scan_mbox_for_evidence.py --mbox-file "<path-to-export.mbox>"

Post-processing: Run clean_evidence_csv.py to strip HTML tags from the exact_text column.
"""

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
# (case-insensitive) against the normalized message body. The default set
# below targets security-operations triage of an mbox export: phishing,
# data-exfiltration indicators, policy violations, and incident-response
# language. Replace or extend per use case.
# =============================
SEARCH_TERMS = {

    # ---- PHISHING & SOCIAL ENGINEERING ----
    "credential_requests": [
        "verify your account", "confirm your password",
        "click here to login", "your account will be suspended",
        "unusual sign-in", "password reset required",
        "validate your credentials"
    ],
    "executive_impersonation": [
        "are you at your desk", "i'm in a meeting",
        "i need this done quickly", "purchase gift cards",
        "send me your number", "wire transfer request"
    ],
    "payment_fraud_indicators": [
        "updated banking details", "new account number",
        "wire instructions", "urgent payment",
        "invoice attached", "overdue invoice"
    ],

    # ---- DATA EXFILTRATION INDICATORS ----
    "external_share_requests": [
        "share via dropbox", "google drive link",
        "wetransfer", "personal email", "send to gmail",
        "send to my home email", "outside the company"
    ],
    "sensitive_data_requests": [
        "send me the spreadsheet", "employee list",
        "password list", "customer database",
        "export the data", "full dataset"
    ],
    "credential_sharing": [
        "here's my password", "use my login",
        "my credentials are", "service account password",
        "shared account"
    ],

    # ---- POLICY VIOLATIONS ----
    "unauthorized_tools": [
        "i installed", "downloaded from", "personal device",
        "bypass", "workaround", "unapproved tool"
    ],
    "confidentiality_concerns": [
        "confidential", "do not forward", "nda",
        "trade secret", "proprietary", "internal only"
    ],
    "shadow_it": [
        "signed up for", "created an account",
        "new saas", "without it approval"
    ],

    # ---- INCIDENT RESPONSE LANGUAGE ----
    "compromise_indicators": [
        "unauthorized access", "suspicious activity",
        "breach", "compromised", "incident",
        "leaked", "exposed"
    ],
    "malware_indicators": [
        "ransomware", "encrypted my files", "ransom note",
        "malware detected", "antivirus alert",
        "endpoint protection"
    ],
    "investigation_terms": [
        "forensic", "preserve evidence", "chain of custody",
        "soc ticket", "incident ticket", "triage"
    ],

    # ---- URGENCY & PRESSURE ----
    "urgency_language": [
        "urgent", "asap", "immediately", "right now",
        "time sensitive", "emergency", "do not delay"
    ],
    "external_link_lures": [
        "click the link", "follow this url", "log in here",
        "open the attachment", "enable macros",
        "view document online"
    ],

    # ---- GENERAL CORRESPONDENCE ANALYSIS ----
    "follow_ups": [
        "following up", "still waiting", "haven't heard",
        "any update", "checking in"
    ],
    "deadline_commitments": [
        "by friday", "by monday", "this week",
        "next week", "by end of"
    ],
    "attachment_promises": [
        "attached", "here is", "i'm sending",
        "supporting documentation", "see file"
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
