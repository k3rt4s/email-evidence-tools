# Project Board: email-evidence-tools

Active work board for email-evidence-tools, showing only what is in progress right now; shipped work lives in CHANGELOG.md and the working mental model in THEORY.md.

## Status values

- `pending`: ready to start.
- `in_progress`: assigned and active.
- `blocked`: needs a decision or a missing dependency.

## In Progress

Nothing active. The project closed out on 2026-08-12: everything on the board shipped, merged to master, and pushed. 64 tests pass on master, plus 6 live tests that skip unless pointed at a real IMAP server; those were run once against the local bridge and passed.

## Questions for Jon

None open.

## Pending

- Optional: run the one live test that writes. `tests/test_live_imap.py` covers the labeler against the real bridge, but its labelling test stays skipped unless `EET_LIVE_LABEL_TARGET` names a folder it may create, because applying a label copies a message into a real mailbox and the tool has no undo. Everything read-only is proven. Set that variable, run it, and delete the folder afterwards if you want the write path covered too.
- Optional: prove `--ssl on` against a hosted provider. Implicit TLS is covered by unit tests and by STARTTLS on the bridge, but no test has opened an implicit-TLS session to a server on port 993. Needs an account somewhere other than the local bridge.

## Where things live

- Shipped, user-facing history: `CHANGELOG.md`.
- What a session must believe before changing anything: `THEORY.md`.
- Usage, scale limits, and data hygiene: `README.md`.
