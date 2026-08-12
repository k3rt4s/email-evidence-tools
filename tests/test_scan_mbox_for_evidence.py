"""Covers the body-extraction and sentence-matching behaviour of scan_mbox_for_evidence.py."""

import csv
import subprocess
import sys
from email import message_from_string
from email import policy
from pathlib import Path

import mbox_builder as mb
import scan_mbox_for_evidence as scan

SCRIPT = Path(__file__).resolve().parent.parent / "scan_mbox_for_evidence.py"


def run_scan(mbox_path: Path, out_csv: Path):
    """Run the scanner as the user runs it and return its CSV rows as dicts."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--mbox-file", str(mbox_path), "--output-file", str(out_csv)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    with out_csv.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_html_only_message_is_scanned(tmp_path):
    """An HTML-only body used to read as empty, so the message could never hit."""
    mbox = mb.write_mbox(tmp_path / "html.mbox", [
        mb.html_only_message(html="<html><body><p>Please note the updated banking details.</p></body></html>"),
    ])
    rows = run_scan(mbox, tmp_path / "hits.csv")
    assert [r["matched_term"] for r in rows] == ["updated banking details"]
    assert "updated banking details" in rows[0]["exact_text"]


def test_hit_spanning_a_line_break_is_reported(tmp_path):
    """Terms were matched against collapsed text but reported from raw sentences.

    A phrase wrapped across two lines satisfied the body check, matched no raw
    sentence, and was dropped without a trace.
    """
    mbox = mb.write_mbox(tmp_path / "wrapped.mbox", [
        mb.plain_message(body="Please use the updated banking\ndetails below going forward."),
    ])
    rows = run_scan(mbox, tmp_path / "hits.csv")
    assert [r["matched_term"] for r in rows] == ["updated banking details"]
    assert "updated banking details" in rows[0]["exact_text"]


def test_plain_body_hit_is_still_reported(tmp_path):
    """The straightforward case has to keep working after the normalization change."""
    mbox = mb.write_mbox(tmp_path / "plain.mbox", [
        mb.plain_message(body="This is an urgent payment request."),
    ])
    rows = run_scan(mbox, tmp_path / "hits.csv")
    assert "urgent payment" in {r["matched_term"] for r in rows}


def test_reported_text_keeps_its_original_case(tmp_path):
    """Matching is case-insensitive, but the evidence quote must not be lowercased."""
    mbox = mb.write_mbox(tmp_path / "case.mbox", [
        mb.plain_message(body="Kindly send the Updated Banking Details today."),
    ])
    rows = run_scan(mbox, tmp_path / "hits.csv")
    assert "Updated Banking Details" in rows[0]["exact_text"]


def test_get_body_prefers_plain_over_html():
    """When both alternatives are present the plain part wins, unchanged behaviour."""
    raw = mb.nested_message().split("\n", 1)[1]
    msg = message_from_string(raw, policy=policy.default)
    body = scan.get_body(msg)
    assert "Plain version of the message." in body
    assert "HTML version" not in body


def test_get_body_returns_empty_for_a_bodyless_message():
    """A message with no text part yields an empty string rather than raising."""
    raw = mb.attachment_message(body="").split("\n", 1)[1]
    msg = message_from_string(raw, policy=policy.default)
    assert scan.get_body(msg).strip() == ""


def test_normalize_collapses_whitespace_without_lowercasing():
    assert scan.normalize("Two\nLines   here") == "Two Lines here"


def test_subject_line_hits_are_reported(tmp_path):
    """A lure can live entirely in the Subject header, where a body-only scan sees nothing."""
    mbox = mb.write_mbox(tmp_path / "subject.mbox", [
        mb.plain_message(subject="Urgent payment required", body="Nothing notable here."),
    ])
    rows = run_scan(mbox, tmp_path / "hits.csv")

    subject_hits = [r for r in rows if r["location"] == "subject"]
    assert "urgent payment" in {r["matched_term"] for r in subject_hits}
    assert {r["exact_text"] for r in subject_hits} == {"Urgent payment required"}


def test_body_hits_are_labelled_as_body(tmp_path):
    mbox = mb.write_mbox(tmp_path / "body.mbox", [
        mb.plain_message(subject="Nothing notable", body="Please send an urgent payment."),
    ])
    rows = run_scan(mbox, tmp_path / "hits.csv")
    assert {r["location"] for r in rows} == {"body"}


def test_a_term_in_both_places_is_reported_twice(tmp_path):
    """Subject and body are separate sources of evidence and each is quoted."""
    mbox = mb.write_mbox(tmp_path / "both.mbox", [
        mb.plain_message(subject="Urgent payment", body="This is an urgent payment request."),
    ])
    rows = [r for r in run_scan(mbox, tmp_path / "hits.csv") if r["matched_term"] == "urgent payment"]
    assert sorted(r["location"] for r in rows) == ["body", "subject"]


def test_encoded_subject_is_decoded_before_matching(tmp_path):
    """An RFC 2047 subject matches nothing while it is still base64."""
    mbox = mb.write_mbox(tmp_path / "encoded.mbox", [
        mb.plain_message(subject="=?utf-8?B?VXJnZW50IHBheW1lbnQgbmVlZGVkIOKAkyBhY3Q=?=",
                         body="Nothing notable here."),
    ])
    rows = run_scan(mbox, tmp_path / "hits.csv")
    assert "urgent payment" in {r["matched_term"] for r in rows}
    assert all("Urgent payment needed" in r["exact_text"] for r in rows)


def test_unusual_text_subtypes_are_still_read():
    """Narrowing to text/plain and text/html would silently skip other text parts.

    Legacy clients emit text/enriched and similar; a scanner that ignores them
    reports nothing for a message it never actually read.
    """
    raw = mb.plain_message(body="Contains an urgent payment request.").split("\n", 1)[1]
    raw = raw.replace('Content-Type: text/plain', 'Content-Type: text/enriched')
    msg = message_from_string(raw, policy=policy.default)
    assert "urgent payment" in scan.get_body(msg)


def test_output_defaults_beside_the_input_not_the_working_directory(tmp_path, monkeypatch):
    """A relative default writes evidence wherever the tool is run from.

    On this workstation that means into a code repository, which the workspace
    rules forbid and which .gitignore alone cannot be trusted to catch.
    """
    archive = tmp_path / "archive.mbox"
    mb.write_mbox(archive, [mb.plain_message(body="An urgent payment request.")])

    elsewhere = tmp_path / "cwd"
    elsewhere.mkdir()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--mbox-file", str(archive)],
        capture_output=True, text=True, cwd=elsewhere,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "archive_evidence_hits.csv").exists()
    assert list(elsewhere.iterdir()) == []
