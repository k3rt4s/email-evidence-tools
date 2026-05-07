# Reorganization Map

> **AI reviewer - read before editing.** Keep this document public-safe. Do not add exact evidence paths, personal names, party names, complaint numbers, email addresses, or secrets.

The repository was reframed on 2026-05-07 as `email-evidence-tools`.

| Old Path                          | New Path                            |
| --------------------------------- | ----------------------------------- |
| Former case-specific IMAP labeler | `label_matching_emails_via_imap.py` |
| `README.md`                       | `README.md`                         |
| `requirements.txt`                | `requirements.txt`                  |
| Not previously tracked            | `.gitignore`                        |
| Not previously tracked            | `docs\content-review.md`            |
| Not previously tracked            | `docs\evidence-location.md`         |
| Not previously tracked            | `docs\reorganization-map.md`        |

The remaining script names were already generic enough to keep:

- `scan_mbox_for_evidence.py`
- `strip_attachments_from_mbox.py`
- `clean_evidence_csv.py`
