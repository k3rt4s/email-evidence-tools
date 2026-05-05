# === AI REVIEWER - READ BEFORE EDITING ==============================
# Before changing this file, read the master workspace README at
#   C:\Code\README.md   ("AI Session Rules" section)
# and the README(s) for this project and sub-product. Those documents
# are the single source of truth for venvs, path conventions,
# archive/backup rules, markdown conventions, and every repo-wide rule.
# Do not guess - reference the READMEs first.
# =====================================================================

"""
label_cr_emails_via_imap.py
============================
Project : Crosier_Bowker — Legal Evidence Review
Case    : Tennessee Board of Professional Responsibility, Complaint No. 105302-2026-CAP
Purpose : Connects to a local ProtonMail Bridge IMAP endpoint and labels all messages
          that involve Crosier-related email domains under a dedicated IMAP label
          ("Labels/CR").  This makes the relevant email thread visible as a distinct
          folder/label inside Proton Mail or any connected IMAP client.

          Two scan modes are available:
            fast  — server-side IMAP SEARCH filters on From/Reply-To/To/Cc headers
                    containing "@crosier".  Fast but may miss edge cases where the
                    domain appears only in a Cc or BCC field spelled differently.
            full  — downloads and inspects every message in All Mail.  Slower but
                    exhaustive.

          The script is resumable: processed message UIDs are appended to a state
          file after each batch.  Re-running with resume=yes skips already-processed
          UIDs.

Requirements:
    - ProtonMail Bridge running locally (default: 127.0.0.1:1143)
    - .env file in the working directory containing:
          IMAP_USER=<bridge username>
          IMAP_PASS=<bridge password>
    - python-dotenv  (pip install python-dotenv)

Usage   : python label_cr_emails_via_imap.py
          → prompts for mode (full / fast) and whether to restart from scratch

Author  : Jonathan David Bowker
Created : 2025-12-29
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

import imaplib
import email
import os
import time
from dotenv import load_dotenv
from email.utils import getaddresses

# =============================
# CONFIG
# =============================
load_dotenv()

IMAP_USER = os.getenv("IMAP_USER")
IMAP_PASS = os.getenv("IMAP_PASS")
IMAP_HOST = "127.0.0.1"
IMAP_PORT = 1143

MAILBOX = '"All Mail"'

LABEL_PREFIX = "Labels/"
TARGET_LABEL = LABEL_PREFIX + "CR"  # IMAP folder that acts as the CR label

# Domains whose messages should be labeled
TARGET_DOMAINS = {
    "crosierhudson.com",
    "crosierfamilylaw.com",
    "mycase.com",
}

FETCH_BATCH_SIZE  = 10
STATE_FLUSH_EVERY = 100   # write state file after every N messages processed
PROGRESS_EVERY    = 250   # print progress every N messages scanned

STATE_FILE    = "processed_uids_cr.txt"
DEBUG_MATCHES = False     # set True to print each matched UID + subject

# =============================
# RESUME HELPERS
# =============================

def load_processed_uids() -> set:
    """Return the set of UIDs already processed in a prior run."""
    if not os.path.exists(STATE_FILE):
        return set()
    with open(STATE_FILE, "r") as f:
        return set(line.strip() for line in f if line.strip())


def save_processed_uids(uids: list):
    """Append a batch of UIDs to the state file."""
    if not uids:
        return
    with open(STATE_FILE, "a") as f:
        for uid in uids:
            f.write(uid + "\n")


def wipe_resume_file():
    """Delete the state file to force a clean restart."""
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)

# =============================
# LABEL HELPERS
# =============================

def ensure_folder(imap, folder: str):
    """Create the IMAP folder/label if it does not already exist."""
    try:
        imap.create(folder)
    except Exception:
        pass  # folder already exists


def apply_label(imap, uid: bytes):
    """Copy a message UID into the TARGET_LABEL folder."""
    ensure_folder(imap, TARGET_LABEL)
    imap.select(MAILBOX, readonly=False)
    imap.uid("COPY", uid, TARGET_LABEL)

# =============================
# DOMAIN EXTRACTION
# =============================

def extract_domains(msg) -> set:
    """
    Parse From, Reply-To, To, and Cc headers and return the set of
    sender/recipient domains found in the message.
    """
    domains = set()
    headers = []
    for h in ("From", "Reply-To", "To", "Cc"):
        v = msg.get(h)
        if v:
            headers.append(v)

    for _name, addr in getaddresses(headers):
        addr = addr.lower()
        if "@" not in addr:
            continue
        domain = addr.split("@", 1)[1].strip(" >")
        if domain:
            domains.add(domain)

    return domains


def message_is_cr(msg) -> tuple[bool, str]:
    """
    Return (True, matched_domain) if any address in the message belongs to a
    Crosier-related domain, otherwise (False, '').
    """
    domains = extract_domains(msg)
    for d in domains:
        if d in TARGET_DOMAINS:
            return True, d
    return False, ""

# =============================
# UID FETCHERS
# =============================

def fetch_uids_full() -> list:
    """Retrieve ALL message UIDs from the mailbox (exhaustive scan)."""
    imap = imaplib.IMAP4(IMAP_HOST, IMAP_PORT)
    imap.login(IMAP_USER, IMAP_PASS)
    imap.select(MAILBOX, readonly=True)

    _, data = imap.uid("SEARCH", None, "ALL")
    uids = data[0].split()

    imap.logout()
    print(f"FULL scan: {len(uids):,} messages to process")
    return uids


def fetch_uids_fast() -> list:
    """
    Use server-side SEARCH to pre-filter messages with '@crosier' in any
    address header.  Much faster than a full scan; may miss a small number
    of edge cases.
    """
    imap = imaplib.IMAP4(IMAP_HOST, IMAP_PORT)
    imap.login(IMAP_USER, IMAP_PASS)
    imap.select(MAILBOX, readonly=True)

    search = (
        '(OR '
        '(HEADER From "@crosier") '
        '(HEADER Reply-To "@crosier") '
        '(HEADER To "@crosier") '
        '(HEADER Cc "@crosier")'
        ')'
    )

    _, data = imap.uid("SEARCH", None, search)
    uids = data[0].split()

    imap.logout()
    print(f"FAST scan: {len(uids):,} candidate messages")
    return uids

# =============================
# PROCESSOR
# =============================

def process_uids(uids: list, resume: bool):
    """
    Iterate through UIDs, fetch each message, and apply the CR label to any
    that match TARGET_DOMAINS.  Writes progress to the state file for resumability.
    """
    processed = load_processed_uids()
    total = len(uids)

    imap = imaplib.IMAP4(IMAP_HOST, IMAP_PORT)
    imap.login(IMAP_USER, IMAP_PASS)
    imap.select(MAILBOX, readonly=False)

    scanned = matched = 0
    buffer  = []
    start   = time.time()

    for uid_bytes in uids:
        uid = uid_bytes.decode()
        if resume and uid in processed:
            continue  # skip already-handled UIDs

        res, data = imap.uid("FETCH", uid, "(RFC822)")
        if res != "OK" or not data or not data[0]:
            continue

        msg = email.message_from_bytes(data[0][1])

        ok, reason = message_is_cr(msg)
        if ok:
            apply_label(imap, uid)
            matched += 1
            if DEBUG_MATCHES:
                print(f"MATCH uid={uid} domain={reason} subject={msg.get('Subject', '')}")

        scanned += 1
        buffer.append(uid)

        if scanned % STATE_FLUSH_EVERY == 0:
            save_processed_uids(buffer)
            buffer.clear()

        if scanned % PROGRESS_EVERY == 0:
            rate = scanned / (time.time() - start)
            print(f"{scanned:,}/{total:,} scanned | {matched:,} matched | {rate:.1f} msg/sec")

    save_processed_uids(buffer)  # flush remaining buffer
    imap.logout()
    print(f"Done. Scanned {scanned:,}, labeled {matched:,} as CR")

# =============================
# MAIN
# =============================
if __name__ == "__main__":
    mode    = input("Scan mode (full / fast): ").strip().lower()
    restart = input("Restart from scratch? (yes/no): ").strip().lower() == "yes"

    if restart:
        wipe_resume_file()
        print("State file cleared — starting fresh.")

    uids = fetch_uids_fast() if mode == "fast" else fetch_uids_full()
    process_uids(uids, resume=not restart)
