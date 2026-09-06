# Future features

Backlog of candidate features not yet scheduled.

## Scored index

One bullet per unshipped feature in this file, scored with `ai_development/docs/board-scoring.md`.
Keep it current when a feature is added, moved or dropped: a feature that ships or moves onto the
board loses its bullet here on the day it moves.

- **transport-headers** Preserve the mail transport header chain (`Received`, `Return-Path`, `Authentication-Results`, `DKIM-Signature`) in the rendered evidence document, its CSV and its manifest, so a delivery or notice argument is citable from the exhibit instead of reconstructed from the source archive. Points at "Ingested 2026-08-21: public talk and summit digests". `score: kind=feature gain=0.5/2/6 p=0.3 freq=2 hours=0.5/1/2 ai=2 risk=0.1x0.5 rev=two-way conf=opinion flags=legal id=transport-headers` `return: likelihood 1 in 3 per rendered case that delivery or notice is actually at issue, about 2 renders a year, so about once in two years; estimated, nothing was counted, there is no run counter and C:\Code_data\email-evidence-tools is empty; impact 0.5 to 6 h of Jon's time on the one occurrence, going back to the source archive to pull the Received chain and authentication results for the messages at issue by hand, re-hashing what he quotes, and reissuing an exhibit that was already served; evidence render_mbox_to_markdown.py lines 399 to 421 write the addressing, threading and integrity headers and no transport headers, and its render_manifest.json (lines 338 to 358) carries file and per-message SHA-256 only; git log over that file since the repo opened shows no Received handling; the request itself is the 2026-08-21 digest ingest bullet below`
  - `worker: sonnet 1.5/3/6 h`

## Ingested 2026-08-21: public talk and summit digests

- Preserving logs/traffic analysis is critical to legal analysis of notice requirements, citable in chain-of-custody docs. Source: Threat Hunting Summit 2026, panel 05:03:20, digest_threat_hunting_summit_2026.md
