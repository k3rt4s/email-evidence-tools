"""Covers MIME-structure preservation and exact resume in strip_attachments_from_mbox.py."""

import csv
import email
import subprocess
import sys
from email import policy
from pathlib import Path

import mbox_builder as mb

SCRIPT = Path(__file__).resolve().parent.parent / "strip_attachments_from_mbox.py"


def run_strip(mbox_path: Path, out_mbox: Path, inventory: Path, checkpoint: Path):
    """Run the stripper as the user runs it."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT),
         "--input-mbox", str(mbox_path),
         "--output-mbox", str(out_mbox),
         "--attachment-csv", str(inventory),
         "--checkpoint-file", str(checkpoint)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def read_inventory(path: Path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def parse_first_message(out_mbox: Path):
    """Parse the first message out of a written mbox, separator line removed."""
    raw = out_mbox.read_bytes().split(b"\n", 1)[1]
    return email.message_from_bytes(raw, policy=policy.default)


def structure(msg):
    """Return the MIME tree as nested content types."""
    if msg.is_multipart():
        return [msg.get_content_type()] + [structure(p) for p in msg.get_payload()]
    return msg.get_content_type()


def test_attachment_is_removed_and_inventoried(tmp_path):
    mbox = mb.write_mbox(tmp_path / "in.mbox", [mb.attachment_message(payload=b"12345")])
    out = tmp_path / "out.mbox"
    inv = tmp_path / "inv.csv"
    run_strip(mbox, out, inv, tmp_path / "cp.json")

    rows = read_inventory(inv)
    assert len(rows) == 1
    assert rows[0]["Filename"] == "doc.bin"
    assert rows[0]["Size"] == "5"
    assert b"attachment-bytes" not in out.read_bytes()


def test_nested_containers_survive_stripping(tmp_path):
    """Re-attaching surviving leaves at the top level flattened the tree.

    A multipart/alternative inside a multipart/mixed came back as two sibling
    parts, so a reader rendered the plain and HTML versions one after the other
    instead of choosing between them.
    """
    mbox = mb.write_mbox(tmp_path / "in.mbox", [mb.nested_message()])
    out = tmp_path / "out.mbox"
    run_strip(mbox, out, tmp_path / "inv.csv", tmp_path / "cp.json")

    assert structure(parse_first_message(out)) == [
        "multipart/mixed",
        ["multipart/alternative", "text/plain", "text/html"],
    ]


def test_resume_keeps_the_inventory_written_before_the_interruption(tmp_path):
    """The inventory was rebuilt from an in-memory list at the end of every run.

    A resumed run therefore replaced the whole CSV with only the attachments it
    saw after the resume point, destroying the record of everything stripped
    earlier while the files themselves stayed gone from the output.
    """
    first_half = [mb.attachment_message(mid="att1", filename="first.bin", payload=b"first")]
    both = first_half + [mb.attachment_message(mid="att2", filename="second.bin", payload=b"second")]

    out = tmp_path / "out.mbox"
    inv = tmp_path / "inv.csv"
    cp = tmp_path / "cp.json"

    # Run against the first message only, exactly as an interrupted run would leave things.
    partial = mb.write_mbox(tmp_path / "in.mbox", first_half)
    run_strip(partial, out, inv, cp)
    assert [r["Filename"] for r in read_inventory(inv)] == ["first.bin"]

    # Resume against the full archive.
    full = mb.write_mbox(tmp_path / "in.mbox", both)
    stdout = run_strip(full, out, inv, cp)
    assert "Resuming from message 2" in stdout
    assert [r["Filename"] for r in read_inventory(inv)] == ["first.bin", "second.bin"]


def test_resumed_output_matches_an_uninterrupted_run(tmp_path):
    """Resume must be exactly-once: same bytes as if the run had never stopped."""
    messages = [
        mb.attachment_message(mid="att1", filename="first.bin", payload=b"first"),
        mb.attachment_message(mid="att2", filename="second.bin", payload=b"second"),
        mb.plain_message(mid="tail", body="No attachment here."),
    ]

    clean_out = tmp_path / "clean.mbox"
    clean_inv = tmp_path / "clean.csv"
    full = mb.write_mbox(tmp_path / "full.mbox", messages)
    run_strip(full, clean_out, clean_inv, tmp_path / "clean.json")

    resumed_out = tmp_path / "resumed.mbox"
    resumed_inv = tmp_path / "resumed.csv"
    cp = tmp_path / "resumed.json"
    partial = mb.write_mbox(tmp_path / "partial.mbox", messages[:1])
    run_strip(partial, resumed_out, resumed_inv, cp)
    run_strip(mb.write_mbox(partial, messages), resumed_out, resumed_inv, cp)

    assert resumed_inv.read_bytes() == clean_inv.read_bytes()
    assert resumed_out.read_bytes() == clean_out.read_bytes()


def test_checkpoint_without_byte_lengths_restarts_instead_of_duplicating(tmp_path):
    """A checkpoint from before exact resume cannot be trusted, so the run starts over."""
    mbox = mb.write_mbox(tmp_path / "in.mbox", [mb.attachment_message(payload=b"12345")])
    out = tmp_path / "out.mbox"
    inv = tmp_path / "inv.csv"
    cp = tmp_path / "cp.json"

    run_strip(mbox, out, inv, cp)
    cp.write_text("1", encoding="utf-8")  # the old bare-integer format
    stdout = run_strip(mbox, out, inv, cp)

    assert "predates exact resume" in stdout
    assert len(read_inventory(inv)) == 1
