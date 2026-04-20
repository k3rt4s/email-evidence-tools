# crosier_bowker_complaint

**Location:** `D:\Proton Drive\My files\Code\projects\crosier_bowker_complaint\`
**Owner:** k3rt4s
**Purpose:** Python scripts for processing, analyzing, and labeling legal
evidence from email exports (mbox) related to the Crosier Bowker complaint.
**Last Updated:** 2026-04-19

---

## Scripts

| Script | Purpose |
|--------|---------|
| `scan_mbox_for_evidence.py` | Scans an mbox file and extracts emails matching evidence criteria |
| `label_cr_emails_via_imap.py` | Connects via IMAP and applies labels to matching emails |
| `strip_attachments_from_mbox.py` | Strips attachments from mbox to reduce file size |
| `clean_evidence_csv.py` | Cleans and deduplicates evidence CSV output |

---

## Usage

```powershell
D:\venvs\ai-toolkit\Scripts\python.exe scan_mbox_for_evidence.py
D:\venvs\ai-toolkit\Scripts\python.exe label_cr_emails_via_imap.py
D:\venvs\ai-toolkit\Scripts\python.exe strip_attachments_from_mbox.py
D:\venvs\ai-toolkit\Scripts\python.exe clean_evidence_csv.py
```

---

## Notes

- Uses shared venv at `D:\venvs\ai-toolkit\`
- Credentials (IMAP host, user, password) loaded from `ai-toolkit\.env`
- Input mbox files are not stored in this repo — reference local paths in script config
- Output CSVs are gitignored — do not commit evidence data

---

## Structure

```
crosier_bowker_complaint\
├── scan_mbox_for_evidence.py
├── label_cr_emails_via_imap.py
├── strip_attachments_from_mbox.py
├── clean_evidence_csv.py
└── README.md
```
