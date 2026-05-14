# email-evidence-tools

Python utilities for processing, reducing, scanning, and labeling email archives in mbox or IMAP form. Suitable for security-operations triage of an exported mailbox (phishing, exfiltration, policy violations), internal investigations, incident response, or legal evidence review. Designed for streaming and resume-on-failure so they handle multi-gigabyte archives without blowing memory or losing progress on a network disconnect.

**Author:** Jon Bowker
**Requires:** Python 3.10+. `pip install -r requirements.txt`.

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

```bash
python extract_messages_by_address.py --mbox-file "<path-to-export.mbox>" --address "someone@example.com"
python render_mbox_to_markdown.py --mbox-file "<extracted.mbox>" --output-dir "<out-dir>"
python scan_mbox_for_evidence.py --mbox-file "<path-to-export.mbox>" --output-file "evidence_hits.csv"
python strip_attachments_from_mbox.py --input-mbox "<path-to-export.mbox>"
python clean_evidence_csv.py --input-file "evidence_hits.csv" --output-file "evidence_hits_clean.csv"
python label_matching_emails_via_imap.py --domains "example.com,example.org" --target-label "Labels/Evidence"
```

`extract_messages_by_address.py` accepts multiple `--mbox-file` arguments and treats `--address` as a case-insensitive substring, so passing `@example.com` matches every address at that domain.

All scripts also accept their inputs via environment variables for automation; see each script's docstring for the supported variables.

## Data hygiene

These tools operate on user-provided email archives that may contain PII, credentials, or sensitive correspondence. Treat the repository as code-only:

- Do not commit mbox files, generated CSVs, attachment inventories, checkpoints, or `.env` files. The included `.gitignore` excludes these.
- Pass inputs and outputs through command-line arguments or environment variables; never hard-code addresses, domains, or labels into the scripts.
- For long-running jobs against large archives, output to a directory outside the repository so accidental commits cannot leak data.

## Structure

```text
email-evidence-tools/
├── clean_evidence_csv.py
├── extract_messages_by_address.py
├── label_matching_emails_via_imap.py
├── render_mbox_to_markdown.py
├── scan_mbox_for_evidence.py
├── strip_attachments_from_mbox.py
├── requirements.txt
└── README.md
```
