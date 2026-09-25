"""Runs the extract, strip, scan, clean, and render tools as one ordered pipeline over an mbox archive.

run_evidence_pipeline.py
========================
Project : email-evidence-tools
Purpose : Drives the individual tools in the order that makes sense for a case,
          passing each stage's output to the next so the six-command manual
          sequence becomes one command.

          Stages, in order, each reading what the one before it wrote:
            1. extract  - pull every message involving --address out of the
                          source archives into a much smaller working mbox
            2. strip    - write an attachment-free copy of the extract, plus a
                          hashed inventory of everything removed
            3. scan     - keyword-scan the stripped copy for evidence hits
            4. clean    - strip HTML from the hit quotes scan produced
            5. render   - build the Markdown evidence document from the extract,
                          which unlike the stripped copy still has the
                          attachments to hash and write out

          Stage 1 is what makes the rest affordable: scan, strip, and render all
          index or hold the whole archive, so they run against the extract and
          never against a raw multi-gigabyte export.

Inputs  : --mbox-file PATH [PATH ...]   source archives
          --address    user@example.com address the case is about
          --output-dir DIR              where the case folder goes
          --skip STAGE [STAGE ...]      stages to leave out
          --dry-run                     print the plan and exit
          --no-source-hash              skip hashing the source archives (they
                                        record path and size only, with sha256
                                        null, when this is set)

Outputs : Under <output-dir>: 01_extract, 02_stripped, 03_scan (which holds both
          the raw and the cleaned hit CSVs, since clean rewrites what scan wrote),
          04_render, pipeline.log, and a chain-of-custody
          custody_<UTC stamp>.json per non-dry run (a stamp collision gets a
          -1, -2, ... suffix rather than overwriting an earlier run's record).
          The custody record holds the source archives' paths, sizes and
          (unless skipped) SHA-256 hashes, the code commit and dirty state,
          argv, the python version, start/end times, the stages that actually
          ran, stages skipped, each stage's exit code and elapsed time, overall
          status (complete or incomplete plus the failed stage, and an
          "interrupted" note if an exception or Ctrl-C cut a stage short), and
          a path/size/SHA-256 listing of every file under the four stage
          folders, each tagged "new", "modified", or "pre-existing" against a
          snapshot taken before stage 1 runs, since a resumed run reuses an
          earlier attempt's completed-stage output untouched. Each tool keeps
          its own outputs and checkpoints, so a failed run resumes by
          re-running the same command.

Usage   : python run_evidence_pipeline.py \\
              --mbox-file "D:\\export\\All Mail" \\
              --address "someone@example.com" \\
              --output-dir "C:\\Code_data\\email-evidence-tools\\case-01"

Exit    : 0 on a complete run; 2 when preflight finds a stage that would run
codes     without its producer; a failing stage's own exit code when one
          fails (a KeyboardInterrupt or other exception during a stage instead
          propagates unchanged); and 3 when the run itself completed cleanly
          but its custody record could not be written, so a missing record is
          never silent. A custody write failure after a stage already failed
          still returns that stage's own exit code, logged separately.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from extract_messages_by_address import slugify as _extract_slugify

HERE = Path(__file__).resolve().parent

STAGES = ("extract", "strip", "scan", "clean", "render")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the email-evidence-tools stages as one pipeline.",
    )
    parser.add_argument("--mbox-file", nargs="+", required=True,
                        help="One or more source mbox files.")
    parser.add_argument("--address", required=True,
                        help="Address the case is about (case-insensitive substring).")
    parser.add_argument("--output-dir", required=True,
                        help="Case folder. Each stage writes a subfolder under it.")
    parser.add_argument("--skip", nargs="*", default=[], choices=STAGES,
                        help="Stages to leave out.")
    parser.add_argument("--title", default=None,
                        help="Title for the rendered Markdown document.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the commands that would run, then exit.")
    parser.add_argument("--no-source-hash", action="store_true",
                        help="Skip hashing the source archives in the custody record "
                             "(they can be tens of GB; hashing them takes minutes).")
    return parser.parse_args()


def slugify(address: str) -> str:
    """Return the extractor's own slug, so the two can never disagree.

    This driver has to know what the extract stage will name its output before
    that stage has run. Reimplementing the rule here is how the pair drifts
    apart: a local copy using str.isalnum(), which is Unicode-aware, already
    disagreed with the extractor's ASCII character class on any address with an
    accent in it, and every later stage would then look for a file that was
    never written.
    """
    return _extract_slugify(address)


def build_plan(args, out_dir: Path):
    """Return ([(stage, [command...]), ...], {stage: required input path}).

    Paths are computed here rather than discovered between stages so --dry-run
    shows the real commands, not an approximation of them.
    """
    slug = slugify(args.address)
    extract_dir  = out_dir / "01_extract"
    stripped_dir = out_dir / "02_stripped"
    scan_dir     = out_dir / "03_scan"
    render_dir   = out_dir / "04_render"

    extract_mbox  = extract_dir / f"{slug}.mbox"
    stripped_mbox = stripped_dir / f"{slug}_no_attachments.mbox"
    hits_csv      = scan_dir / f"{slug}_evidence_hits.csv"

    # Keyword scanning reads text parts only, so it runs against the
    # attachment-free copy when there is one: same hits, without decoding
    # megabytes of base64 that can never match. Rendering always uses the
    # extract, because the stripped copy no longer holds the attachments it
    # has to hash and write out.
    scan_source = extract_mbox if "strip" in args.skip else stripped_mbox

    plan = [
        ("extract", [sys.executable, str(HERE / "extract_messages_by_address.py"),
                     "--mbox-file", *args.mbox_file,
                     "--address", args.address,
                     "--output-dir", str(extract_dir)]),
        ("strip", [sys.executable, str(HERE / "strip_attachments_from_mbox.py"),
                   "--input-mbox", str(extract_mbox),
                   "--output-mbox", str(stripped_mbox),
                   "--attachment-csv", str(stripped_dir / "attachments_inventory.csv"),
                   "--checkpoint-file", str(stripped_dir / "strip.checkpoint")]),
        ("scan", [sys.executable, str(HERE / "scan_mbox_for_evidence.py"),
                  "--mbox-file", str(scan_source),
                  "--output-file", str(hits_csv)]),
        ("clean", [sys.executable, str(HERE / "clean_evidence_csv.py"),
                   "--input-file", str(hits_csv),
                   "--output-file", str(scan_dir / f"{slug}_evidence_hits_clean.csv")]),
        ("render", [sys.executable, str(HERE / "render_mbox_to_markdown.py"),
                    "--mbox-file", str(extract_mbox),
                    "--output-dir", str(render_dir)]
                   + (["--title", args.title] if args.title else [])),
    ]

    # What each stage needs on disk before it can start, and which stage makes it.
    inputs = {
        "strip":  (extract_mbox, "extract"),
        "scan":   (scan_source, "strip" if scan_source == stripped_mbox else "extract"),
        "clean":  (hits_csv, "scan"),
        "render": (extract_mbox, "extract"),
    }
    return ([(stage, command) for stage, command in plan if stage not in args.skip], inputs)


def preflight(plan, inputs, skipped):
    """Return a list of problems where a stage will run but its producer was skipped.

    Without this the run starts, works through whatever stages it can, and fails
    somewhere in the middle on a missing file whose real cause was a --skip flag
    several stages earlier.
    """
    problems = []
    running = {stage for stage, _ in plan}
    for stage, (path, producer) in inputs.items():
        if stage not in running or producer in running:
            continue
        if not Path(path).exists():
            problems.append(
                f"{stage} needs {path}, which {producer} would have made, "
                f"but {producer} is skipped and the file is not there already"
            )
    return problems


def hash_file(path, chunk_size=1024 * 1024):
    """Return (sha256_hex_digest, bytes_hashed) for `path`, streamed in chunks.

    Never reads the file whole: sources can be tens of gigabytes. Returning the
    byte count actually hashed lets a caller record size from the same read
    that produced the hash, rather than from a separate stat() that can
    disagree with it.
    """
    digest = hashlib.sha256()
    total = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            digest.update(chunk)
            total += len(chunk)
    return digest.hexdigest(), total


def hash_and_stat(path: Path, skip_hash: bool) -> dict:
    """Return {"size", "sha256", "changed_during_hash", "mtime_ns"} for a readable file.

    size is the byte count actually hashed (or the pre-hash stat size when
    hashing is skipped), never a second read that can disagree with what was
    hashed. When hashing runs, the file is re-stat'd afterwards; a size or
    mtime that differs from the pre-hash stat sets changed_during_hash, so a
    file that moved under the run is never silently treated as unchanged.
    mtime_ns is the post-hash (or pre-hash, when skipped) mtime, so a caller
    comparing against a baseline never has to stat the file a second time,
    which would let it raise on a file that vanished between the two calls.
    Raises OSError if the file cannot be stat'd or opened; callers decide how
    to record that.
    """
    pre = path.stat()
    if skip_hash:
        return {"size": pre.st_size, "sha256": None, "changed_during_hash": False,
                "mtime_ns": pre.st_mtime_ns}
    sha256, bytes_hashed = hash_file(path)
    post = path.stat()
    changed = post.st_size != bytes_hashed or post.st_mtime_ns != pre.st_mtime_ns
    return {"size": bytes_hashed, "sha256": sha256, "changed_during_hash": changed,
            "mtime_ns": post.st_mtime_ns}


def get_code_version() -> dict:
    """Return {"commit": ..., "dirty": ...} for the checkout this script lives in.

    A custody record should never fail a run over its own provenance, so any
    git problem, missing binary, or directory that is not a checkout falls back
    to commit "unknown" and dirty None rather than raising.
    """
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=HERE, capture_output=True, text=True,
            check=True, timeout=10,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=HERE, capture_output=True, text=True,
            check=True, timeout=10,
        ).stdout
        return {"commit": commit, "dirty": bool(status.strip())}
    except Exception:
        return {"commit": "unknown", "dirty": None}


def hash_sources(mbox_files, skip_hash, log) -> list:
    """Return one record per source archive: path as given, resolved path, size, hash.

    Hashing streams each file and can take minutes on a large archive, so the
    start and finish are logged. A missing or unreadable source does not stop
    the run: its record gets sha256 null, size null, and an "error" field
    ("missing", or the OSError text for anything else), same as the extract
    stage's own handling of a bad --mbox-file entry, so the stage's SKIP
    behaviour on master is unchanged.
    """
    if not skip_hash:
        log(f"hashing {len(mbox_files)} source file(s)")
    sources = []
    for given in mbox_files:
        resolved = Path(given).resolve()
        entry = {"path": given, "resolved": str(resolved)}
        try:
            entry.update(hash_and_stat(resolved, skip_hash))
        except OSError as exc:
            entry["size"] = None
            entry["sha256"] = None
            entry["error"] = "missing" if isinstance(exc, FileNotFoundError) else str(exc)
        sources.append(entry)
    if not skip_hash:
        log("source hashing complete")
    return sources


STAGE_DIRS = ("01_extract", "02_stripped", "03_scan", "04_render")


def snapshot_outputs(out_dir: Path) -> dict:
    """Return {relative path: (size, mtime_ns)} for every file already under the stage folders.

    Taken before stage 1 runs, so collect_outputs can tag each output against
    this baseline afterwards. A resumed run reuses an earlier attempt's
    completed-stage files untouched, so pre-existing is a real, expected state
    here, not a sign something went wrong.
    """
    snapshot = {}
    for stage_dir in STAGE_DIRS:
        stage_path = out_dir / stage_dir
        if not stage_path.exists():
            continue
        for file_path in stage_path.rglob("*"):
            if not file_path.is_file():
                continue
            rel = str(file_path.relative_to(out_dir)).replace("\\", "/")
            st = file_path.stat()
            snapshot[rel] = (st.st_size, st.st_mtime_ns)
    return snapshot


def count_output_files(out_dir: Path) -> int:
    """Return how many files sit under the four stage folders, for the pre-hash log line."""
    count = 0
    for stage_dir in STAGE_DIRS:
        stage_path = out_dir / stage_dir
        if not stage_path.exists():
            continue
        count += sum(1 for p in stage_path.rglob("*") if p.is_file())
    return count


def collect_outputs(out_dir: Path, baseline: dict) -> list:
    """Return path/size/SHA-256 for every file under the four stage folders.

    Excludes pipeline.log and the custody files themselves, neither of which
    lives under a stage folder. Each entry is tagged "origin": "new" (not in
    baseline), "modified" (in baseline but its size or mtime changed),
    "pre-existing" (untouched since the pre-stage-1 snapshot), or "unknown"
    (present but could not be stat'd or hashed, so its baseline state cannot
    be judged either way; never reported as "modified", which would claim
    more than is known). A baseline path no longer present on disk is listed
    separately with origin "removed" and size/sha256 null, so a file the run
    caused to disappear is not just silently missing from the record.
    A baseline of None means the snapshot never ran (the run was cut short
    during source hashing), so every output is "unknown" rather than "new".
    """
    outputs = []
    seen = set()
    for stage_dir in STAGE_DIRS:
        stage_path = out_dir / stage_dir
        if not stage_path.exists():
            continue
        for file_path in sorted(stage_path.rglob("*")):
            if not file_path.is_file():
                continue
            rel = str(file_path.relative_to(out_dir)).replace("\\", "/")
            seen.add(rel)
            entry = {"path": rel}
            prior = baseline.get(rel) if baseline is not None else None
            try:
                stat_info = hash_and_stat(file_path, skip_hash=False)
            except OSError as exc:
                entry["size"] = None
                entry["sha256"] = None
                entry["error"] = str(exc)
                entry["origin"] = "unknown"
                outputs.append(entry)
                continue
            mtime_ns = stat_info.pop("mtime_ns")
            entry.update(stat_info)
            current = (entry["size"], mtime_ns)
            if baseline is None:
                entry["origin"] = "unknown"
            elif prior is None:
                entry["origin"] = "new"
            else:
                entry["origin"] = "pre-existing" if prior == current else "modified"
            outputs.append(entry)
    for rel in baseline or {}:
        if rel not in seen:
            outputs.append({"path": rel, "size": None, "sha256": None, "origin": "removed"})
    return outputs


def reserve_custody_path(out_dir: Path, stamp: str) -> Path:
    """Claim and return a custody_<stamp>[-N].json path that did not already exist.

    Uses exclusive creation in a loop rather than check-then-write, so two
    pipelines starting in the same second cannot race into overwriting each
    other's record; the second one gets -1, the third -2, and so on.
    """
    candidate = out_dir / f"custody_{stamp}.json"
    n = 0
    while True:
        try:
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            n += 1
            candidate = out_dir / f"custody_{stamp}-{n}.json"
            continue
        os.close(fd)
        return candidate


def write_custody(out_dir: Path, stamp: str, record: dict) -> Path:
    """Write the custody record atomically: temp file in out_dir, then os.replace.

    The final name is reserved first so a stamp collision gets a suffix
    instead of silently overwriting an earlier run's record. Reserving it is
    inside the same protected region as the write: an interrupt between the
    reserve and the mkstemp call still cleans up the empty reserved file
    rather than leaving a zero-byte custody_*.json behind. final_path and
    tmp_name start out None so the cleanup below only unlinks what actually
    got created, whether the failure happened before either existed, after
    only the reserve, or after both. The temp file is fsync'd before the
    replace so the record cannot land truncated, and cleanup on failure runs
    for any BaseException, including KeyboardInterrupt, not only Exception.
    """
    final_path = None
    tmp_name = None
    try:
        final_path = reserve_custody_path(out_dir, stamp)
        fd, tmp_name = tempfile.mkstemp(dir=str(out_dir), prefix=".custody_", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, final_path)
        return final_path
    except BaseException:
        # Remove the temp file and the empty name reserved above, so a failed
        # write leaves no zero-byte custody file posing as a record.
        for leftover in (tmp_name, final_path):
            if leftover is None:
                continue
            try:
                os.unlink(leftover)
            except OSError:
                pass
        raise


def main():
    args = parse_args()
    out_dir = Path(args.output_dir)
    plan, inputs = build_plan(args, out_dir)

    if args.dry_run:
        for stage, command in plan:
            print(f"{stage}: {subprocess.list2cmdline(command)}")
        return 0

    problems = preflight(plan, inputs, args.skip)
    if problems:
        for problem in problems:
            print(f"cannot start: {problem}", file=sys.stderr)
        return 2

    out_dir.mkdir(parents=True, exist_ok=True)
    for stage_dir in STAGE_DIRS:
        (out_dir / stage_dir).mkdir(exist_ok=True)
    log_path = out_dir / "pipeline.log"

    def log(line):
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        print(f"[{stamp}] {line}", flush=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"[{stamp}] {line}\n")

    start_dt = datetime.now(timezone.utc)
    custody_stamp = start_dt.strftime("%Y%m%dT%H%M%SZ")

    log(f"pipeline start: {len(plan)} stage(s) -> {out_dir}")
    if args.skip:
        log(f"skipping: {', '.join(args.skip)}")

    code_info = get_code_version()

    stage_results = []
    failed_stage = None
    failed_exit_code = None
    interrupted = None
    current_stage = None
    stage_started = None
    record_write_failed = False
    sources = []
    baseline = None

    try:
        # Source hashing and the pre-stage-1 output snapshot live inside this
        # protected region (not before it): hashing tens of GB can take
        # minutes, and a Ctrl-C during that wait must still produce a record,
        # even an empty one, rather than leave the run with nothing at all.
        sources = hash_sources(args.mbox_file, args.no_source_hash, log)
        baseline = snapshot_outputs(out_dir)

        for stage, command in plan:
            current_stage = stage
            log(f"--- {stage} ---")
            stage_started = time.time()
            result = subprocess.run(command)
            elapsed = time.time() - stage_started
            stage_results.append({
                "stage": stage,
                "exit_code": result.returncode,
                "elapsed_seconds": round(elapsed, 3),
            })
            current_stage = None
            if result.returncode != 0:
                # Stop rather than feed a later stage an output that was never
                # finished. Every tool is re-runnable, so the fix is to correct the
                # cause and run the same pipeline command again.
                log(f"{stage} FAILED with exit code {result.returncode} after {elapsed:.1f}s")
                failed_stage = stage
                failed_exit_code = result.returncode
                break
            log(f"{stage} completed in {elapsed:.1f}s")
    except BaseException as exc:
        # An exception or KeyboardInterrupt here still leaves a custody record
        # rather than none at all; the finally block below writes it before
        # this re-raises with the run's normal (unhandled) exit behaviour. The
        # original exception type and message are never altered by anything
        # custody-related.
        interrupted = f"{type(exc).__name__}: {exc}"
        if current_stage is not None:
            # Cut short mid-stage: name the stage and record it as an
            # incomplete entry with whatever elapsed time it managed, so
            # stages_run still lists it rather than silently dropping it.
            failed_stage = current_stage
            failed_exit_code = None
            stage_results.append({
                "stage": current_stage,
                "exit_code": None,
                "elapsed_seconds": round(time.time() - stage_started, 3),
                "interrupted": True,
            })
        else:
            # No stage had started yet: the cut came during source hashing
            # (or the snapshot immediately after it), which the record notes
            # since failed_stage has nothing to name.
            interrupted += " (during source hashing)"
        raise
    finally:
        end_dt = datetime.now(timezone.utc)
        record = {
            "argv": sys.argv,
            "python_version": sys.version,
            "start": start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "code": code_info,
            "source_hash_skipped": bool(args.no_source_hash),
            "sources": sources,
            "stages_run": [r["stage"] for r in stage_results],
            "stages_skipped": list(args.skip),
            "stage_results": stage_results,
            "status": "incomplete" if (failed_stage or interrupted) else "complete",
            "failed_stage": failed_stage,
            "failed_exit_code": failed_exit_code,
            "interrupted": interrupted,
        }
        # Building and writing the record must never replace the run's real
        # outcome: a KeyboardInterrupt raised from inside this block is let
        # through (it is a genuine second interrupt, not a custody failure),
        # but any other exception here is logged and swallowed so the
        # original return value or the original propagating exception, if
        # any, is what the caller actually sees.
        try:
            log(f"writing custody record, hashing {count_output_files(out_dir)} output file(s)")
            record["outputs"] = collect_outputs(out_dir, baseline)
            write_custody(out_dir, custody_stamp, record)
        except Exception as exc:
            record_write_failed = True
            log(f"custody record could not be written: {type(exc).__name__}: {exc}")

    if failed_stage:
        log("pipeline stopped. Re-run this command once the cause is fixed; "
            "completed stages resume rather than redo their work.")
        return failed_exit_code

    if record_write_failed:
        # The run itself was clean, but a run without a record is not a
        # verifiable run, so this is never allowed to look like success.
        return 3

    log("pipeline complete")
    log(f"outputs under {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
