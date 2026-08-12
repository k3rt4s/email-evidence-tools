"""Runs the extract, strip, scan, clean, and render tools as one ordered pipeline over an mbox archive.

run_evidence_pipeline.py
========================
Project : email-evidence-tools
Purpose : Drives the individual tools in the order that makes sense for a case,
          passing each stage's output to the next so the six-command manual
          sequence becomes one command.

          Stages, in order:
            1. extract  - pull every message involving --address out of the
                          source archives into a much smaller working mbox
            2. strip    - write an attachment-free copy plus a hashed inventory
            3. scan     - keyword-scan the extract for evidence hits
            4. clean    - strip HTML from the hit quotes
            5. render   - build the chronological Markdown evidence document

          Stage 1 is what makes the rest affordable: scan, strip, and render all
          index or hold the whole archive, so they run against the extract and
          never against a raw multi-gigabyte export.

Inputs  : --mbox-file PATH [PATH ...]   source archives
          --address    user@example.com address the case is about
          --output-dir DIR              where the case folder goes
          --skip STAGE [STAGE ...]      stages to leave out
          --dry-run                     print the plan and exit

Outputs : Under <output-dir>, one folder per stage plus pipeline.log. Each tool
          keeps its own outputs and checkpoints, so a failed run resumes by
          re-running the same command.

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


def build_plan(args, out_dir: Path):
    """Return [(stage, [command...]), ...] for the stages that will run.

    Paths are computed here rather than discovered between stages so --dry-run
    shows the real commands, not an approximation of them.
    """
    extract_dir = out_dir / "01_extract"
    slug = args.address.split("@", 1)[0]
    slug = "".join(c if c.isalnum() or c in "_.-" else "_" for c in slug).strip("_") or "extract"
    extract_mbox = extract_dir / f"{slug}.mbox"
    hits_csv = extract_dir / f"{slug}_evidence_hits.csv"

    plan = [
        ("extract", [sys.executable, str(HERE / "extract_messages_by_address.py"),
                     "--mbox-file", *args.mbox_file,
                     "--address", args.address,
                     "--output-dir", str(extract_dir)]),
        ("strip", [sys.executable, str(HERE / "strip_attachments_from_mbox.py"),
                   "--input-mbox", str(extract_mbox),
                   "--output-mbox", str(out_dir / "02_stripped" / f"{slug}_no_attachments.mbox"),
                   "--attachment-csv", str(out_dir / "02_stripped" / "attachments_inventory.csv"),
                   "--checkpoint-file", str(out_dir / "02_stripped" / "strip.checkpoint")]),
        ("scan", [sys.executable, str(HERE / "scan_mbox_for_evidence.py"),
                  "--mbox-file", str(extract_mbox),
                  "--output-file", str(hits_csv)]),
        ("clean", [sys.executable, str(HERE / "clean_evidence_csv.py"),
                   "--input-file", str(hits_csv),
                   "--output-file", str(extract_dir / f"{slug}_evidence_hits_clean.csv")]),
        ("render", [sys.executable, str(HERE / "render_mbox_to_markdown.py"),
                    "--mbox-file", str(extract_mbox),
                    "--output-dir", str(out_dir / "03_render")]
                   + (["--title", args.title] if args.title else [])),
    ]
    return [(stage, command) for stage, command in plan if stage not in args.skip]


def main():
    args = parse_args()
    out_dir = Path(args.output_dir)
    plan = build_plan(args, out_dir)

    if args.dry_run:
        for stage, command in plan:
            print(f"{stage}: {subprocess.list2cmdline(command)}")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "02_stripped").mkdir(exist_ok=True)
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
