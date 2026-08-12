# email-evidence-tools

Python utilities for processing, reducing, scanning, and labeling email archives in mbox or IMAP form. Suitable for security-operations triage of an exported mailbox (phishing, exfiltration, policy violations), internal investigations, incident response, or legal evidence review. The long-running tools checkpoint their progress, so an interrupted run resumes exactly instead of duplicating or losing records.

**Author:** Jon Bowker
**License:** MIT, see [LICENSE](LICENSE).
**Requires:** Python 3.10+. `pip install -r requirements.txt`.

## Contents

<!-- BEGIN CONTENTS (auto-generated, do not edit by hand) -->

- [docs/](docs/README.md): Supporting documentation for email-evidence-tools, including workstation-local path notes for evidence archives.
- [tests/](tests/README.md): Regression tests for email-evidence-tools, built on synthetic mbox archives that reproduce the message shapes and interrupted runs that have caused silent failures.
- [CHANGELOG.md](CHANGELOG.md): Notable user-facing changes to email-evidence-tools.
- [clean_evidence_csv.py](clean_evidence_csv.py): Strips HTML tags and normalizes whitespace in evidence CSV files produced by scan_mbox_for_evidence.py.
- [evidence_text.py](evidence_text.py): Converts HTML email bodies to plain text for rendering and keyword scanning.
- [extract_messages_by_address.py](extract_messages_by_address.py): Stream-scans one or more mbox archives and extracts every message involving a given address, writing a filtered mbox and index CSV with resume-on-failure support.
- [label_matching_emails_via_imap.py](label_matching_emails_via_imap.py): Connects to an IMAP mailbox and applies a label or folder to messages whose participant addresses match configured domains.
- [pytest.ini](pytest.ini): Pytest configuration and test discovery settings.
- [render_mbox_to_markdown.py](render_mbox_to_markdown.py): Renders an mbox archive as a single chronological Markdown document with forensic headers, plain-text bodies, and a hashed attachment manifest.
- [requirements-dev.txt](requirements-dev.txt): Pinned development and test dependencies.
- [requirements.txt](requirements.txt): Pinned runtime Python dependencies.
- [run_evidence_pipeline.py](run_evidence_pipeline.py): Runs the extract, strip, scan, clean, and render tools as one ordered pipeline over an mbox archive.
- [scan_mbox_for_evidence.py](scan_mbox_for_evidence.py): Scans an mbox archive for configurable evidence keyword categories and writes one CSV row per matched sentence.
- [strip_attachments_from_mbox.py](strip_attachments_from_mbox.py): Creates an attachment-free copy of an mbox archive and writes a SHA-256 inventory CSV of every stripped attachment.
- [THEORY.md](THEORY.md): What a session needs to believe before it changes anything here.
- [WORK_BOARD.md](WORK_BOARD.md): Active work board for email-evidence-tools, showing only what is in progress right now; shipped work lives in CHANGELOG.md and the working mental model in THEORY.md.

<!-- END CONTENTS -->

## Scripts

| Script                              | Purpose                                                                                                                                                                                                                                                                             |
| ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `extract_messages_by_address.py`    | Stream-scans one or more mbox files and extracts every message where a given address (or domain substring) appears in From/To/Cc/Bcc/Reply-To/Sender/Delivered-To. Outputs a filtered mbox + index CSV. Deduped by Message-ID. Byte-offset checkpoint for resume on large archives. |
| `render_mbox_to_markdown.py`        | Renders an mbox as a chronological Markdown evidence document with full forensic headers, plain-text body, attachment manifest (each file extracted to disk and hashed).                                                                                                            |
| `scan_mbox_for_evidence.py`         | Scans an mbox file's subject lines and message bodies for configurable evidence keyword categories. One row per hit, with a `location` column saying whether it came from the subject or the body.                                                                                  |
| `run_evidence_pipeline.py`          | Runs extract, strip, scan, clean, and render in order over one archive, wiring each stage's output into the next. `--dry-run` prints the plan, `--skip` leaves stages out.                                                                                                          |
| `label_matching_emails_via_imap.py` | Connects to an IMAP mailbox and applies a label/folder to messages whose address domains match configured domains.                                                                                                                                                                  |
| `strip_attachments_from_mbox.py`    | Creates an attachment-free mbox copy and writes an attachment inventory CSV.                                                                                                                                                                                                        |
| `clean_evidence_csv.py`             | Cleans text fields in evidence CSV output by removing HTML tags and normalizing whitespace.                                                                                                                                                                                         |

## Usage

The whole sequence, one command:

```bash
python run_evidence_pipeline.py \
    --mbox-file "<path-to-export.mbox>" \
    --address "someone@example.com" \
    --output-dir "<case-folder>"
```

Add `--dry-run` to see the plan first, or `--skip strip render` to leave stages out. A stage that fails stops the run rather than feeding a half-written file to the next one; fix the cause and re-run the same command, and the checkpointed stages pick up where they stopped.

Or each tool on its own:

```bash
python extract_messages_by_address.py --mbox-file "<path-to-export.mbox>" --address "someone@example.com"
python render_mbox_to_markdown.py --mbox-file "<extracted.mbox>" --output-dir "<out-dir>"
python scan_mbox_for_evidence.py --mbox-file "<path-to-export.mbox>"
python strip_attachments_from_mbox.py --input-mbox "<path-to-export.mbox>"
python clean_evidence_csv.py --input-file "<archive>_evidence_hits.csv"
python label_matching_emails_via_imap.py --domains "example.com,example.org" --target-label "Labels/Evidence"
```

`extract_messages_by_address.py` accepts multiple `--mbox-file` arguments and treats `--address` as a case-insensitive substring, so passing `@example.com` matches every address at that domain.

All scripts also accept their inputs via environment variables for automation; see each script's docstring for the supported variables.

`label_matching_emails_via_imap.py` uses TLS by default for every host except a local mail bridge, so it works against a hosted provider as well as a bridge:

```bash
python label_matching_emails_via_imap.py --imap-host imap.example.com --imap-port 993 \
    --domains "example.com" --target-label "Labels/Evidence" --mode fast
```

Use `--starttls` for a server that upgrades a plaintext connection in place, and `--ssl off` only on a link you already trust. TLS connections validate the certificate chain and hostname; `imaplib` does not do this on its own, so pass `--tls-no-verify` deliberately if you need to reach a bridge presenting a self-signed certificate.

Outputs default to sitting beside their input rather than in the working directory, so running a tool from inside a code checkout cannot drop evidence into it. Pass `--output-file` or `--output-dir` to place them anywhere else.

## Scale and resume

The tools differ in how much of an archive they hold at once, which decides what each one is usable on:

| Script                              | Reads                                                          | Resume                                                         |
| ----------------------------------- | -------------------------------------------------------------- | -------------------------------------------------------------- |
| `extract_messages_by_address.py`    | Streams the file in chunks; memory is flat at any size.        | Byte-offset checkpoint, outputs roll back to it exactly.       |
| `strip_attachments_from_mbox.py`    | Uses `mailbox.mbox`, which indexes the whole archive up front. | Per-message checkpoint, outputs roll back to it exactly.       |
| `scan_mbox_for_evidence.py`         | Uses `mailbox.mbox`, one message body at a time after that.    | None; re-run from the start.                                   |
| `render_mbox_to_markdown.py`        | Holds every parsed message in memory to sort chronologically.  | None; render the extract, not the full archive.                |
| `label_matching_emails_via_imap.py` | One message at a time over IMAP.                               | Processed-UID state file, keyed to host, mailbox, and domains. |
| `run_evidence_pipeline.py`          | Delegates; holds nothing itself.                               | Re-run the same command, each stage resumes as it would alone. |

Run `extract_messages_by_address.py` first on a very large archive and point the rest at its much smaller output.

Resume is exactly-once for the two checkpointed tools: each records the byte length of its outputs alongside its position, and truncates back to that length before appending. A checkpoint written before this was added is refused rather than resumed, because a stale one silently duplicates records.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The suite builds synthetic mbox archives covering the message shapes that have caused silent failures: HTML-only bodies, keywords wrapped across a line break, nested MIME containers, and interrupted runs.

The tools themselves need only `python-dotenv`, and that only for the IMAP labeler's `.env` support. Everything else is standard library.

## Data hygiene

These tools operate on user-provided email archives that may contain PII, credentials, or sensitive correspondence. Treat the repository as code-only:

- Do not commit mbox files, generated CSVs, attachment inventories, checkpoints, or `.env` files. The included `.gitignore` excludes these.
- Pass inputs and outputs through command-line arguments or environment variables; never hard-code addresses, domains, or labels into the scripts.
- For long-running jobs against large archives, output to a directory outside the repository so accidental commits cannot leak data.

## Structure

```text
email-evidence-tools/
├── clean_evidence_csv.py
├── evidence_text.py
├── extract_messages_by_address.py
├── label_matching_emails_via_imap.py
├── render_mbox_to_markdown.py
├── scan_mbox_for_evidence.py
├── strip_attachments_from_mbox.py
├── tests/
├── docs/
├── requirements.txt
├── requirements-dev.txt
├── pytest.ini
├── LICENSE
├── CHANGELOG.md
├── THEORY.md
├── WORK_BOARD.md
└── README.md
```
