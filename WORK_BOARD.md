# Project Board: email-evidence-tools

Active work board for email-evidence-tools, showing only what is in progress right now; shipped work lives in CHANGELOG.md and the working mental model in THEORY.md.

## Status values

- `pending`: ready to start.
- `in_progress`: assigned and active.
- `blocked`: needs a decision or a missing dependency.

## In Progress

E1 to E4 are built, committed, and unmerged on branch `feature/e1-e4-hardening-pass` (commit 2147cf4). The working tree is clean and all 33 tests pass. Nothing has been merged or pushed.

Your next action: confirm with Jon whether to run `ai_development/scripts/pre_push_review.py` over the branch before merging. He was asked and powered down before answering, so do not merge or push until he picks. After he answers, run or skip the review per his answer, then merge to master and push only on an explicit go. The review question is open, not the push.

What is on the branch, as one review unit:

| id  | status      | item                                                                                                                                                                     |
| --- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| E1  | in_progress | Five verified silent defects fixed, each covered by a test that fails on the pre-fix code. See CHANGELOG.md for what each one was.                                       |
| E2  | in_progress | Repo hygiene: MIT LICENSE, .gitignore coverage for renderer and extractor outputs, README corrected to state which tools stream and which build a full index.            |
| E3  | in_progress | IMAP over TLS (`--ssl auto\|on\|off`, `--starttls`) plus a resume state file keyed to host, mailbox, label, and domain set. Selection logic is unit-tested; see Pending. |
| E4  | in_progress | Project scaffolding: this board, CHANGELOG.md, THEORY.md.                                                                                                                |

To verify the branch yourself: `C:\Code\venvs\email-evidence-tools\Scripts\python.exe -m pytest` from the repo root. To confirm the tests are real regression guards, copy `tests/`, `pytest.ini`, and `evidence_text.py` over a checkout of master and run them there; 18 fail.

## Questions for Jon

- Run `pre_push_review.py` on this branch before merging, or merge on the strength of the local review plus the test suite? Asked, unanswered.
- `ai_development/WORKSPACE_MAP.md` is modified and uncommitted in the ai_development working tree, from running `workspace_inventory.py --sync-readme` during this work. It carries two regenerated description lines: this project's, and a stale Fortivra one that had drifted from its README before this session. Commit both, commit only this project's, or leave it? Asked, unanswered. Tracked on the framework board, since that file belongs to ai_development.

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
