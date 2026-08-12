"""Covers the rendered evidence document produced by render_mbox_to_markdown.py."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import mbox_builder as mb
from evidence_text import html_to_text

SCRIPT = Path(__file__).resolve().parent.parent / "render_mbox_to_markdown.py"


def run_render(mbox_path: Path, out_dir: Path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--mbox-file", str(mbox_path), "--output-dir", str(out_dir)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    return (out_dir / f"{mbox_path.stem}.md").read_text(encoding="utf-8")


def test_renders_messages_in_chronological_order(tmp_path):
    mbox = mb.write_mbox(tmp_path / "in.mbox", [
        mb.plain_message(mid="later", subject="Later", date="Wed, 07 Jan 2026 09:00:00 +0000"),
        mb.plain_message(mid="earlier", subject="Earlier", date="Mon, 05 Jan 2026 09:00:00 +0000"),
    ])
    md = run_render(mbox, tmp_path / "out")
    assert md.index("Earlier") < md.index("Later")


def test_html_only_body_is_rendered_as_text(tmp_path):
    """The HTML fallback moved to evidence_text.py; the renderer must still use it."""
    mbox = mb.write_mbox(tmp_path / "in.mbox", [
        mb.html_only_message(html='<html><body><p>Call <a href="https://example.test/x">this link</a>.</p></body></html>'),
    ])
    md = run_render(mbox, tmp_path / "out")
    assert "Call this link <https://example.test/x>." in md
    assert "<p>" not in md
    assert "text/html->stripped" in md


def test_attachments_are_extracted_and_hashed(tmp_path):
    payload = b"attachment-bytes"
    mbox = mb.write_mbox(tmp_path / "in.mbox", [mb.attachment_message(payload=payload)])
    out_dir = tmp_path / "out"
    md = run_render(mbox, out_dir)

    saved = list((out_dir / "attachments").iterdir())
    assert len(saved) == 1
    assert saved[0].read_bytes() == payload
    assert hashlib.sha256(payload).hexdigest() in md


def test_manifest_records_source_hash_and_counts(tmp_path):
    mbox = mb.write_mbox(tmp_path / "in.mbox", [mb.plain_message(), mb.attachment_message()])
    out_dir = tmp_path / "out"
    run_render(mbox, out_dir)

    manifest = json.loads((out_dir / "render_manifest.json").read_text(encoding="utf-8"))
    assert manifest["messages_total"] == 2
    assert manifest["attachments_total"] == 1
    assert manifest["parse_errors"] == 0
    assert manifest["input_mbox_sha256"] == hashlib.sha256(mbox.read_bytes()).hexdigest()


def test_undated_messages_are_appended_not_dropped(tmp_path):
    mbox = mb.write_mbox(tmp_path / "in.mbox", [
        mb.plain_message(mid="dated", subject="Dated"),
        mb.plain_message(mid="undated", subject="Undated", date="not a date at all"),
    ])
    md = run_render(mbox, tmp_path / "out")
    assert "## Messages (undated)" in md
    assert "Undated" in md


def test_html_to_text_keeps_link_targets():
    assert html_to_text('<p>See <a href="https://example.test">here</a></p>') == "See here <https://example.test>"
