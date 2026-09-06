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

Empty. When new work arrives, add it here as a bullet carrying a `score:` and a `return:` block per
`ai_development/docs/board-scoring.md`, and score it before proposing an order.

## Standing notes

Records and reading rules for this board, not items. `ai_development/scripts/score_board.py` reads the
live sections and lists every entry there that has no score block, so a record belongs here, where the
script does not look. An entry that turns back into work moves up to Pending with a block.

- Everything raised in the 2026-08-12 review shipped, including the live verification: the IMAP labeler
  has been exercised against the real Proton Bridge for authentication, enumeration, server-side search
  and labelling, and over implicit TLS against a stub server holding a real certificate. The live tests
  live in `tests/test_live_imap.py` and skip unless `EET_LIVE_ENV_FILE` points at credentials.
- Read THEORY.md before changing anything: it records the constraints that are not visible in the code,
  including the two `imaplib` behaviours that have each already caused a silent failure in this tool.
- The candidate features live in `FUTURE_FEATURES.md` under its Scored index, scored the same way.
  Nothing moves from there to Pending except on Jon's say-so.

## Where things live

- Shipped, user-facing history: `CHANGELOG.md`.
- What a session must believe before changing anything: `THEORY.md`.
- Usage, scale limits, and data hygiene: `README.md`.
