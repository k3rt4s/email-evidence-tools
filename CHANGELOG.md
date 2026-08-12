# Changelog

Notable user-facing changes to email-evidence-tools. Newest first.

## 2026-08-12, later

Closing out the remaining board items.

- `scan_mbox_for_evidence.py` scans the Subject header as well as the body. A lure that lives entirely in the subject ("Urgent payment") never appears in the body, so a body-only scan reported nothing for the message doing the work. Each row gains a `location` column saying whether the hit came from the subject or the body, and the quoted `exact_text` is the subject line for a subject hit.
- `scan_mbox_for_evidence.py` decodes RFC 2047 headers before matching. A subject encoded as `=?utf-8?B?...?=`, which is any subject containing a non-ASCII character, previously matched nothing at all.
- Added `run_evidence_pipeline.py`, which runs extract, strip, scan, clean, and render in order over one archive and wires each stage's output into the next. `--dry-run` prints the plan, `--skip` leaves stages out, and a failing stage stops the run rather than handing a half-written file to the next one.
- Added `tests/imap_stub.py`, an in-process IMAP server, and the session tests that drive the labeler through login, search, fetch and COPY against it. The labeler's behaviour once connected was previously untested.
- Verified the transport against the live local bridge: certificate verification rejects its self-signed certificate as it should, `--tls-no-verify` upgrades to TLS 1.3, and `auto` selects plaintext for loopback. Login against a real server still needs the bridge password and remains unexercised.

## 2026-08-12

Findings from the pre-push peer review of the hardening pass below, fixed before it landed.

- Security: TLS connections in `label_matching_emails_via_imap.py` now validate the certificate chain and hostname. `imaplib` falls back to `ssl._create_stdlib_context()` for both implicit TLS and STARTTLS, and that context sets `check_hostname=False` and `verify_mode=CERT_NONE`, so the connection added a day earlier was encrypted but unauthenticated. `--tls-no-verify` opts out for a bridge with a self-signed certificate, and says so on stdout.
- `strip_attachments_from_mbox.py` no longer duplicates a message when an I/O error interrupts it mid-write. The inventory rows moved inside the retry block during yesterday's work, so a failure between writing the message and writing its rows re-ran the whole block and appended the message twice. Each attempt now rewinds both outputs to where they stood before the message.
- `scan_mbox_for_evidence.py` reads every `text/*` part, not only `text/plain` and `text/html`. Restricting it to those two would have skipped `text/enriched` and similar legacy parts that the previous implementation did read.
- `scan_mbox_for_evidence.py` and `clean_evidence_csv.py` default their output beside the input archive instead of into the working directory, so running either from inside a code checkout cannot write evidence into it.
- `clean_evidence_csv.py` uses the standard-library `csv` module instead of pandas, and raises the field-size limit so a quoted HTML body does not trip it. It now fails loudly when the input has no `exact_text` column rather than emitting a copy. pandas leaves `requirements.txt`, whose only remaining entry is `python-dotenv`.

## 2026-08-11

Initial changelog. Earlier history is in git; this file starts at the hardening pass that followed the first full review of the toolkit.

Fixed:

- `strip_attachments_from_mbox.py` no longer loses attachment records on resume. The inventory CSV was rewritten from an in-memory list at the end of every run, so a resumed run replaced the whole file with only the attachments it happened to see after the resume point. Inventory rows are now appended as each message is processed, and both outputs are truncated back to their last checkpointed length on resume.
- `extract_messages_by_address.py` no longer duplicates messages on resume. Matches were written immediately but the checkpoint, including the seen Message-ID set, only flushed every 1,000 scanned messages, so a crash in between re-extracted everything since the last flush into both the output mbox and the index CSV. The checkpoint now records the byte length of both outputs and truncates them on resume.
- `scan_mbox_for_evidence.py` now scans HTML-only messages. A multipart message with no text/plain part yielded an empty body and therefore no hits at all.
- `scan_mbox_for_evidence.py` no longer discards hits whose keyword crosses a line break. Terms were matched against a whitespace-normalized body but reported from raw, unnormalized sentences, so a wrapped phrase matched the body check, matched no sentence, and was silently dropped.
- `strip_attachments_from_mbox.py` keeps nested MIME containers. Surviving parts were re-attached at the top level, so a `multipart/alternative` came back as siblings and a reader rendered both the plain and HTML versions.

Added:

- `evidence_text.py`, the shared HTML-to-text converter now used by both the renderer and the scanner.
- TLS support in `label_matching_emails_via_imap.py`: `--ssl auto|on|off` and `--starttls`. The tool previously spoke plaintext IMAP only, so it could reach a local bridge but no remote provider. Plaintext to a non-local host is now refused unless `--ssl off` is passed explicitly, so credentials cannot leak by default.
- A pytest suite under `tests/`, with a regression test per defect above, plus `requirements-dev.txt`.
- MIT LICENSE, WORK_BOARD.md, CHANGELOG.md, and THEORY.md.

Changed:

- `label_matching_emails_via_imap.py` derives its default resume state filename from the host, mailbox, target label, and domain set, so a run against different targets no longer skips messages recorded by an unrelated run. It also creates the target folder and selects the mailbox once per run instead of once per match.
- README no longer claims streaming and resume across the whole toolkit; each script now states which of the two it actually does.
- `.gitignore` covers the renderer and extractor outputs (`*_index.csv`, `*_messages.csv`, `render_manifest.json`, `attachments/`, `extract.log`, `checkpoint.json`).
