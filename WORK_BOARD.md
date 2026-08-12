# Project Board: email-evidence-tools

Active work board for email-evidence-tools, showing only what is in progress right now; shipped work lives in CHANGELOG.md and the working mental model in THEORY.md.

## Status values

- `pending`: ready to start.
- `in_progress`: assigned and active.
- `blocked`: needs a decision or a missing dependency.

## In Progress

Nothing active. The hardening pass shipped on 2026-08-12: merged to master, pushed to origin, feature branch deleted, 45 tests passing on master. What it changed is in CHANGELOG.md; what a session must believe before touching the code is in THEORY.md.

Pick the next item from Pending below, or ask Jon what he wants.

## Questions for Jon

None open.

## Pending

- Exercise the IMAP labeler against a real server. Nothing here has ever opened a socket: the transport tests cover which mode is selected and that a verifying SSL context reaches `imaplib`, but no test connects. Verify `--ssl on` against a hosted provider and `--starttls` against one that advertises it, and check whether the local bridge needs `--tls-no-verify` for its self-signed certificate. This is the only unproven path in shipped code.
- Scan subject lines as well as bodies. `scan_mbox_for_evidence.py` reads bodies only, so a lure living entirely in the `Subject` header produces no hit. Decide first what goes in the `exact_text` column for a subject hit, since that column is the quoted evidence.
- Consider a single driver that runs extract, strip, scan, clean, and render as one pipeline. The README documents a six-command manual sequence. Convenience only, no correctness argument behind it.
- Framework proposal, needs Jon's approval before anyone edits the framework: add `pytest.ini` to `COMMON_FILE_DESCRIPTIONS` in `ai_development/scripts/workspace_inventory.py`, so the CONTENTS manifest describes it instead of listing a bare link. Affects every project carrying one, so it belongs to the framework board once approved.

## Where things live

- Shipped, user-facing history: `CHANGELOG.md`.
- What a session must believe before changing anything: `THEORY.md`.
- Usage, scale limits, and data hygiene: `README.md`.
