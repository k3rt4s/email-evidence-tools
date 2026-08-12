# Project Board: email-evidence-tools

Active work board for email-evidence-tools, showing only what is in progress right now; shipped work lives in CHANGELOG.md and the working mental model in THEORY.md.

ACTIVE THREAD: 2026-08-11 20:55

## Status values

- `pending`: ready to start.
- `in_progress`: assigned and active.
- `blocked`: needs a decision or a missing dependency.

## Work Board

| id  | status      | item                                                                                                                                                            |
| --- | ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| E1  | in_progress | Fix the five verified silent defects and cover each with a regression test. Branch `feature/e1-e4-hardening-pass`. Committed, awaiting review and merge.        |
| E2  | in_progress | Repo hygiene: MIT LICENSE, .gitignore coverage for render and extract outputs, README claims corrected to match actual behaviour. Committed on the same branch. |
| E3  | in_progress | IMAP over TLS plus a resume state file keyed to the mailbox and domain set. Committed on the same branch, untested against a live server.                       |
| E4  | in_progress | Project scaffolding: this board, CHANGELOG.md, THEORY.md. Committed on the same branch.                                                                         |

The whole branch is one review unit. Next action: Jon reviews, then merge to master and push.

## Questions for Jon

None open.

## Pending

- Exercise the IMAP labeler against a real server. The TLS paths are unit-tested for selection logic only; no test opens a socket, so `--ssl on` and `--starttls` have not been proven against a live endpoint. Verify against the local bridge and one hosted provider before relying on it.
- Scan subject lines as well as bodies. `scan_mbox_for_evidence.py` reads only the body, so a phishing lure that lives entirely in the Subject header produces no hit. Proposed during the first full review, not yet approved.
- Update the GitHub repo description. It still claims streaming at multi-GB scale for the whole toolkit; only `extract_messages_by_address.py` streams. Outward-facing, so it needs Jon's go.
- Consider a single driver that runs extract, strip, scan, clean, and render as one pipeline. Today the README documents a six-command manual sequence.
- Framework proposal, needs Jon's approval before anyone edits the framework: add `pytest.ini` to `COMMON_FILE_DESCRIPTIONS` in `ai_development/scripts/workspace_inventory.py`, so the CONTENTS manifest describes it instead of listing a bare link. Applies to every project carrying one.

## Where things live

- Shipped, user-facing history: `CHANGELOG.md`.
- What a session must believe before changing anything: `THEORY.md`.
- Usage and data hygiene: `README.md`.
