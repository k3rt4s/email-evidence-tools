"""
extract_messages_by_address.py
===============================
Project : email-evidence-tools
Purpose : Stream-scan one or more mbox files and extract every message in which
          a given email address appears in From, To, Cc, Bcc, Reply-To, Sender,
          or Delivered-To. Writes a filtered .mbox plus an index CSV. Designed
          for very large Thunderbird/Gmail "All Mail" archives (tens of GB),
          so it uses a line-streaming parser instead of mailbox.mbox to avoid
          building a full table of contents up front. Supports resume-on-failure
          via a byte-offset checkpoint.

Match   : case-insensitive substring match of --address against the bare email
          parts of the participant headers above.

Dedup   : matched messages are deduped by Message-ID across all input mboxes
          (helpful when scanning both Gmail's "All Mail" and "Sent", which
          overlap). Messages missing a Message-ID are kept and tagged.

Inputs  : --mbox-file PATH [PATH ...]   one or more mbox files to scan
          --address    user@example.com  address to match (case-insensitive)
          --output-dir DIR              output directory (default derived,
                                        see "Outputs" below)

Outputs : Under <output-dir> (default
          C:\\Code_data\\email-evidence-tools\\extracts\\<slug>_<utc-ts>\\):
              <slug>.mbox       - filtered messages, mbox format
              <slug>_index.csv  - date, from, to, cc, subject, message-id,
                                  source-mbox, byte-offset
              extract.log       - progress + summary
              checkpoint.json   - resume marker (auto-managed)

Resume  : re-run with the same --output-dir to continue from the last
          fully-processed message. Delete checkpoint.json to force a fresh run.

Usage   : C:\\Code\\venvs\\email-evidence-tools\\Scripts\\python.exe \\
              .\\extract_messages_by_address.py \\
              --mbox-file "D:\\Thunderbird\\dwsyiiuk.default-release\\ImapMail\\127.0.0-1.1\\All Mail" \\
              --address   "someone@example.com"
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path

PROGRESS_EVERY_MESSAGES = 5_000
PROGRESS_EVERY_BYTES    = 500 * 1024 * 1024  # 500 MB
CHECKPOINT_EVERY        = 1_000              # messages between checkpoint flushes
DEFAULT_OUTPUT_ROOT     = Path(r"C:\Code_data\email-evidence-tools\extracts")

# mbox separator: a line at start-of-line beginning with literal "From " followed
# by at least one non-space character. In-body "From " lines are escaped to
# ">From " in well-formed mbox files, so unescaped "From " at column 0 is safe.
FROM_SEP_RE = re.compile(rb"^From [^\s]", re.MULTILINE)

PARTICIPANT_HEADERS = (
    "from", "to", "cc", "bcc",
    "reply-to", "sender", "delivered-to",
)


def slugify(address: str) -> str:
    local = address.split("@", 1)[0]
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", local).strip("_") or "extract"


def parse_args():
    ap = argparse.ArgumentParser(
        description="Extract mbox messages where a given address appears as a participant."
    )
    ap.add_argument(
        "--mbox-file", nargs="+", required=True,
        help="One or more mbox files to scan (space-separated; quote paths with spaces).",
    )
    ap.add_argument(
        "--address", required=True,
        help="Email address to match (case-insensitive substring).",
    )
    ap.add_argument(
        "--output-dir", default=None,
        help=(
            "Output directory. Defaults to "
            r"C:\Code_data\email-evidence-tools\extracts\<slug>_<utc-ts>\."
        ),
    )
    return ap.parse_args()


def open_csv_for_append(path: Path):
    """Open the index CSV in append mode, writing the header if the file is new."""
    is_new = not path.exists() or path.stat().st_size == 0
    f = path.open("a", newline="", encoding="utf-8")
    w = csv.writer(f)
    if is_new:
        w.writerow([
            "date_iso", "date_raw", "from", "to", "cc",
            "subject", "message_id", "source_mbox", "byte_offset",
        ])
    return f, w


def addrs_of(msg, *header_names):
    """Return a list of lowercased bare-email addresses parsed from the given headers."""
    raw = []
    for h in header_names:
        for v in msg.get_all(h, []):
            raw.append(v)
    return [a.lower() for _name, a in getaddresses(raw) if a]


def header_str(msg, name):
    """Return a single header value as a string (concatenated if multiple), or ""."""
    vals = msg.get_all(name, [])
    if not vals:
        return ""
    return " ".join(str(v).replace("\r\n", " ").replace("\n", " ").strip() for v in vals)


def iter_mbox_messages(mbox_path: Path, start_offset: int = 0):
    """
    Yield (start_offset, raw_bytes) for each message in an mbox file.

    Streams the file rather than loading it whole. Uses the unix `From ` separator
    at line start to mark message boundaries. The first separator at the head of
    the file marks the start of message 0; the next separator marks its end.

    Resumes cleanly from start_offset, which MUST be the start byte of a "From "
    separator line (the checkpoint records exactly that).
    """
    with mbox_path.open("rb") as f:
        f.seek(start_offset)

        buf = bytearray()
        msg_start = start_offset
        in_message = False

        # Read in 4 MB chunks. Large enough to amortize syscalls, small enough
        # to not balloon memory for pathologically large messages.
        CHUNK = 4 * 1024 * 1024

        # When resuming at offset 0 (or any "From " line), the first thing we
        # read should be that separator. We yield once we see the NEXT separator.
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                break
            buf.extend(chunk)

            while True:
                # Find a "From " line at column 0 within buf.
                # We search starting from position 1 (so the leading separator
                # that begins the current message is not re-matched).
                search_start = 0 if not in_message else 1
                m = FROM_SEP_RE.search(buf, search_start)
                if not m:
                    break
                sep_pos = m.start()
                if not in_message:
                    # First separator we ever saw: it begins message 0. Drop
                    # anything before it (should be empty for a well-formed
                    # mbox) and start the message.
                    if sep_pos > 0:
                        del buf[:sep_pos]
                        msg_start += sep_pos
                    in_message = True
                    continue
                # We have a complete message: buf[0:sep_pos]
                raw = bytes(buf[:sep_pos])
                yield msg_start, raw
                # Advance: discard the consumed bytes, slide msg_start forward.
                del buf[:sep_pos]
                msg_start += sep_pos
                # in_message stays True; loop continues searching for next sep.

        # End of file: emit final message if we were inside one.
        if in_message and buf:
            yield msg_start, bytes(buf)


def address_matches(msg, needle_lower: str) -> bool:
    for a in addrs_of(msg, *PARTICIPANT_HEADERS):
        if needle_lower in a:
            return True
    return False


def write_mbox_message(out_fh, raw: bytes):
    """Append a raw message (already containing its `From ` separator line) to the output mbox."""
    # The streamed `raw` always begins with a `From ...` line, so we can write it directly.
    # Ensure the message ends with exactly one blank line before the next separator.
    if not raw.endswith(b"\n"):
        raw = raw + b"\n"
    if not raw.endswith(b"\n\n"):
        raw = raw + b"\n"
    out_fh.write(raw)


def load_checkpoint(path: Path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_checkpoint(path: Path, data: dict, max_attempts: int = 6):
    """Atomic-replace via a temp file. Retries on Windows file-lock contention
    (antivirus / search indexer / cloud sync briefly holding the target)."""
    tmp = path.with_suffix(".json.tmp")
    payload = json.dumps(data, indent=2)
    last_err = None
    for attempt in range(max_attempts):
        try:
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(path)
            return
        except PermissionError as e:
            last_err = e
            time.sleep(0.5 * (2 ** attempt))  # 0.5, 1, 2, 4, 8, 16 s
    # Last-ditch: write directly without atomic rename, so the run can keep going.
    try:
        path.write_text(payload, encoding="utf-8")
    except Exception:
        raise last_err


def fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def main():
    args = parse_args()
    needle = args.address.strip().lower()
    if "@" not in needle:
        sys.exit("--address must look like an email address")

    slug = slugify(args.address)

    if args.output_dir:
        out_dir = Path(args.output_dir)
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = DEFAULT_OUTPUT_ROOT / f"{slug}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    out_mbox_path = out_dir / f"{slug}.mbox"
    index_csv_path = out_dir / f"{slug}_index.csv"
    log_path       = out_dir / "extract.log"
    checkpoint_path = out_dir / "checkpoint.json"

    checkpoint = load_checkpoint(checkpoint_path)
    seen_message_ids = set(checkpoint.get("seen_message_ids", []))
    file_state = checkpoint.get("files", {})

    parser = BytesParser(policy=policy.compat32)

    def log(line: str):
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        print(f"[{ts}] {line}", flush=True)
        with log_path.open("a", encoding="utf-8") as lf:
            lf.write(f"[{ts}] {line}\n")

    log("=" * 72)
    log(f"extract_messages_by_address.py starting")
    log(f"  address     : {args.address}")
    log(f"  output dir  : {out_dir}")
    log(f"  mbox inputs : {len(args.mbox_file)}")
    for p in args.mbox_file:
        log(f"                {p}")

    # Open outputs in append mode so resume keeps prior writes.
    out_fh, _ = (out_mbox_path.open("ab"), None)
    csv_fh, csv_w = open_csv_for_append(index_csv_path)

    total_matched = checkpoint.get("total_matched", 0)
    total_scanned = checkpoint.get("total_scanned", 0)

    try:
        for mbox_file in args.mbox_file:
            mbox_path = Path(mbox_file)
            if not mbox_path.exists():
                log(f"SKIP missing: {mbox_path}")
                continue

            fkey = str(mbox_path.resolve())
            state = file_state.get(fkey, {})
            start_offset = state.get("next_offset", 0)
            file_size = mbox_path.stat().st_size

            if start_offset >= file_size:
                log(f"already complete: {mbox_path.name} ({fmt_bytes(file_size)})")
                continue

            log(
                f"scanning {mbox_path.name}  "
                f"({fmt_bytes(file_size)}, resume at byte {start_offset:,})"
            )

            t0 = time.time()
            last_progress_msgs  = 0
            last_progress_bytes = start_offset
            file_scanned_msgs = state.get("scanned", 0)
            file_matched_msgs = state.get("matched", 0)

            for msg_offset, raw in iter_mbox_messages(mbox_path, start_offset):
                total_scanned += 1
                file_scanned_msgs += 1

                # Parse headers only (cheap): feed the raw message to the parser.
                # The first line is the `From ` separator, which BytesParser
                # tolerates as a header-like prefix, but to be safe we strip it.
                nl = raw.find(b"\n")
                hdr_bytes = raw[nl + 1:] if nl != -1 else raw
                try:
                    msg = parser.parsebytes(hdr_bytes, headersonly=True)
                except Exception as e:
                    log(f"  parse error at offset {msg_offset:,}: {e!r} - skipping")
                    continue

                if not address_matches(msg, needle):
                    pass
                else:
                    mid = (msg.get("message-id") or "").strip()
                    if mid and mid in seen_message_ids:
                        pass  # already extracted from a prior input file
                    else:
                        # parse the full body too so we keep the message intact
                        write_mbox_message(out_fh, raw)
                        if mid:
                            seen_message_ids.add(mid)
                        # populate index row
                        date_raw = header_str(msg, "date")
                        try:
                            dt = parsedate_to_datetime(date_raw)
                            date_iso = dt.isoformat() if dt else ""
                        except Exception:
                            date_iso = ""
                        csv_w.writerow([
                            date_iso,
                            date_raw,
                            header_str(msg, "from"),
                            header_str(msg, "to"),
                            header_str(msg, "cc"),
                            header_str(msg, "subject"),
                            mid,
                            mbox_path.name,
                            msg_offset,
                        ])
                        total_matched += 1
                        file_matched_msgs += 1

                # progress
                if (total_scanned - last_progress_msgs) >= PROGRESS_EVERY_MESSAGES \
                   or (msg_offset - last_progress_bytes) >= PROGRESS_EVERY_BYTES:
                    elapsed = time.time() - t0
                    rate = file_scanned_msgs / elapsed if elapsed > 0 else 0
                    pct = (msg_offset / file_size * 100) if file_size else 100
                    log(
                        f"  {mbox_path.name}: scanned {file_scanned_msgs:,}, "
                        f"matched {file_matched_msgs:,}, "
                        f"{pct:5.1f}% ({fmt_bytes(msg_offset)}/{fmt_bytes(file_size)}), "
                        f"{rate:.0f} msg/s"
                    )
                    last_progress_msgs  = total_scanned
                    last_progress_bytes = msg_offset

                # checkpoint
                if total_scanned % CHECKPOINT_EVERY == 0:
                    out_fh.flush()
                    csv_fh.flush()
                    file_state[fkey] = {
                        "next_offset": msg_offset + len(raw),
                        "scanned": file_scanned_msgs,
                        "matched": file_matched_msgs,
                    }
                    save_checkpoint(checkpoint_path, {
                        "files": file_state,
                        "seen_message_ids": sorted(seen_message_ids),
                        "total_matched": total_matched,
                        "total_scanned": total_scanned,
                        "updated": datetime.now(timezone.utc).isoformat(),
                    })

            # End of this mbox - mark fully complete.
            out_fh.flush()
            csv_fh.flush()
            file_state[fkey] = {
                "next_offset": file_size,
                "scanned": file_scanned_msgs,
                "matched": file_matched_msgs,
                "completed": True,
            }
            save_checkpoint(checkpoint_path, {
                "files": file_state,
                "seen_message_ids": sorted(seen_message_ids),
                "total_matched": total_matched,
                "total_scanned": total_scanned,
                "updated": datetime.now(timezone.utc).isoformat(),
            })
            log(
                f"finished {mbox_path.name}: scanned {file_scanned_msgs:,}, "
                f"matched {file_matched_msgs:,}"
            )
    finally:
        out_fh.close()
        csv_fh.close()

    log(
        f"DONE. total scanned={total_scanned:,}, total matched={total_matched:,}, "
        f"unique message-ids stored={len(seen_message_ids):,}"
    )
    log(f"mbox  : {out_mbox_path}")
    log(f"index : {index_csv_path}")


if __name__ == "__main__":
    main()
