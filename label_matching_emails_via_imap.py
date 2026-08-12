"""Connects to an IMAP mailbox and applies a label or folder to messages whose participant addresses match configured domains.

label_matching_emails_via_imap.py
=================================
Project : email-evidence-tools
Purpose : Connects to an IMAP endpoint and labels messages that involve configured
          address domains. This makes a related email thread visible as a distinct
          folder/label inside the mail client.

          Two scan modes are available:
            fast, server-side IMAP SEARCH filters on From/Reply-To/To/Cc headers
                    containing configured domain fragments. Fast but may miss edge
                    cases where a domain appears only in unsupported headers.
            full, downloads and inspects every message in All Mail.  Slower but
                    exhaustive.

          The script is resumable: processed message UIDs are appended to a state
          file after each batch.  Re-running with resume=yes skips already-processed
          UIDs. The default state filename is derived from the host, mailbox, label
          and domain set, so a run against different targets does not inherit the
          UIDs of an unrelated one.

Transport: --ssl auto (the default) uses implicit TLS for every host except a
          local bridge on its own port, so credentials are never sent in the
          clear by accident. --ssl on forces TLS, --ssl off forces plaintext,
          and --starttls upgrades a plaintext connection in place.

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

import imaplib
import email
import hashlib
import os
import ssl
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
USE_SSL       = True      # implicit TLS (IMAP4_SSL)
USE_STARTTLS  = False     # plaintext socket upgraded in place
VERIFY_TLS    = True      # validate the server certificate chain and hostname

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
IMAPS_PORT  = 993


def split_domains(value: str) -> set:
    """Split a comma-separated domain list into normalized domain names."""
    return {item.strip().lower().lstrip("@") for item in value.split(",") if item.strip()}


def is_local_host(host: str) -> bool:
    """Return True if the host is a loopback address, i.e. a local mail bridge."""
    host = (host or "").strip().lower().strip("[]")
    return host in LOCAL_HOSTS or host.startswith("127.")


def resolve_transport(args) -> tuple:
    """Return (use_ssl, use_starttls) for the requested host, port, and --ssl mode.

    The default, auto, is what keeps credentials off the wire: it selects TLS for
    every destination except a loopback bridge on a non-IMAPS port. Plaintext to a
    remote server therefore never happens by accident, only when --ssl off says so.
    """
    if args.starttls:
        if args.ssl == "on":
            raise SystemExit("--starttls and --ssl on are mutually exclusive.")
        return False, True
    if args.ssl == "on":
        return True, False
    if args.ssl == "off":
        if not is_local_host(args.imap_host):
            print(
                f"WARNING: --ssl off sends the password to {args.imap_host} in "
                "the clear. Use --ssl on or --starttls unless this link is trusted."
            )
        return False, False
    # auto
    return not (is_local_host(args.imap_host) and args.imap_port != IMAPS_PORT), False


def default_state_file(host, port, mailbox, label, domains) -> str:
    """Derive a resume-state filename unique to this host, mailbox, label, and domain set.

    A single fixed filename made resume unsafe across runs: the UIDs recorded
    while labeling one mailbox marked messages as processed for a later run
    against a different mailbox or a different domain list, which then skipped
    them without ever inspecting them.
    """
    key = "|".join([str(host), str(port), str(mailbox), str(label), ",".join(sorted(domains))])
    return f"processed_uids_{hashlib.sha256(key.encode()).hexdigest()[:8]}.txt"


def tls_context(verify: bool = True) -> ssl.SSLContext:
    """Return the SSL context to use for TLS connections.

    This must be passed explicitly. Left to itself `imaplib` builds its context
    with `ssl._create_stdlib_context()`, for implicit TLS and for STARTTLS alike,
    and that context sets check_hostname=False and verify_mode=CERT_NONE. The
    connection is then encrypted but unauthenticated, which stops a passive
    listener and does nothing at all about an active one: any host that can
    answer for the address can present its own certificate, take the password,
    and proxy the session. `ssl.create_default_context()` verifies both the
    chain and the hostname.
    """
    if not verify:
        context = ssl._create_unverified_context()
        print(
            "WARNING: TLS certificate verification is disabled. The connection is "
            "encrypted but the server is not authenticated."
        )
        return context
    return ssl.create_default_context()


def connect() -> imaplib.IMAP4:
    """Open and authenticate an IMAP connection using the resolved transport."""
    if USE_SSL:
        imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=tls_context(VERIFY_TLS))
    else:
        imap = imaplib.IMAP4(IMAP_HOST, IMAP_PORT)
        if USE_STARTTLS:
            imap.starttls(ssl_context=tls_context(VERIFY_TLS))
    imap.login(IMAP_USER, IMAP_PASS)
    return imap


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
        default=os.getenv("STATE_FILE"),
        help="Resume state file path. Defaults to a name derived from the host, mailbox, label, and domains.",
    )
    parser.add_argument(
        "--ssl",
        choices=("auto", "on", "off"),
        default=os.getenv("IMAP_SSL", "auto"),
        help="Implicit TLS. auto (default) uses TLS everywhere except a local bridge.",
    )
    parser.add_argument(
        "--starttls",
        action="store_true",
        default=os.getenv("IMAP_STARTTLS", "").lower() in {"1", "true", "yes"},
        help="Connect in plaintext and upgrade with STARTTLS. Not valid with --ssl on.",
    )
    parser.add_argument(
        "--tls-no-verify",
        action="store_true",
        default=os.getenv("IMAP_TLS_NO_VERIFY", "").lower() in {"1", "true", "yes"},
        help="Skip certificate validation, for a bridge presenting a self-signed certificate.",
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
    """Copy a message UID into the TARGET_LABEL folder.

    The caller creates the folder and selects the mailbox once per run; doing
    either here meant an extra round trip to the server for every match.
    """
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
    imap = connect()
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
    imap = connect()
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

    imap = connect()
    ensure_folder(imap, TARGET_LABEL)
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
    STATE_FILE = cli_args.state_file or default_state_file(
        IMAP_HOST, IMAP_PORT, MAILBOX, TARGET_LABEL, TARGET_DOMAINS
    )
    DEBUG_MATCHES = cli_args.debug_matches
    USE_SSL, USE_STARTTLS = resolve_transport(cli_args)
    VERIFY_TLS = not cli_args.tls_no_verify
    print(
        f"Connecting to {IMAP_HOST}:{IMAP_PORT} "
        f"({'implicit TLS' if USE_SSL else 'STARTTLS' if USE_STARTTLS else 'plaintext'}), "
        f"state file {STATE_FILE}"
    )

    mode = cli_args.mode or input("Scan mode (full / fast): ").strip().lower()
    restart = cli_args.restart or input("Restart from scratch? (yes/no): ").strip().lower() == "yes"

    if restart:
        wipe_resume_file()
        print("State file cleared - starting fresh.")

    uids = fetch_uids_fast() if mode == "fast" else fetch_uids_full()
    process_uids(uids, resume=not restart)
