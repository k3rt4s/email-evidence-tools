# Future features

Backlog of candidate features not yet scheduled.

## Scored index

One bullet per unshipped feature in this file, scored with `ai_development/docs/board-scoring.md`.
Keep it current when a feature is added, moved or dropped: a feature that ships or moves onto the
board loses its bullet here on the day it moves.

The custody-log, header-scan and single-part-attachment entries moved onto the board on 2026-09-24
and shipped on 2026-09-25 (see CHANGELOG.md).

- rfc822-attachment: `strip_attachments_from_mbox.py` mishandles a single-part message whose top-level
  Content-Type is `message/rfc822` with `Content-Disposition: attachment`. The inventory row shows Size 0
  and the SHA-256 of empty bytes, and the message stays whole in the stripped copy, so the inventory
  misstates what the archive held. Found in review on 2026-09-25; it predates the single-part change.
  Start with a failing test. `score: kind=bug gain=2/6/30 p=0.2 hours=0.5/1/2 rev=two-way conf=assessed`

## Ingested 2026-08-21: public talk and summit digests

- Preserving logs/traffic analysis is critical to legal analysis of notice requirements, citable in chain-of-custody docs. Source: Threat Hunting Summit 2026, panel 05:03:20, digest_threat_hunting_summit_2026.md
