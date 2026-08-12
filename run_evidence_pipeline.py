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

Outputs : Under <output-dir>: 01_extract, 02_stripped, 03_scan (which holds both
          the raw and the cleaned hit CSVs, since clean rewrites what scan wrote),
          04_render, and pipeline.log. Each tool keeps its own outputs and
          checkpoints, so a failed run resumes by re-running the same command.

Usage   : python run_evidence_pipeline.py \\
              --mbox-file "D:\\export\\All Mail" \\
              --address "someone@example.com" \\
              --output-dir "C:\\Code_data\\email-evidence-tools\\case-01"
"""

import argparse
import subprocess
import sys
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
    for stage_dir in ("01_extract", "02_stripped", "03_scan", "04_render"):
        (out_dir / stage_dir).mkdir(exist_ok=True)
    log_path = out_dir / "pipeline.log"

    def log(line):
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        print(f"[{stamp}] {line}", flush=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"[{stamp}] {line}\n")

    log(f"pipeline start: {len(plan)} stage(s) -> {out_dir}")
    if args.skip:
        log(f"skipping: {', '.join(args.skip)}")

    for stage, command in plan:
        log(f"--- {stage} ---")
        started = time.time()
        result = subprocess.run(command)
        elapsed = time.time() - started
        if result.returncode != 0:
            # Stop rather than feed a later stage an output that was never
            # finished. Every tool is re-runnable, so the fix is to correct the
            # cause and run the same pipeline command again.
            log(f"{stage} FAILED with exit code {result.returncode} after {elapsed:.1f}s")
            log("pipeline stopped. Re-run this command once the cause is fixed; "
                "completed stages resume rather than redo their work.")
            return result.returncode
        log(f"{stage} completed in {elapsed:.1f}s")

    log("pipeline complete")
    log(f"outputs under {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
