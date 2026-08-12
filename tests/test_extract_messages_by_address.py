"""Covers address matching and exact resume in extract_messages_by_address.py."""

import csv
import sys
from pathlib import Path

import pytest

import extract_messages_by_address as extract
import mbox_builder as mb


def run_extract(monkeypatch, mbox_path: Path, out_dir: Path, address="b@example.com"):
    """Invoke the extractor in-process with the given arguments."""
    monkeypatch.setattr(sys, "argv", [
        "extract_messages_by_address.py",
        "--mbox-file", str(mbox_path),
        "--address", address,
        "--output-dir", str(out_dir),
    ])
    extract.main()


def index_rows(out_dir: Path):
    csv_path = next(out_dir.glob("*_index.csv"))
    with csv_path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def mbox_message_count(out_dir: Path):
    mbox_path = next(p for p in out_dir.glob("*.mbox"))
    return mbox_path.read_bytes().count(b"\nFrom nobody") + mbox_path.read_bytes().startswith(b"From nobody")


def test_matches_participant_addresses(tmp_path, monkeypatch):
    mbox = mb.write_mbox(tmp_path / "in.mbox", [
        mb.plain_message(mid="hit", to="target@example.org"),
        mb.plain_message(mid="miss", to="someone@elsewhere.test"),
    ])
    out_dir = tmp_path / "out"
    run_extract(monkeypatch, mbox, out_dir, address="target@example.org")

    rows = index_rows(out_dir)
    assert len(rows) == 1
    assert rows[0]["message_id"] == "<hit@example.com>"


def test_resume_after_a_crash_does_not_duplicate_messages(tmp_path, monkeypatch):
    """Matches are written immediately; the checkpoint only flushes periodically.

    A crash in between left messages in the output mbox and the index that the
    checkpoint knew nothing about, so the rescan wrote every one of them a second
    time. The Message-ID dedup could not catch it because those ids had not been
    flushed either.
    """
    messages = [mb.plain_message(mid=f"m{i}", body=f"Message {i}.") for i in range(4)]
    mbox = mb.write_mbox(tmp_path / "in.mbox", messages)
    out_dir = tmp_path / "out"

    # Crash partway through, after two matches are already on disk.
    real_write = extract.write_mbox_message
    calls = {"n": 0}

    def crash_after_two(out_fh, raw):
        if calls["n"] >= 2:
            raise RuntimeError("simulated interruption")
        calls["n"] += 1
        return real_write(out_fh, raw)

    monkeypatch.setattr(extract, "write_mbox_message", crash_after_two)
    with pytest.raises(RuntimeError):
        run_extract(monkeypatch, mbox, out_dir)
    assert len(index_rows(out_dir)) == 2

    # Resume with the real writer.
    monkeypatch.setattr(extract, "write_mbox_message", real_write)
    run_extract(monkeypatch, mbox, out_dir)

    rows = index_rows(out_dir)
    assert [r["message_id"] for r in rows] == [f"<m{i}@example.com>" for i in range(4)]
    assert mbox_message_count(out_dir) == 4


def test_completed_run_is_not_reprocessed(tmp_path, monkeypatch):
    """Re-running a finished extract is a no-op, not a second copy of everything."""
    mbox = mb.write_mbox(tmp_path / "in.mbox", [mb.plain_message(mid=f"m{i}") for i in range(3)])
    out_dir = tmp_path / "out"

    run_extract(monkeypatch, mbox, out_dir)
    first = index_rows(out_dir)
    run_extract(monkeypatch, mbox, out_dir)

    assert index_rows(out_dir) == first


def test_duplicate_message_ids_across_inputs_are_extracted_once(tmp_path, monkeypatch):
    """Gmail's All Mail and Sent overlap, so the same message arrives twice."""
    shared = mb.plain_message(mid="shared")
    first = mb.write_mbox(tmp_path / "a.mbox", [shared])
    second = mb.write_mbox(tmp_path / "b.mbox", [shared])
    out_dir = tmp_path / "out"

    monkeypatch.setattr(sys, "argv", [
        "extract_messages_by_address.py",
        "--mbox-file", str(first), str(second),
        "--address", "b@example.com",
        "--output-dir", str(out_dir),
    ])
    extract.main()

    assert len(index_rows(out_dir)) == 1
