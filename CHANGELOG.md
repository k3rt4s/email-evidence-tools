# Changelog

Notable user-facing changes to email-evidence-tools. Newest first.

## 2026-08-12, live verification

Running the live tests against a real mailbox found a silent failure, which is what they were written for.

- `label_matching_emails_via_imap.py` reported labeling messages it had not labeled. `imaplib` returns `('NO', ...)` for a refused command instead of raising, and both the folder creation and the COPY discarded that result, so a server that rejected the folder name produced a run that created nothing, copied nothing, and finished by printing how many messages it had labeled. Against Proton Bridge, which requires a namespace prefix such as `Labels/Evidence` and refuses a bare top-level name, that is the default outcome. Both calls now check the response: an unusable folder name stops the run with a message naming the likely cause, and a refused COPY raises rather than counting as a success.
- Mailbox names are quoted on the wire. `imaplib` passes them through as given, so a target label containing a space arrived as two arguments.
- The run summary now reports messages the server would not hand over. They were skipped silently, which reads as "no match" in the totals.
- Added `tests/test_imap_tls_session.py`, which drives a full labeling session over implicit TLS against a stub server holding an ephemeral certificate. It covers what no live test could without a hosted account: that `--ssl on` completes a session, and that it refuses both an untrusted certificate and a trusted one issued for a different hostname.
- The live labeling test now deletes the folder it creates, so running it leaves the mailbox as it found it.

## 2026-08-12, close-out

Closing out the remaining board items.

- `scan_mbox_for_evidence.py` scans the Subject header as well as the body. A lure that lives entirely in the subject ("Urgent payment") never appears in the body, so a body-only scan reported nothing for the message doing the work. Each row gains a `location` column saying whether the hit came from the subject or the body, and the quoted `exact_text` is the subject line for a subject hit.
- `scan_mbox_for_evidence.py` decodes RFC 2047 headers before matching. A subject encoded as `=?utf-8?B?...?=`, which is any subject containing a non-ASCII character, previously matched nothing at all.
- Added `run_evidence_pipeline.py`, which runs extract, strip, scan, clean, and render in order over one archive, replacing five separate commands. Each stage reads what the one before it wrote: strip works on the extract, scan on the stripped copy, clean on scan's CSV, and render goes back to the extract because the stripped copy no longer holds the attachments it must hash. `--dry-run` prints the plan, `--skip` leaves stages out and fails immediately if a skipped stage was going to produce something a later one needs, and a failing stage stops the run rather than handing a half-written file forward.
- Added `tests/imap_stub.py`, an in-process IMAP server, and the session tests that drive the labeler through login, search, fetch and COPY against it. The labeler's behaviour once connected was previously untested.
- Added `tests/test_live_imap.py`, which exercises the labeler against a real IMAP server and skips unless `EET_LIVE_ENV_FILE` points at credentials. It reads that file directly rather than taking anything on a command line. Verified against the live Proton Bridge: authentication over the auto transport and over STARTTLS, certificate verification correctly rejecting the bridge's self-signed certificate, full-scan UID enumeration, and the server accepting the fast scan's HEADER search syntax. The single test that writes a label needs `EET_LIVE_LABEL_TARGET` named as well and stays skipped otherwise.
- Recorded what the fast scan actually costs: about fifteen minutes against a large All Mail, since it is four server-side searches over the whole archive.

## 2026-08-12, hardening review

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
