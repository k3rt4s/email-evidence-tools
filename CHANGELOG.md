# Changelog

Notable user-facing changes to email-evidence-tools. Newest first.

## 2026-08-11

Initial changelog. Earlier history is in git; this file starts at the hardening pass that followed the first full review of the toolkit.

### Fixed

- `strip_attachments_from_mbox.py` no longer loses attachment records on resume. The inventory CSV was rewritten from an in-memory list at the end of every run, so a resumed run replaced the whole file with only the attachments it happened to see after the resume point. Inventory rows are now appended as each message is processed, and both outputs are truncated back to their last checkpointed length on resume.
- `extract_messages_by_address.py` no longer duplicates messages on resume. Matches were written immediately but the checkpoint, including the seen Message-ID set, only flushed every 1,000 scanned messages, so a crash in between re-extracted everything since the last flush into both the output mbox and the index CSV. The checkpoint now records the byte length of both outputs and truncates them on resume.
- `scan_mbox_for_evidence.py` now scans HTML-only messages. A multipart message with no text/plain part yielded an empty body and therefore no hits at all.
- `scan_mbox_for_evidence.py` no longer discards hits whose keyword crosses a line break. Terms were matched against a whitespace-normalized body but reported from raw, unnormalized sentences, so a wrapped phrase matched the body check, matched no sentence, and was silently dropped.

### Added

- `evidence_text.py`, the shared HTML-to-text converter now used by both the renderer and the scanner.
- TLS support in `label_matching_emails_via_imap.py`: `--ssl auto|on|off` and `--starttls`. The tool previously spoke plaintext IMAP only, so it could reach a local bridge but no remote provider. Plaintext to a non-local host is now refused unless `--ssl off` is passed explicitly, so credentials cannot leak by default.
- A pytest suite under `tests/`, with a regression test per defect above, plus `requirements-dev.txt`.
- MIT LICENSE, WORK_BOARD.md, CHANGELOG.md, and THEORY.md.

### Changed

- `label_matching_emails_via_imap.py` derives its default resume state filename from the host, mailbox, target label, and domain set, so a run against different targets no longer skips messages recorded by an unrelated run. It also creates the target folder and selects the mailbox once per run instead of once per match.
- README no longer claims streaming and resume across the whole toolkit; each script now states which of the two it actually does.
- `.gitignore` covers the renderer and extractor outputs (`*_index.csv`, `*_messages.csv`, `render_manifest.json`, `attachments/`, `extract.log`, `checkpoint.json`).
