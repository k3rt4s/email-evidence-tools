"""Scans an mbox archive for configurable evidence keyword categories and writes one CSV row per matched sentence.

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
          Both the Subject header and the message body are scanned; the
          `location` column on each row says which one the hit came from.
          Writes one CSV row per (message, category, matched term, matching sentence).

Input   : --mbox-file or MBOX_FILE
Output  : --output-file or OUTPUT_FILE. Defaults to <input>_evidence_hits.csv
          beside the source archive, never the working directory, so a run
          started from inside a code repository cannot drop evidence into it.

Usage   : python scan_mbox_for_evidence.py --mbox-file "<path-to-export.mbox>"

Post-processing: Run clean_evidence_csv.py to strip HTML tags from the exact_text column.
"""

import mailbox
import email
import csv
import re
import os
import argparse
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from pathlib import Path

from evidence_text import html_to_text

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
    """Extract readable text from a message, preferring text/plain and falling back to HTML.

    Every text part is collected, not just the first: a message can carry more
    than one text/plain part, and taking only the first drops the rest.

    The HTML fallback is load-bearing. A multipart/alternative message with no
    text/plain part is common from Outlook and from marketing systems, and
    without the fallback its body reads as empty, so the message is scanned as
    if it were blank and can never produce a hit.
    """
    plain, html = [], []
    for part in msg.walk():
        if part.get_content_maintype() != "text":
            continue
        ctype = part.get_content_type()
        try:
            payload = part.get_payload(decode=True)
        except Exception:
            continue
        if not payload:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            text = payload.decode(charset, errors="ignore")
        except (LookupError, UnicodeDecodeError):
            text = payload.decode("utf-8", errors="ignore")
        # Any text/* subtype that is not HTML is read as plain text. Restricting
        # this to text/plain would drop text/enriched, text/rfc822-headers and
        # the various oddly-labelled text parts legacy clients emit, which is the
        # same class of silent false negative as skipping HTML bodies.
        (html if ctype == "text/html" else plain).append(text)

    if plain:
        return "\n\n".join(plain)
    if html:
        return "\n\n".join(html_to_text(h) for h in html)
    return ""


def normalize(text):
    """Collapse whitespace runs to single spaces, preserving case.

    Both the body-level term check and the sentence split must run on this same
    normalized text. Normalizing only one of them silently discards every hit
    whose keyword crosses a line break: the term is present in the collapsed
    body, absent from every raw sentence, and so no row is ever written.
    """
    return re.sub(r"\s+", " ", text)


def extract_sentences(text):
    """Split text into sentences on sentence-ending punctuation."""
    return re.split(r'(?<=[.!?])\s+', text)


def decode_header_value(raw):
    """Decode an RFC 2047 encoded header into readable text.

    Subject lines arrive as `=?utf-8?B?...?=` from any client that used a
    non-ASCII character, and matching against that encoded form finds nothing.
    """
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(str(raw))))
    except Exception:
        return str(raw)


def scan_text(text, location, row_prefix, writer, split_sentences=True):
    """Write one row per (category, term, quote) hit in `text`. Returns the hit count.

    Matching and sentence extraction both run on the same normalized text; see
    normalize() for what splitting them apart silently costs.

    `split_sentences=False` quotes the whole of `text` instead. A subject line is
    one piece of evidence however much punctuation it contains, and splitting
    "Urgent payment. Please act." into fragments would quote half a subject in
    the exact_text column.
    """
    flat = normalize(text)
    if not flat:
        return 0
    lowered = flat.lower()
    sentences = extract_sentences(flat) if split_sentences else [flat]

    hits = 0
    for category, terms in SEARCH_TERMS.items():
        for term in terms:
            if term not in lowered:
                continue
            for sentence in sentences:
                if term in sentence.lower():
                    writer.writerow(row_prefix + [category, term, sentence.strip(), location])
                    hits += 1
    return hits


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
        default=os.getenv("OUTPUT_FILE"),
        help="CSV output path. Defaults to <input>_evidence_hits.csv beside the source archive.",
    )
    args = parser.parse_args()
    if not args.mbox_file:
        parser.error("--mbox-file is required unless MBOX_FILE is set.")
    if not args.output_file:
        # Beside the archive, not in the working directory. A relative default
        # writes evidence wherever the tool happens to be run from, which on this
        # workstation means into a code repository.
        source = Path(args.mbox_file)
        args.output_file = str(source.with_name(f"{source.stem}_evidence_hits.csv"))
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
            "category", "matched_term", "exact_text", "location"
        ])

        mbox = mailbox.mbox(args.mbox_file)
        total_hits = 0

        for msg in mbox:
            date_raw = msg.get("date", "")
            try:
                date = parsedate_to_datetime(date_raw).isoformat()
            except Exception:
                date = date_raw

            # From and To stay as the raw header text. They are address fields
            # that downstream steps parse, and decoding them here would rewrite
            # the display name inside an address list for no gain: nothing
            # matches against them.
            sender    = msg.get("from", "")
            recipient = msg.get("to", "")
            subject   = decode_header_value(msg.get("subject", ""))

            row_prefix = [date, sender, recipient, subject]

            # The subject is scanned as its own source. A lure that lives
            # entirely in the Subject header ("Urgent payment") never appears in
            # the body, so a body-only scan reports nothing for the message that
            # is doing the work.
            total_hits += scan_text(subject, "subject", row_prefix, writer,
                                    split_sentences=False)
            total_hits += scan_text(get_body(msg), "body", row_prefix, writer)

    print(f"Done. {total_hits:,} evidence hits written to {args.output_file}")
    print("Next step: run clean_evidence_csv.py to strip HTML from the exact_text column.")
