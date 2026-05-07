# === AI REVIEWER - READ BEFORE EDITING ==============================
# Before changing this file, read the master workspace README at
#   C:\Code\README.md   ("AI Session Rules" section)
# and the README(s) for this project and sub-product. Those documents
# are the single source of truth for venvs, path conventions,
# archive/backup rules, markdown conventions, and every repo-wide rule.
# Do not guess - reference the READMEs first.
# =====================================================================

"""
label_matching_emails_via_imap.py
=================================
Project : email-evidence-tools
Purpose : Connects to an IMAP endpoint and labels messages that involve configured
          address domains. This makes a related email thread visible as a distinct
          folder/label inside the mail client.

          Two scan modes are available:
            fast  — server-side IMAP SEARCH filters on From/Reply-To/To/Cc headers
                    containing configured domain fragments. Fast but may miss edge
                    cases where a domain appears only in unsupported headers.
            full  — downloads and inspects every message in All Mail.  Slower but
                    exhaustive.

          The script is resumable: processed message UIDs are appended to a state
          file after each batch.  Re-running with resume=yes skips already-processed
          UIDs.

Requirements:
    - IMAP endpoint. Local bridge defaults are supported through environment vars.
    - .env file in the working directory containing:
          IMAP_USER=<username>
          IMAP_PASS=<password>
          TARGET_DOMAINS=example.com,example.org
          TARGET_LABEL=Labels/Evidence
    - python-dotenv  (pip install python-dotenv)

Usage   : python label_matching_emails_via_imap.py --domains "example.com,example.org" --target-label "Labels/Evidence"
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
import argparse
from dotenv import load_dotenv
from email.utils import getaddresses

# =============================
# CONFIG
# =============================
load_dotenv()

IMAP_USER = None
IMAP_PASS = None
IMAP_HOST = None
IMAP_PORT = None
MAILBOX = None
TARGET_LABEL = None
TARGET_DOMAINS = set()

FETCH_BATCH_SIZE  = 10
STATE_FLUSH_EVERY = 100   # write state file after every N messages processed
PROGRESS_EVERY    = 250   # print progress every N messages scanned

STATE_FILE    = None
DEBUG_MATCHES = False     # set True to print each matched UID + subject


def split_domains(value: str) -> set:
    """Split a comma-separated domain list into normalized domain names."""
    return {item.strip().lower().lstrip("@") for item in value.split(",") if item.strip()}


def parse_args():
    """Parse command-line arguments and environment-variable fallbacks."""
    parser = argparse.ArgumentParser(
        description="Apply an IMAP label/folder to messages matching configured address domains."
    )
    parser.add_argument("--imap-host", default=os.getenv("IMAP_HOST", "127.0.0.1"))
    parser.add_argument("--imap-port", type=int, default=int(os.getenv("IMAP_PORT", "1143")))
    parser.add_argument("--imap-user", default=os.getenv("IMAP_USER"))
    parser.add_argument("--imap-pass", default=os.getenv("IMAP_PASS"))
    parser.add_argument("--mailbox", default=os.getenv("MAILBOX", '"All Mail"'))
    parser.add_argument("--target-label", default=os.getenv("TARGET_LABEL", "Labels/Evidence"))
    parser.add_argument(
        "--domains",
        default=os.getenv("TARGET_DOMAINS", ""),
        help="Comma-separated target domains, for example: example.com,example.org.",
    )
    parser.add_argument(
        "--state-file",
        default=os.getenv("STATE_FILE", "processed_uids_matching_domains.txt"),
        help="Resume state file path.",
    )
    parser.add_argument(
        "--mode",
        choices=("fast", "full"),
        default=os.getenv("SCAN_MODE"),
        help="Scan mode. If omitted, the script prompts.",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        default=os.getenv("RESTART_SCAN", "").lower() in {"1", "true", "yes"},
        help="Clear the state file before scanning.",
    )
    parser.add_argument(
        "--debug-matches",
        action="store_true",
        default=os.getenv("DEBUG_MATCHES", "").lower() in {"1", "true", "yes"},
        help="Print matched UID, domain, and subject.",
    )
    args = parser.parse_args()

    if not args.imap_user:
        parser.error("--imap-user is required unless IMAP_USER is set.")
    if not args.imap_pass:
        parser.error("--imap-pass is required unless IMAP_PASS is set.")

    domains = split_domains(args.domains)
    if not domains:
        parser.error("--domains is required unless TARGET_DOMAINS is set.")

    return args, domains

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


def message_matches_domains(msg) -> tuple[bool, str]:
    """
    Return (True, matched_domain) if any address in the message belongs to a
    configured target domain, otherwise (False, '').
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
    Use server-side SEARCH to pre-filter messages with target domains in
    address headers. Much faster than a full scan; may miss edge cases.
    """
    imap = imaplib.IMAP4(IMAP_HOST, IMAP_PORT)
    imap.login(IMAP_USER, IMAP_PASS)
    imap.select(MAILBOX, readonly=True)

    uids = set()
    headers = ("From", "Reply-To", "To", "Cc")
    for domain in sorted(TARGET_DOMAINS):
        token = f"@{domain}"
        for header in headers:
            _, data = imap.uid("SEARCH", None, f'(HEADER {header} "{token}")')
            if data and data[0]:
                uids.update(data[0].split())

    sorted_uids = sorted(uids, key=lambda value: int(value))

    imap.logout()
    print(f"FAST scan: {len(sorted_uids):,} candidate messages")
    return sorted_uids

# =============================
# PROCESSOR
# =============================

def process_uids(uids: list, resume: bool):
    """
    Iterate through UIDs, fetch each message, and apply the target label to any
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

        ok, reason = message_matches_domains(msg)
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
    print(f"Done. Scanned {scanned:,}, labeled {matched:,} as {TARGET_LABEL}")

# =============================
# MAIN
# =============================
if __name__ == "__main__":
    cli_args, cli_domains = parse_args()

    IMAP_USER = cli_args.imap_user
    IMAP_PASS = cli_args.imap_pass
    IMAP_HOST = cli_args.imap_host
    IMAP_PORT = cli_args.imap_port
    MAILBOX = cli_args.mailbox
    TARGET_LABEL = cli_args.target_label
    TARGET_DOMAINS = cli_domains
    STATE_FILE = cli_args.state_file
    DEBUG_MATCHES = cli_args.debug_matches

    mode = cli_args.mode or input("Scan mode (full / fast): ").strip().lower()
    restart = cli_args.restart or input("Restart from scratch? (yes/no): ").strip().lower() == "yes"

    if restart:
        wipe_resume_file()
        print("State file cleared - starting fresh.")

    uids = fetch_uids_fast() if mode == "fast" else fetch_uids_full()
    process_uids(uids, resume=not restart)
