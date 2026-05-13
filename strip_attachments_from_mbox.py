"""
strip_attachments_from_mbox.py
===============================
Project : email-evidence-tools
Purpose : Creates a clean, attachment-free copy of an mbox archive for faster scanning
          and smaller file sizes.  For every message, any part with a Content-Disposition
          of "attachment" or a recognized filename is removed; the remaining text/inline
          parts are preserved.  A separate CSV inventory of all stripped attachments
          (filename, size, SHA-256 hash, message metadata) is written for the record.

          The script is resumable: it writes a checkpoint file after each message so that
          if it is interrupted (e.g. by a network drive disconnect), it can pick up where
          it left off rather than starting over.

Input   : --input-mbox or MBOX_INPUT_PATH
Output  : OUTPUT_MBOX      — <INPUT_MBOX>_NO_ATTACHMENTS  (new mbox file)
          ATTACHMENT_CSV   — attachments_inventory.csv
          CHECKPOINT_FILE  — strip_attachments.checkpoint  (auto-managed, safe to delete)

Usage   : python strip_attachments_from_mbox.py --input-mbox "<path-to-export.mbox>"

Note    : Output paths are derived automatically from the input unless you
          override them with command-line arguments or environment variables.
"""

import os
import time
import csv
import hashlib
import email
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


def load_checkpoint() -> int:
    """Return the index of the last successfully processed message (0 = none)."""
    if CHECKPOINT_FILE.exists():
        try:
            return int(CHECKPOINT_FILE.read_text(encoding="utf-8").strip())
        except Exception:
            return 0
    return 0


def save_checkpoint(i: int):
    """Persist the current message index so the run can be resumed."""
    CHECKPOINT_FILE.write_text(str(i), encoding="utf-8")


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


# =============================
# MAIN
# =============================
if __name__ == "__main__":
    INPUT_MBOX, OUTPUT_MBOX, ATTACHMENT_CSV, CHECKPOINT_FILE = parse_args()

    last_done  = load_checkpoint()
    resume_ok  = last_done > 0 and OUTPUT_MBOX.exists()
    mode       = "ab" if resume_ok else "wb"

    if mode == "wb":
        # Fresh start — remove any stale outputs to avoid accidental duplication
        if OUTPUT_MBOX.exists():
            OUTPUT_MBOX.unlink()
        if ATTACHMENT_CSV.exists():
            ATTACHMENT_CSV.unlink()
        save_checkpoint(0)
        last_done = 0
        print("Starting fresh — output will be written from scratch.")
    else:
        print(f"Resuming from message {last_done + 1}, appending to existing output.")

    attachments = []
    inbox       = mailbox.mbox(INPUT_MBOX)

    with open(OUTPUT_MBOX, mode) as out_f:
        for i, msg in enumerate(inbox, start=1):
            if i <= last_done:
                continue  # already processed in a previous run

            if i % PROGRESS_EVERY == 0:
                print(f"Processed {i:,} messages...")

            raw    = msg.as_bytes()
            parsed = PARSER.parsebytes(raw)

            # Strip attachments; keep all non-attachment MIME parts
            if parsed.is_multipart():
                kept_parts = []
                for part in parsed.walk():
                    if part.get_content_maintype() == "multipart":
                        continue  # container parts are rebuilt automatically

                    if is_attachment_part(part):
                        payload = part.get_payload(decode=True) or b""
                        attachments.append({
                            "Message-ID" : parsed.get("Message-ID"),
                            "Date"       : parsed.get("Date"),
                            "From"       : parsed.get("From"),
                            "To"         : parsed.get("To"),
                            "Filename"   : part.get_filename(),
                            "Size"       : len(payload),
                            "SHA256"     : sha256_bytes(payload),
                        })
                    else:
                        kept_parts.append(part)

                parsed.set_payload([])
                for p in kept_parts:
                    parsed.attach(p)

            # Serialize with minimal rewriting, then write the mbox separator + message
            buffer = BytesIO()
            gen    = BytesGenerator(buffer, mangle_from_=True, policy=policy.compat32)
            gen.flatten(parsed)
            msg_bytes = buffer.getvalue()

            written = False
            while not written:
                try:
                    wait_for_parent(OUTPUT_MBOX)
                    out_f.write(b"From nobody Thu Jan 01 00:00:00 1970\n")
                    out_f.write(msg_bytes)
                    out_f.write(b"\n")
                    out_f.flush()
                    save_checkpoint(i)
                    written = True
                except OSError as e:
                    print(f"I/O error at message {i}: {e} — retrying in {RETRY_DELAY}s...")
                    time.sleep(RETRY_DELAY)

    # Write attachment inventory CSV
    if attachments:
        with open(ATTACHMENT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(attachments[0].keys()))
            writer.writeheader()
            writer.writerows(attachments)
        print(f"Attachment inventory: {ATTACHMENT_CSV}  ({len(attachments):,} items)")
    else:
        print("No attachments found.")

    print("Done.")
    print(f"Output MBOX      : {OUTPUT_MBOX}")
    print(f"Checkpoint file  : {CHECKPOINT_FILE}")
