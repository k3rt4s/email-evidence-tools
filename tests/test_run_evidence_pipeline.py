"""Covers stage ordering, wiring, and failure handling in run_evidence_pipeline.py."""

import csv
import subprocess
import sys
from pathlib import Path

import mbox_builder as mb

SCRIPT = Path(__file__).resolve().parent.parent / "run_evidence_pipeline.py"


def run_pipeline(args, expect_success=True):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
    )
    if expect_success:
        assert result.returncode == 0, result.stdout + result.stderr
    return result


def case_archive(tmp_path):
    return mb.write_mbox(tmp_path / "source.mbox", [
        mb.plain_message(mid="hit", to="target@example.org",
                         body="Please action this urgent payment."),
        mb.attachment_message(mid="att", payload=b"attachment-bytes"),
        mb.plain_message(mid="miss", to="nobody@elsewhere.test"),
    ])


def test_full_pipeline_produces_every_stage_output(tmp_path):
    archive = case_archive(tmp_path)
    out = tmp_path / "case"
    run_pipeline(["--mbox-file", str(archive), "--address", "target@example.org",
                  "--output-dir", str(out)])

    assert (out / "01_extract" / "target.mbox").exists()
    assert (out / "01_extract" / "target_index.csv").exists()
    assert (out / "02_stripped" / "target_no_attachments.mbox").exists()
    assert (out / "02_stripped" / "attachments_inventory.csv").exists()
    assert (out / "03_scan" / "target_evidence_hits.csv").exists()
    assert (out / "03_scan" / "target_evidence_hits_clean.csv").exists()
    assert (out / "04_render" / "target.md").exists()
    assert (out / "pipeline.log").exists()


def test_later_stages_run_against_the_extract_not_the_source(tmp_path):
    """Scanning the raw archive would defeat the point of extracting first."""
    archive = case_archive(tmp_path)
    out = tmp_path / "case"
    run_pipeline(["--mbox-file", str(archive), "--address", "target@example.org",
                  "--output-dir", str(out)])

    with (out / "03_scan" / "target_evidence_hits.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    # Only the extracted message is in scope, so its hit is the only one present.
    assert rows, "expected at least one hit from the extracted message"
    assert all("urgent" in r["matched_term"] or "payment" in r["matched_term"] for r in rows)


def test_scan_consumes_the_stripped_copy_when_strip_runs(tmp_path):
    """Strip exists to make the scan cheaper; if nothing reads its output it is dead weight."""
    archive = case_archive(tmp_path)
    out = tmp_path / "case"
    result = run_pipeline(["--mbox-file", str(archive), "--address", "target@example.org",
                           "--output-dir", str(out), "--dry-run"])

    scan_line = next(line for line in result.stdout.splitlines() if line.startswith("scan:"))
    assert "02_stripped" in scan_line
    render_line = next(line for line in result.stdout.splitlines() if line.startswith("render:"))
    assert "01_extract" in render_line, "render needs the attachments the stripped copy lacks"


def test_scan_falls_back_to_the_extract_when_strip_is_skipped(tmp_path):
    archive = case_archive(tmp_path)
    out = tmp_path / "case"
    result = run_pipeline(["--mbox-file", str(archive), "--address", "target@example.org",
                           "--output-dir", str(out), "--skip", "strip", "--dry-run"])

    scan_line = next(line for line in result.stdout.splitlines() if line.startswith("scan:"))
    assert "01_extract" in scan_line


def test_skipping_a_producer_fails_before_anything_runs(tmp_path):
    """Otherwise the run gets halfway in and dies on a missing file several stages later."""
    archive = case_archive(tmp_path)
    out = tmp_path / "case"
    result = run_pipeline(["--mbox-file", str(archive), "--address", "target@example.org",
                           "--output-dir", str(out), "--skip", "extract"],
                          expect_success=False)

    assert result.returncode == 2
    assert "cannot start" in result.stderr
    assert not (out / "pipeline.log").exists()


def test_dry_run_prints_the_plan_and_writes_nothing(tmp_path):
    archive = case_archive(tmp_path)
    out = tmp_path / "case"
    result = run_pipeline(["--mbox-file", str(archive), "--address", "target@example.org",
                           "--output-dir", str(out), "--dry-run"])

    for stage in ("extract", "strip", "scan", "clean", "render"):
        assert f"{stage}:" in result.stdout
    assert not out.exists()


def test_skipped_stages_do_not_run(tmp_path):
    archive = case_archive(tmp_path)
    out = tmp_path / "case"
    result = run_pipeline(["--mbox-file", str(archive), "--address", "target@example.org",
                           "--output-dir", str(out), "--skip", "strip", "render", "--dry-run"])

    assert "strip:" not in result.stdout
    assert "render:" not in result.stdout
    assert "extract:" in result.stdout


def test_a_failing_stage_stops_the_pipeline(tmp_path):
    """A later stage must not consume an output that was never finished."""
    out = tmp_path / "case"
    # Stand in an unreadable extract: the path exists, so preflight is satisfied,
    # but strip cannot open it. Render must not run afterwards.
    (out / "01_extract").mkdir(parents=True)
    (out / "01_extract" / "target.mbox").mkdir()
    result = run_pipeline(["--mbox-file", str(case_archive(tmp_path)),
                           "--address", "target@example.org",
                           "--output-dir", str(out), "--skip", "extract"],
                          expect_success=False)

    assert result.returncode != 0
    assert "FAILED" in result.stdout
    log = (out / "pipeline.log").read_text(encoding="utf-8")
    assert "pipeline stopped" in log
    assert "--- render ---" not in log
