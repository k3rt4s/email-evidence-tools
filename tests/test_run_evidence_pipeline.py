"""Covers stage ordering, wiring, and failure handling in run_evidence_pipeline.py."""

import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

import mbox_builder as mb
import run_evidence_pipeline as rep

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


def test_missing_source_gives_a_record_and_no_crash(tmp_path):
    """hash_sources must not raise on a missing/unreadable source, matching the
    extractor's own SKIP-and-continue handling of a bad --mbox-file entry."""
    missing = tmp_path / "does_not_exist.mbox"

    sources = rep.hash_sources([str(missing)], skip_hash=False, log=lambda line: None)

    assert len(sources) == 1
    assert sources[0]["sha256"] is None
    assert sources[0]["size"] is None
    assert sources[0]["error"] == "missing"


def test_exception_mid_stage_still_writes_an_incomplete_record(tmp_path, monkeypatch):
    """A crash inside a stage must still leave a custody record, then re-raise
    with the run's ordinary (unhandled) exit behaviour unchanged."""
    archive = case_archive(tmp_path)
    out = tmp_path / "case"
    argv = ["run_evidence_pipeline.py", "--mbox-file", str(archive),
            "--address", "target@example.org", "--output-dir", str(out)]
    monkeypatch.setattr(sys, "argv", argv)

    real_run = rep.subprocess.run

    def fake_run(command, *a, **kw):
        if any("strip_attachments_from_mbox.py" in str(part) for part in command):
            raise OSError("simulated crash mid-stage")
        return real_run(command, *a, **kw)

    monkeypatch.setattr(rep.subprocess, "run", fake_run)

    with pytest.raises(OSError):
        rep.main()

    custody_files = _custody_files(out)
    assert len(custody_files) == 1
    record = json.loads(custody_files[0].read_text(encoding="utf-8"))
    assert record["status"] == "incomplete"
    assert record["interrupted"] is not None and "OSError" in record["interrupted"]
    # The cut-short stage is named as failed_stage and still appears in
    # stages_run (with exit_code None), rather than being silently dropped.
    assert record["stages_run"] == ["extract", "strip"]
    assert record["failed_stage"] == "strip"
    strip_result = record["stage_results"][-1]
    assert strip_result["stage"] == "strip"
    assert strip_result["exit_code"] is None
    assert strip_result.get("interrupted") is True


def test_pre_existing_and_new_outputs_are_tagged_by_origin(tmp_path):
    archive = case_archive(tmp_path)
    out = tmp_path / "case"
    run_pipeline(["--mbox-file", str(archive), "--address", "target@example.org",
                 "--output-dir", str(out)])

    render_md = out / "04_render" / "target.md"
    assert render_md.exists()
    render_md.unlink()

    run_pipeline(["--mbox-file", str(archive), "--address", "target@example.org",
                 "--output-dir", str(out),
                 "--skip", "extract", "strip", "scan", "clean"])

    custody_files = sorted(_custody_files(out), key=lambda p: p.stat().st_mtime)
    assert len(custody_files) == 2
    record = json.loads(custody_files[-1].read_text(encoding="utf-8"))
    outputs_by_path = {o["path"]: o for o in record["outputs"]}

    assert outputs_by_path["04_render/target.md"]["origin"] == "new"
    assert outputs_by_path["01_extract/target.mbox"]["origin"] == "pre-existing"


def test_stages_run_on_failure_excludes_stages_that_never_ran(tmp_path):
    out = tmp_path / "case"
    (out / "01_extract").mkdir(parents=True)
    (out / "01_extract" / "target.mbox").mkdir()
    run_pipeline(["--mbox-file", str(case_archive(tmp_path)),
                 "--address", "target@example.org",
                 "--output-dir", str(out), "--skip", "extract"],
                expect_success=False)

    record = json.loads(_custody_files(out)[0].read_text(encoding="utf-8"))
    assert record["stages_run"] == ["strip"]
    assert "render" not in record["stages_run"]


def test_get_code_version_falls_back_on_a_git_timeout(monkeypatch):
    """A hung git call must not hang the pipeline: it needs a timeout, and a
    timeout falls back to commit "unknown", dirty None like any other git failure."""
    calls = []

    def fake_run(command, **kwargs):
        calls.append(kwargs)
        raise subprocess.TimeoutExpired(cmd=command, timeout=kwargs.get("timeout") or 0)

    monkeypatch.setattr(rep.subprocess, "run", fake_run)

    info = rep.get_code_version()

    assert info == {"commit": "unknown", "dirty": None}
    assert calls, "expected a git rev-parse attempt"
    assert calls[0].get("timeout") is not None


def test_write_custody_stamp_collision_gets_a_suffixed_file(tmp_path):
    first = rep.write_custody(tmp_path, "20260101T000000Z", {"n": 1})
    second = rep.write_custody(tmp_path, "20260101T000000Z", {"n": 2})

    assert first != second
    assert first.exists() and second.exists()
    assert json.loads(first.read_text(encoding="utf-8"))["n"] == 1
    assert json.loads(second.read_text(encoding="utf-8"))["n"] == 2


def test_keyboard_interrupt_mid_stage_writes_incomplete_record_and_reraises(tmp_path, monkeypatch):
    """A Ctrl-C during a stage must not come out as some other exception, and
    the record it leaves must name the stage that was cut short."""
    archive = case_archive(tmp_path)
    out = tmp_path / "case"
    argv = ["run_evidence_pipeline.py", "--mbox-file", str(archive),
            "--address", "target@example.org", "--output-dir", str(out)]
    monkeypatch.setattr(sys, "argv", argv)

    real_run = rep.subprocess.run

    def fake_run(command, *a, **kw):
        if any("strip_attachments_from_mbox.py" in str(part) for part in command):
            raise KeyboardInterrupt
        return real_run(command, *a, **kw)

    monkeypatch.setattr(rep.subprocess, "run", fake_run)

    with pytest.raises(KeyboardInterrupt):
        rep.main()

    custody_files = _custody_files(out)
    assert len(custody_files) == 1
    record = json.loads(custody_files[0].read_text(encoding="utf-8"))
    assert record["status"] == "incomplete"
    assert record["failed_stage"] == "strip"
    assert record["stages_run"] == ["extract", "strip"]
    strip_result = record["stage_results"][-1]
    assert strip_result["stage"] == "strip"
    assert strip_result["exit_code"] is None
    assert strip_result.get("interrupted") is True


def test_write_custody_failure_on_failed_stage_still_returns_stage_rc(tmp_path, monkeypatch):
    """A custody write failure must never mask a stage's own failure exit code."""
    archive = case_archive(tmp_path)

    baseline_out = tmp_path / "baseline"
    (baseline_out / "01_extract").mkdir(parents=True)
    (baseline_out / "01_extract" / "target.mbox").mkdir()
    baseline_result = run_pipeline(["--mbox-file", str(archive), "--address", "target@example.org",
                                    "--output-dir", str(baseline_out), "--skip", "extract"],
                                   expect_success=False)
    expected_rc = baseline_result.returncode

    out = tmp_path / "case"
    (out / "01_extract").mkdir(parents=True)
    (out / "01_extract" / "target.mbox").mkdir()
    argv = ["run_evidence_pipeline.py", "--mbox-file", str(archive),
            "--address", "target@example.org", "--output-dir", str(out), "--skip", "extract"]
    monkeypatch.setattr(sys, "argv", argv)

    def boom(*a, **kw):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(rep, "write_custody", boom)

    rc = rep.main()

    assert rc == expected_rc
    assert rc != 3
    log = (out / "pipeline.log").read_text(encoding="utf-8")
    assert "custody record could not be written" in log
    assert not list(out.glob("custody_*.json"))


def test_write_custody_failure_during_keyboard_interrupt_still_reraises(tmp_path, monkeypatch):
    """A second failure (writing the record) must never swallow the first
    (the interrupt) or turn it into something else."""
    archive = case_archive(tmp_path)
    out = tmp_path / "case"
    argv = ["run_evidence_pipeline.py", "--mbox-file", str(archive),
            "--address", "target@example.org", "--output-dir", str(out)]
    monkeypatch.setattr(sys, "argv", argv)

    real_run = rep.subprocess.run

    def fake_run(command, *a, **kw):
        if any("strip_attachments_from_mbox.py" in str(part) for part in command):
            raise KeyboardInterrupt
        return real_run(command, *a, **kw)

    monkeypatch.setattr(rep.subprocess, "run", fake_run)

    def boom(*a, **kw):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(rep, "write_custody", boom)

    with pytest.raises(KeyboardInterrupt):
        rep.main()

    log = (out / "pipeline.log").read_text(encoding="utf-8")
    assert "custody record could not be written" in log
    assert not list(out.glob("custody_*.json"))


def test_write_custody_failure_on_clean_run_returns_3(tmp_path, monkeypatch):
    """A run that otherwise succeeded but left no provable record must not
    report success: exit code 3 marks it, never 0."""
    archive = case_archive(tmp_path)
    out = tmp_path / "case"
    argv = ["run_evidence_pipeline.py", "--mbox-file", str(archive),
            "--address", "target@example.org", "--output-dir", str(out)]
    monkeypatch.setattr(sys, "argv", argv)

    def boom(*a, **kw):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(rep, "write_custody", boom)

    rc = rep.main()

    assert rc == 3
    log = (out / "pipeline.log").read_text(encoding="utf-8")
    assert "custody record could not be written" in log
    assert not list(out.glob("custody_*.json"))


def test_missing_and_real_source_end_to_end(tmp_path):
    archive = case_archive(tmp_path)
    missing = tmp_path / "does_not_exist.mbox"
    out = tmp_path / "case"
    run_pipeline(["--mbox-file", str(missing), str(archive), "--address", "target@example.org",
                 "--output-dir", str(out)])

    record = json.loads(_custody_files(out)[0].read_text(encoding="utf-8"))
    assert record["status"] == "complete"
    sources_by_path = {s["path"]: s for s in record["sources"]}
    assert sources_by_path[str(missing)]["error"] == "missing"
    assert sources_by_path[str(missing)]["sha256"] is None
    assert sources_by_path[str(archive)]["sha256"] is not None
    assert sources_by_path[str(archive)].get("error") is None


def test_write_custody_failure_leaves_no_tmp_or_empty_json(tmp_path, monkeypatch):
    """A failure between reserving the final name and completing the write
    must not leave the reserved zero-byte file, or the temp file, behind."""

    def bad_fsync(fd):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(rep.os, "fsync", bad_fsync)

    with pytest.raises(OSError):
        rep.write_custody(tmp_path, "20260101T000000Z", {"n": 1})

    assert list(tmp_path.iterdir()) == []


def test_collect_outputs_tags_removed_baseline_file_as_removed(tmp_path):
    (tmp_path / "01_extract").mkdir()
    gone = tmp_path / "01_extract" / "gone.mbox"
    gone.write_bytes(b"data")
    baseline = rep.snapshot_outputs(tmp_path)
    gone.unlink()

    outputs = rep.collect_outputs(tmp_path, baseline)

    entry = next(o for o in outputs if o["path"] == "01_extract/gone.mbox")
    assert entry["origin"] == "removed"
    assert entry["size"] is None
    assert entry["sha256"] is None


def test_collect_outputs_without_a_baseline_tags_every_output_unknown(tmp_path):
    """When the run was cut short before the snapshot, no output may be claimed as new."""
    (tmp_path / "01_extract").mkdir()
    (tmp_path / "01_extract" / "a.mbox").write_bytes(b"x")
    outputs = rep.collect_outputs(tmp_path, None)
    assert [(o["path"], o["origin"]) for o in outputs] == [("01_extract/a.mbox", "unknown")]
