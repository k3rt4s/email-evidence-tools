"""Covers stage ordering, wiring, and failure handling in run_evidence_pipeline.py."""

import csv
import hashlib
import json
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


def _custody_files(out):
    return list(out.glob("custody_*.json"))


def test_successful_run_writes_a_matching_custody_record(tmp_path):
    archive = case_archive(tmp_path)
    out = tmp_path / "case"
    run_pipeline(["--mbox-file", str(archive), "--address", "target@example.org",
                 "--output-dir", str(out)])

    custody_files = _custody_files(out)
    assert len(custody_files) == 1
    record = json.loads(custody_files[0].read_text(encoding="utf-8"))

    assert record["status"] == "complete"
    assert len(record["sources"]) == 1
    source = record["sources"][0]
    assert source["sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert source["size"] == archive.stat().st_size

    outputs_by_path = {o["path"]: o for o in record["outputs"]}
    on_disk = [p for p in out.rglob("*") if p.is_file() and p.name != "pipeline.log"
               and not p.name.startswith("custody_")]
    assert len(outputs_by_path) == len(on_disk)
    for path in on_disk:
        rel = str(path.relative_to(out)).replace("\\", "/")
        assert rel in outputs_by_path
        entry = outputs_by_path[rel]
        assert entry["size"] == path.stat().st_size
        assert entry["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_failing_stage_writes_an_incomplete_custody_record(tmp_path):
    out = tmp_path / "case"
    (out / "01_extract").mkdir(parents=True)
    (out / "01_extract" / "target.mbox").mkdir()
    run_pipeline(["--mbox-file", str(case_archive(tmp_path)),
                 "--address", "target@example.org",
                 "--output-dir", str(out), "--skip", "extract"],
                expect_success=False)

    custody_files = _custody_files(out)
    assert len(custody_files) == 1
    record = json.loads(custody_files[0].read_text(encoding="utf-8"))
    assert record["status"] == "incomplete"
    assert record["failed_stage"] == "strip"


def test_no_source_hash_skips_hashing(tmp_path):
    archive = case_archive(tmp_path)
    out = tmp_path / "case"
    run_pipeline(["--mbox-file", str(archive), "--address", "target@example.org",
                 "--output-dir", str(out), "--no-source-hash"])

    custody_files = _custody_files(out)
    assert len(custody_files) == 1
    record = json.loads(custody_files[0].read_text(encoding="utf-8"))
    assert record["source_hash_skipped"] is True
    assert record["sources"][0]["sha256"] is None


def test_dry_run_writes_no_custody_file(tmp_path):
    archive = case_archive(tmp_path)
    out = tmp_path / "case"
    run_pipeline(["--mbox-file", str(archive), "--address", "target@example.org",
                 "--output-dir", str(out), "--dry-run"])

    assert not out.exists()
