"""Covers HTML stripping and output placement in clean_evidence_csv.py."""

import csv
import subprocess
import sys
from pathlib import Path

import clean_evidence_csv as clean

SCRIPT = Path(__file__).resolve().parent.parent / "clean_evidence_csv.py"

HEADER = ["date", "from", "to", "subject", "category", "matched_term", "exact_text"]


def write_csv(path: Path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(HEADER)
        writer.writerows(rows)
    return path


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def run_clean(args, cwd=None):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=cwd,
    )
    return result


def test_html_is_stripped_and_whitespace_collapsed(tmp_path):
    src = write_csv(tmp_path / "hits.csv", [[
        "2026-01-05", "a@example.com", "b@example.com", "Subject",
        "payment_fraud_indicators", "wire instructions",
        "<p>New   <b>wire instructions</b>\nattached.</p>",
    ]])
    out = tmp_path / "clean.csv"
    assert run_clean(["--input-file", str(src), "--output-file", str(out)]).returncode == 0

    rows = read_csv(out)
    assert rows[0]["exact_text"] == "New wire instructions attached."


def test_other_columns_pass_through_unchanged(tmp_path):
    src = write_csv(tmp_path / "hits.csv", [[
        "2026-01-05", "a@example.com", "b@example.com", "<not> stripped",
        "urgency_language", "asap", "<i>asap</i>",
    ]])
    out = tmp_path / "clean.csv"
    run_clean(["--input-file", str(src), "--output-file", str(out)])

    row = read_csv(out)[0]
    assert row["subject"] == "<not> stripped"
    assert row["matched_term"] == "asap"
    assert list(row.keys()) == HEADER


def test_output_defaults_beside_the_input(tmp_path):
    """The old default wrote a bare filename into the working directory."""
    src = write_csv(tmp_path / "hits.csv", [[
        "2026-01-05", "a", "b", "s", "c", "t", "<p>text</p>",
    ]])
    elsewhere = tmp_path / "cwd"
    elsewhere.mkdir()

    assert run_clean(["--input-file", str(src)], cwd=elsewhere).returncode == 0
    assert (tmp_path / "hits_clean.csv").exists()
    assert list(elsewhere.iterdir()) == []


def test_missing_text_column_fails_loudly(tmp_path):
    """Silently emitting an unchanged copy would hide a wrong input file."""
    src = tmp_path / "wrong.csv"
    with src.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([["a", "b"], ["1", "2"]])

    result = run_clean(["--input-file", str(src), "--output-file", str(tmp_path / "o.csv")])
    assert result.returncode != 0
    assert "exact_text" in result.stderr


def test_very_long_fields_are_handled(tmp_path):
    """A quoted HTML body can exceed the csv module's default field limit."""
    long_body = "<p>" + ("wire instructions " * 20000) + "</p>"
    src = write_csv(tmp_path / "hits.csv", [[
        "2026-01-05", "a", "b", "s", "c", "wire instructions", long_body,
    ]])
    out = tmp_path / "clean.csv"
    assert run_clean(["--input-file", str(src), "--output-file", str(out)]).returncode == 0
    assert read_csv(out)[0]["exact_text"].startswith("wire instructions")


def test_clean_text_handles_missing_values():
    assert clean.clean_text(None) == ""
    assert clean.clean_text("  a\t b ") == "a b"
