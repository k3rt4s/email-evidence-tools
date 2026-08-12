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
    assert (out / "02_stripped" / "attachments_inventory.csv").exists()
    assert (out / "01_extract" / "target_evidence_hits.csv").exists()
    assert (out / "01_extract" / "target_evidence_hits_clean.csv").exists()
    assert (out / "03_render" / "target.md").exists()
    assert (out / "pipeline.log").exists()


def test_later_stages_run_against_the_extract_not_the_source(tmp_path):
    """Scanning the raw archive would defeat the point of extracting first."""
    archive = case_archive(tmp_path)
    out = tmp_path / "case"
    run_pipeline(["--mbox-file", str(archive), "--address", "target@example.org",
                  "--output-dir", str(out)])

    with (out / "01_extract" / "target_evidence_hits.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    # Only the extracted message is in scope, so its hit is the only one present.
    assert rows, "expected at least one hit from the extracted message"
    assert all("urgent" in r["matched_term"] or "payment" in r["matched_term"] for r in rows)


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
    result = run_pipeline(["--mbox-file", str(tmp_path / "missing.mbox"),
                           "--address", "target@example.org",
                           "--output-dir", str(out), "--skip", "extract"],
                          expect_success=False)

    assert result.returncode != 0
    assert "FAILED" in result.stdout
    log = (out / "pipeline.log").read_text(encoding="utf-8")
    assert "pipeline stopped" in log
    assert "render" not in log.split("pipeline stopped")[0].split("--- ")[-1]
