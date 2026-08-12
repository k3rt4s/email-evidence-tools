"""Strips HTML tags and normalizes whitespace in evidence CSV files produced by scan_mbox_for_evidence.py.

clean_evidence_csv.py
=====================
Project : email-evidence-tools
Purpose : Post-processing step for the output of scan_mbox_for_evidence.py.
          Reads the raw evidence CSV, strips HTML tags from the `exact_text` column,
          and collapses excess whitespace so hits are readable in a spreadsheet or
          when pasted into correspondence.

Input   : --input-file or INPUT_FILE
Output  : --output-file or OUTPUT_FILE. Defaults to <input>_clean.csv beside the
          input, never the working directory.

Usage   : python clean_evidence_csv.py --input-file evidence_hits.csv --output-file evidence_hits_clean.csv

Note    : This script is non-destructive; the original CSV is not modified.
          Every column is carried through unchanged except `exact_text`.
"""

import csv
import os
import re
import sys
import argparse
from pathlib import Path

TEXT_COLUMN = "exact_text"

# The scanner can quote a whole HTML message body, so a single field runs to tens
# of thousands of characters and trips the csv module's default field limit.
csv.field_size_limit(min(2**31 - 1, sys.maxsize))


def clean_text(text):
    """Remove HTML tags and normalize whitespace in a text value."""
    if text is None:
        return ""
    # Strip HTML tags
    text = re.sub(r"<[^>]+>", " ", str(text))
    # Collapse runs of whitespace to a single space
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_args():
    """Parse command-line arguments and environment-variable fallbacks."""
    parser = argparse.ArgumentParser(
        description="Clean text fields in an evidence CSV."
    )
    parser.add_argument(
        "--input-file",
        default=os.getenv("INPUT_FILE"),
        help="Input CSV path. Defaults to INPUT_FILE.",
    )
    parser.add_argument(
        "--output-file",
        default=os.getenv("OUTPUT_FILE"),
        help="Output CSV path. Defaults to <input>_clean.csv beside the input.",
    )
    args = parser.parse_args()
    if not args.input_file:
        parser.error("--input-file is required unless INPUT_FILE is set.")
    if not args.output_file:
        source = Path(args.input_file)
        args.output_file = str(source.with_name(f"{source.stem}_clean.csv"))
    return args


def main():
    args = parse_args()
    rows_written = 0

    with open(args.input_file, newline="", encoding="utf-8") as src:
        reader = csv.DictReader(src)
        if reader.fieldnames is None:
            sys.exit(f"{args.input_file} is empty; nothing to clean.")
        if TEXT_COLUMN not in reader.fieldnames:
            sys.exit(
                f"{args.input_file} has no '{TEXT_COLUMN}' column "
                f"(found: {', '.join(reader.fieldnames)}). "
                "This tool cleans the output of scan_mbox_for_evidence.py."
            )

        with open(args.output_file, "w", newline="", encoding="utf-8") as dst:
            writer = csv.DictWriter(dst, fieldnames=reader.fieldnames)
            writer.writeheader()
            for row in reader:
                row[TEXT_COLUMN] = clean_text(row.get(TEXT_COLUMN))
                writer.writerow(row)
                rows_written += 1

    print(f"Done. {rows_written:,} rows cleaned -> {args.output_file}")


if __name__ == "__main__":
    main()
