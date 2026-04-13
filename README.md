# Crosier_Bowker — Legal Evidence Review

**Case:** Tennessee Board of Professional Responsibility, Complaint No. 105302-2026-CAP  
**Author:** Jonathan David Bowker

---

## Purpose

This project contains scripts for extracting, labeling, and cleaning email evidence
from a Proton Mail archive in support of the above complaint against former counsel.

---

## Recommended Location

This project should live **outside** of `ai-toolkit/` — it is personal legal evidence,
not professional tooling.  Suggested path:

```
D:\Proton Drive\My files\Post Divorce\Diane Billing Issues\Crosier_Bowker\
```

---

## Scripts

### 1. `scan_mbox_for_evidence.py`
**Was:** `email_parsing.py`

Parses an `.mbox` archive and searches every message body for keyword categories
relevant to the complaint (billing, settlement strategy, communication failures,
parenting time, etc.).  Outputs one CSV row per matched sentence.

**Run first.**

```
python scan_mbox_for_evidence.py
```

Output: `mbox_evidence_hits_clean.csv`

---

### 2. `clean_evidence_csv.py`
**Was:** `clean.py`

Post-processes the CSV from step 1: strips HTML tags from the `exact_text` column
and collapses whitespace.

**Run second** (after `scan_mbox_for_evidence.py`).

```
python clean_evidence_csv.py
```

Output: `mbox_evidence_hits_clean2.csv`

---

### 3. `strip_attachments_from_mbox.py`
**Was:** `strip_attachments.py`

Creates an attachment-free copy of an mbox archive.  Useful for faster scanning
or for sharing the message corpus without binary attachments.  Generates a separate
CSV inventory of all stripped attachments (filename, size, SHA-256).

Resumable — safe to interrupt and restart.

```
python strip_attachments_from_mbox.py
```

Output: `<source>_NO_ATTACHMENTS`, `attachments_inventory.csv`

---

### 4. `label_cr_emails_via_imap.py`
**Was:** `cr2.py`

Connects to a local ProtonMail Bridge IMAP endpoint and applies a `Labels/CR`
label to all messages involving Crosier-related domains.  Requires a `.env` file
with IMAP credentials.

Resumable — tracks processed UIDs in `processed_uids_cr.txt`.

```
python label_cr_emails_via_imap.py
```

Requires `.env`:
```
IMAP_USER=<bridge username>
IMAP_PASS=<bridge password>
```

---

## Data Files (not in this repo)

| File | Description |
|------|-------------|
| `Crosier_Bowker_Emails.mbox` | Source email archive |
| `mbox_evidence_hits_clean.csv` | Raw scan output (~6 MB) |
| `mbox_evidence_hits_clean2.csv` | Cleaned scan output (~2 MB) |
| `mbox_evidence_table.csv` | Summary table |

---

## Dependencies

```
pip install pandas python-dotenv
```
