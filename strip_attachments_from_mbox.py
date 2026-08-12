"""Creates an attachment-free copy of an mbox archive and writes a SHA-256 inventory CSV of every stripped attachment.

strip_attachments_from_mbox.py
===============================
Project : email-evidence-tools
Purpose : Creates a clean, attachment-free copy of an mbox archive for faster scanning
          and smaller file sizes.  For every message, any part with a Content-Disposition
          of "attachment" or a recognized filename is removed; the remaining text/inline
          parts are preserved, along with the MIME container structure around them.
          A separate CSV inventory of all stripped attachments (filename, size, SHA-256
          hash, message metadata) is written for the record.

          The script is resumable: it records the message index and the exact byte
          length of both outputs after each message, so an interrupted run (e.g. a
          network drive disconnect) resumes without duplicating or losing rows.

Input   : --input-mbox or MBOX_INPUT_PATH
Output  : OUTPUT_MBOX, <INPUT_MBOX>_NO_ATTACHMENTS  (new mbox file)
          ATTACHMENT_CSV, attachments_inventory.csv
          CHECKPOINT_FILE, strip_attachments.checkpoint  (auto-managed, safe to delete)

Usage   : python strip_attachments_from_mbox.py --input-mbox "<path-to-export.mbox>"

Note    : Output paths are derived automatically from the input unless you
          override them with command-line arguments or environment variables.
          The output mbox is a re-serialization, not a byte copy, so its message
          bytes do not hash to the same digests as the source.
"""

import os
import time
import csv
import json
import hashlib
import mailbox
import argparse
from pathlib import Path
from email.parser import BytesParser
from email.generator import BytesGenerator
from email import policy
from io import BytesIO

RETRY_DELAY    = 5    # seconds to wait when a drive I/O error occurs
PROGRESS_EVERY = 500  # print progress every N messages

# compat32 is the least opinionated policy for legacy/mixed-encoding messages
PARSER = BytesParser(policy=policy.compat32)

INVENTORY_FIELDS = ["Message-ID", "Date", "From", "To", "Filename", "Size", "SHA256"]

INPUT_MBOX = None
OUTPUT_MBOX = None
ATTACHMENT_CSV = None
CHECKPOINT_FILE = None

# =============================
# HELPERS
# =============================

def sha256_bytes(data: bytes) -> str:
    """Return the hex SHA-256 digest of a byte string."""
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def wait_for_parent(path: Path):
    """Block until the parent directory of `path` exists (handles drive reconnects)."""
    while not path.parent.exists():
        print(f"Waiting for drive to become available: {path.parent}")
        time.sleep(RETRY_DELAY)


def load_checkpoint() -> dict:
    """Return the resume state: last message index plus the byte length of each output.

    The byte lengths are what make resume exact. Without them a run that died
    between writing a message and recording it re-emits every message written
    since the last flush, so the output mbox and the inventory both gain
    duplicates that nothing downstream can tell apart from real ones.
    """
    empty = {"last_index": 0, "mbox_bytes": 0, "csv_bytes": 0}
    if not CHECKPOINT_FILE.exists():
        return empty
    try:
        raw = CHECKPOINT_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return empty
    try:
        state = json.loads(raw)
        if isinstance(state, dict) and "last_index" in state:
            return {**empty, **state}
    except json.JSONDecodeError:
        pass
    # A bare integer is a checkpoint from before byte lengths were recorded.
    # It cannot be resumed exactly, so start over rather than risk duplicates.
    if raw.isdigit() and int(raw) > 0:
        print(
            f"Checkpoint {CHECKPOINT_FILE.name} predates exact resume and carries no "
            "output byte lengths; starting fresh to avoid duplicate records."
        )
    return empty


def save_checkpoint(index: int, mbox_bytes: int, csv_bytes: int):
    """Persist the message index and both output lengths so the run can be resumed exactly."""
    CHECKPOINT_FILE.write_text(
        json.dumps({"last_index": index, "mbox_bytes": mbox_bytes, "csv_bytes": csv_bytes}),
        encoding="utf-8",
    )


def is_attachment_part(part) -> bool:
    """
    Return True if this MIME part should be treated as an attachment.

    Attachment detection is intentionally broad: some email clients mark
    attachments as 'inline' but still include a filename, so we check both
    Content-Disposition and the presence of a filename parameter.
    """
    disp     = (part.get("Content-Disposition") or "").lower()
    filename = part.get_filename()
    if "attachment" in disp:
        return True
    if filename:
        return True
    return False


def prune_attachments(part, record) -> bool:
    """Recursively remove attachment parts, keeping the container structure intact.

    Returns True when the part should be kept. `record` is called with each
    removed part.

    The flat alternative, walking the message and re-attaching the surviving
    leaves at the top level, silently destroys nesting: a multipart/mixed that
    wraps a multipart/alternative comes back with the plain and HTML versions as
    siblings, so a reader renders both instead of choosing one and the evidence
    copy no longer reads like the message that was sent.
    """
    if part.get_content_maintype() == "multipart":
        kept = [child for child in part.get_payload() if prune_attachments(child, record)]
        part.set_payload(kept)
        return bool(kept)
    if is_attachment_part(part):
        record(part)
        return False
    return True


def parse_args():
    """Parse command-line arguments and environment-variable fallbacks."""
    parser = argparse.ArgumentParser(
        description="Create an attachment-free copy of an mbox archive."
    )
    parser.add_argument(
        "--input-mbox",
        default=os.getenv("MBOX_INPUT_PATH"),
        help="Path to the source .mbox file or mbox-format folder. Defaults to MBOX_INPUT_PATH.",
    )
    parser.add_argument(
        "--output-mbox",
        default=os.getenv("OUTPUT_MBOX"),
        help="Output mbox path. Defaults to <input>_NO_ATTACHMENTS.",
    )
    parser.add_argument(
        "--attachment-csv",
        default=os.getenv("ATTACHMENT_CSV"),
        help="Attachment inventory CSV path. Defaults to attachments_inventory.csv beside the input.",
    )
    parser.add_argument(
        "--checkpoint-file",
        default=os.getenv("CHECKPOINT_FILE"),
        help="Checkpoint path. Defaults to strip_attachments.checkpoint beside the input.",
    )
    args = parser.parse_args()
    if not args.input_mbox:
        parser.error("--input-mbox is required unless MBOX_INPUT_PATH is set.")

    input_mbox = Path(args.input_mbox)
    output_mbox = Path(args.output_mbox) if args.output_mbox else input_mbox.with_name(input_mbox.name + "_NO_ATTACHMENTS")
    attachment_csv = Path(args.attachment_csv) if args.attachment_csv else input_mbox.with_name("attachments_inventory.csv")
    checkpoint_file = Path(args.checkpoint_file) if args.checkpoint_file else input_mbox.with_name("strip_attachments.checkpoint")
    return input_mbox, output_mbox, attachment_csv, checkpoint_file


def count_inventory_rows(path: Path) -> int:
    """Return the number of data rows in the inventory CSV, header excluded."""
    if not path.exists():
        return 0
    with path.open("r", newline="", encoding="utf-8") as f:
        return max(sum(1 for _ in csv.reader(f)) - 1, 0)


# =============================
# MAIN
# =============================
if __name__ == "__main__":
    INPUT_MBOX, OUTPUT_MBOX, ATTACHMENT_CSV, CHECKPOINT_FILE = parse_args()

    state     = load_checkpoint()
    last_done = state["last_index"]
    resume_ok = last_done > 0 and OUTPUT_MBOX.exists()

    if resume_ok:
        # Roll both outputs back to their last recorded length, discarding any
        # partial tail the interrupted run left behind, then append from there.
        os.truncate(OUTPUT_MBOX, state["mbox_bytes"])
        if ATTACHMENT_CSV.exists():
            os.truncate(ATTACHMENT_CSV, state["csv_bytes"])
        print(f"Resuming from message {last_done + 1}, appending to existing output.")
    else:
        # Fresh start, remove any stale outputs to avoid accidental duplication
        if OUTPUT_MBOX.exists():
            OUTPUT_MBOX.unlink()
        if ATTACHMENT_CSV.exists():
            ATTACHMENT_CSV.unlink()
        last_done = 0
        print("Starting fresh - output will be written from scratch.")

    inbox = mailbox.mbox(INPUT_MBOX)

    with open(OUTPUT_MBOX, "ab") as out_f, \
         open(ATTACHMENT_CSV, "a", newline="", encoding="utf-8") as csv_f:

        writer = csv.DictWriter(csv_f, fieldnames=INVENTORY_FIELDS)
        if os.fstat(csv_f.fileno()).st_size == 0:
            writer.writeheader()
            csv_f.flush()

        stripped_this_run = 0

        for i, msg in enumerate(inbox, start=1):
            if i <= last_done:
                continue  # already processed in a previous run

            if i % PROGRESS_EVERY == 0:
                print(f"Processed {i:,} messages...")

            raw    = msg.as_bytes()
            parsed = PARSER.parsebytes(raw)

            # Strip attachments; keep every other part, and the containers holding them
            pending_rows = []

            def record(part, _parsed=parsed, _rows=pending_rows):
                payload = part.get_payload(decode=True) or b""
                _rows.append({
                    "Message-ID": _parsed.get("Message-ID"),
                    "Date"      : _parsed.get("Date"),
                    "From"      : _parsed.get("From"),
                    "To"        : _parsed.get("To"),
                    "Filename"  : part.get_filename(),
                    "Size"      : len(payload),
                    "SHA256"    : sha256_bytes(payload),
                })

            if parsed.is_multipart():
                prune_attachments(parsed, record)

            # Serialize with minimal rewriting, then write the mbox separator + message
            buffer = BytesIO()
            gen    = BytesGenerator(buffer, mangle_from_=True, policy=policy.compat32)
            gen.flatten(parsed)
            msg_bytes = buffer.getvalue()

            # Where both outputs stood before this message. A retry rewinds to
            # here first: the message bytes and the inventory rows are one unit,
            # so a failure partway through must not leave half of it behind to be
            # written again on the next attempt.
            mbox_mark = os.fstat(out_f.fileno()).st_size
            csv_mark  = os.fstat(csv_f.fileno()).st_size

            written = False
            while not written:
                try:
                    wait_for_parent(OUTPUT_MBOX)
                    # Start every attempt from the mark, so a half-written
                    # message from a failed one is discarded rather than
                    # duplicated. Both handles are in append mode, so the
                    # truncate is what matters and the seek is belt and braces.
                    out_f.truncate(mbox_mark)
                    out_f.seek(mbox_mark)
                    csv_f.truncate(csv_mark)
                    csv_f.seek(csv_mark)
                    out_f.write(b"From nobody Thu Jan 01 00:00:00 1970\n")
                    out_f.write(msg_bytes)
                    out_f.write(b"\n")
                    out_f.flush()
                    # The inventory row and the message it came from have to land
                    # before the checkpoint that covers them, or a crash in between
                    # loses the record of an attachment that is already gone from
                    # the output.
                    writer.writerows(pending_rows)
                    csv_f.flush()
                    save_checkpoint(
                        i,
                        os.fstat(out_f.fileno()).st_size,
                        os.fstat(csv_f.fileno()).st_size,
                    )
                    written = True
                except OSError as e:
                    print(f"I/O error at message {i}: {e} - retrying in {RETRY_DELAY}s...")
                    time.sleep(RETRY_DELAY)

            stripped_this_run += len(pending_rows)

    total_attachments = count_inventory_rows(ATTACHMENT_CSV)
    print(f"Attachment inventory: {ATTACHMENT_CSV}  ({total_attachments:,} items, "
          f"{stripped_this_run:,} this run)")
    print("Done.")
    print(f"Output MBOX      : {OUTPUT_MBOX}")
    print(f"Checkpoint file  : {CHECKPOINT_FILE}")
