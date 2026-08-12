# Project Board: email-evidence-tools

Active work board for email-evidence-tools, showing only what is in progress right now; shipped work lives in CHANGELOG.md and the working mental model in THEORY.md.

## Status values

- `pending`: ready to start.
- `in_progress`: assigned and active.
- `blocked`: needs a decision or a missing dependency.

## In Progress

Nothing active. The project closed out on 2026-08-12: everything on the board shipped, merged to master, and pushed. 64 tests pass on master.

## Questions for Jon

None open.

## Pending

- Authenticate the IMAP labeler against a real mailbox. Everything else about it is now covered: the transport was verified against the live local bridge, and a stub IMAP server exercises login, search, fetch and COPY. What has never run is a session against a real server with real credentials, which needs the Proton Bridge password from its GUI, or a hosted account. Until then `--ssl on` against a hosted provider is unproven end to end.

## Where things live

- Shipped, user-facing history: `CHANGELOG.md`.
- What a session must believe before changing anything: `THEORY.md`.
- Usage, scale limits, and data hygiene: `README.md`.
