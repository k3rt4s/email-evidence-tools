# crosier_bowker_complaint

> **AI reviewer - read before editing.** Start at the master `Code/README.md` ("AI Session Rules" section) and any README upstream of this one. It is the single source of truth for venvs, path conventions, archive/backup rules, markdown conventions, and every repo-wide rule - the rules live there so they don't need to be repeated per file.

**Location:** `C:\Code\projects\crosier_bowker_complaint\`
**Owner:** k3rt4s
**Purpose:** Python scripts for processing, analyzing, and labeling legal
evidence from email exports (mbox) related to the Crosier Bowker complaint.
**Last Updated:** 2026-04-19

---

## Scripts

| Script                           | Purpose                                                           |
| -------------------------------- | ----------------------------------------------------------------- |
| `scan_mbox_for_evidence.py`      | Scans an mbox file and extracts emails matching evidence criteria |
| `label_cr_emails_via_imap.py`    | Connects via IMAP and applies labels to matching emails           |
| `strip_attachments_from_mbox.py` | Strips attachments from mbox to reduce file size                  |
| `clean_evidence_csv.py`          | Cleans and deduplicates evidence CSV output                       |

---

## Usage

```powershell
C:\Code\venvs\ai-toolkit\Scripts\python.exe scan_mbox_for_evidence.py
C:\Code\venvs\ai-toolkit\Scripts\python.exe label_cr_emails_via_imap.py
C:\Code\venvs\ai-toolkit\Scripts\python.exe strip_attachments_from_mbox.py
C:\Code\venvs\ai-toolkit\Scripts\python.exe clean_evidence_csv.py
```

---

## Notes

- Uses shared venv at `C:\Code\venvs\ai-toolkit\`
- Credentials (IMAP host, user, password) loaded from `ai-toolkit\.env`
- Input mbox files are not stored in this repo — reference local paths in script config
- Output CSVs are gitignored — do not commit evidence data

---

## Structure

```text
crosier_bowker_complaint\
├── scan_mbox_for_evidence.py
├── label_cr_emails_via_imap.py
├── strip_attachments_from_mbox.py
├── clean_evidence_csv.py
└── README.md
```
