# Project Board: email-evidence-tools

Active work board for email-evidence-tools, showing only what is in progress right now; shipped work lives in CHANGELOG.md and the working mental model in THEORY.md.

## Status values

- `pending`: ready to start.
- `in_progress`: assigned and active.
- `blocked`: needs a decision or a missing dependency.

## In Progress

Nothing active.

## Questions for Jon

None open.

## Pending

Empty. Everything raised in the 2026-08-12 review shipped, including the live verification: the IMAP labeler has been exercised against the real Proton Bridge for authentication, enumeration, server-side search and labelling, and over implicit TLS against a stub server holding a real certificate. The live tests live in `tests/test_live_imap.py` and skip unless `EET_LIVE_ENV_FILE` points at credentials.

When new work arrives, add it here. Read THEORY.md first: it records the constraints that are not visible in the code, including the two `imaplib` behaviours that have each already caused a silent failure in this tool.

## Where things live

- Shipped, user-facing history: `CHANGELOG.md`.
- What a session must believe before changing anything: `THEORY.md`.
- Usage, scale limits, and data hygiene: `README.md`.
