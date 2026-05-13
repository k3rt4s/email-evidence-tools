# email-evidence-tools

> **AI reviewer - read before editing.** Start at the master `Code/README.md` ("AI Session Rules" section) and any README upstream of this one. It is the single source of truth for venvs, path conventions, archive/backup rules, markdown conventions, and every repo-wide rule.

**Location:** `C:\Code\projects\email-evidence-tools\`
**Owner:** email-evidence-tools maintainers
**Purpose:** Python utilities for processing, reducing, scanning, cleaning, and labeling email evidence exports.
**Last Updated:** 2026-05-07

## Review Summary

This repo was reviewed and reframed from a case-specific evidence workflow into neutral email evidence tooling. Evidence files, generated CSVs, IMAP credentials, exact local evidence paths, party names, and case identifiers must stay outside git.

## Scripts

| Script                              | Purpose                                                                                                                                                                                                                                                                             |
| ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `extract_messages_by_address.py`    | Stream-scans one or more mbox files and extracts every message where a given address (or domain substring) appears in From/To/Cc/Bcc/Reply-To/Sender/Delivered-To. Outputs a filtered mbox + index CSV. Deduped by Message-ID. Byte-offset checkpoint for resume on large archives. |
| `render_mbox_to_markdown.py`        | Renders an mbox as a chronological Markdown evidence document with full forensic headers, plain-text body, attachment manifest (each file extracted to disk and hashed).                                                                                                            |
| `scan_mbox_for_evidence.py`         | Scans an mbox file and extracts messages matching configurable evidence keyword categories.                                                                                                                                                                                         |
| `label_matching_emails_via_imap.py` | Connects to an IMAP mailbox and applies a label/folder to messages whose address domains match configured domains.                                                                                                                                                                  |
| `strip_attachments_from_mbox.py`    | Creates an attachment-free mbox copy and writes an attachment inventory CSV.                                                                                                                                                                                                        |
| `clean_evidence_csv.py`             | Cleans text fields in evidence CSV output by removing HTML tags and normalizing whitespace.                                                                                                                                                                                         |

## Usage

Use the project venv explicitly:

```powershell
C:\Code\venvs\email-evidence-tools\Scripts\python.exe .\extract_messages_by_address.py --mbox-file "<path-to-export.mbox>" --address "someone@example.com"
C:\Code\venvs\email-evidence-tools\Scripts\python.exe .\render_mbox_to_markdown.py --mbox-file "<extracted.mbox>" --output-dir "<out-dir>"
C:\Code\venvs\email-evidence-tools\Scripts\python.exe .\scan_mbox_for_evidence.py --mbox-file "<path-to-export.mbox>" --output-file ".\reports\evidence_hits.csv"
C:\Code\venvs\email-evidence-tools\Scripts\python.exe .\strip_attachments_from_mbox.py --input-mbox "<path-to-export.mbox>"
C:\Code\venvs\email-evidence-tools\Scripts\python.exe .\clean_evidence_csv.py --input-file ".\reports\evidence_hits.csv" --output-file ".\reports\evidence_hits_clean.csv"
C:\Code\venvs\email-evidence-tools\Scripts\python.exe .\label_matching_emails_via_imap.py --domains "example.com,example.org" --target-label "Labels/Evidence"
```

`extract_messages_by_address.py` accepts multiple `--mbox-file` arguments and `--address` as a case-insensitive substring (so passing `@example.com` matches every address at that domain). Output goes under `C:\Code_data\email-evidence-tools\extracts\` by default, in line with AGENTS.md §3.

The scripts also support environment variables for automation. See each script header for the supported variables.

## Evidence Location Notes

- Public-safe evidence path history is documented in `docs\evidence-location.md`.
- Exact local paths belong only in `docs\evidence-location.local.md`, which is ignored by git.
- Evidence inputs and outputs must stay outside this repository or under gitignored local output folders.

## Data Safety

- Do not commit mbox files, generated CSVs, attachment inventories, checkpoints, `.env` files, or local evidence path notes.
- Do not commit personal names, party names, complaint numbers, exact evidence paths, email addresses, or passwords.
- Use environment variables or command-line arguments for inputs, outputs, target domains, labels, and IMAP connection settings.

## Structure

```text
email-evidence-tools\
├── docs\
│   └── evidence-location.md
├── clean_evidence_csv.py
├── extract_messages_by_address.py
├── label_matching_emails_via_imap.py
├── render_mbox_to_markdown.py
├── scan_mbox_for_evidence.py
├── strip_attachments_from_mbox.py
├── requirements.txt
└── README.md
```
