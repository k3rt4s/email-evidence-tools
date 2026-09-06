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

## Standing rules for a run group

Not items. These are the rules every run group on this board inherits, from
`ai_development/PLAYBOOK.md` and this project's own constraints. A group brief repeats them
rather than linking to them, because the group's session cannot see this board.

- This repository is public (`k3rt4s/email-evidence-tools`). A push publishes. No group pushes, no
  group merges to `master`, no group opens a pull request. Each group commits to its own branch and
  stops there. Jon reviews and merges.
- Work in the worktree the item names, never in `C:\Code\projects\email-evidence-tools` itself.
  Another session may hold that tree.
- Workers never commit. The group orchestrator reviews each result against the item's definition of
  done and commits what meets it. Workers kill only processes they started, by PID.
- Every commit is authored by Jon Bowker alone, the message says what changed, and it carries no AI
  attribution of any kind (CORE-05, CORE-06).
- Generated output, logs and reports go to `C:\Code_data\email-evidence-tools\`, never into the
  repository (CORE-01).
- Tests run from `C:\Code\venvs\email-evidence-tools\Scripts\python.exe`, output redirected to a log
  file under the data root, and the log is what gets read.
- Failure budget: if the same test fails twice after a fix attempt, stop. Write the failing output to
  the data root, leave the branch as it stands, and record the stop on this board. Do not widen the
  change to make a test pass.
- Overrun: if a group passes its `worker:` high estimate in wall clock, stop at the last green commit
  and record what is left in its run log. Do not carry on.

## Pending

Two groups. They share no file and depend on nothing the other produces, so both run at the same
time, each in its own worktree on its own branch. Every decision a group needs is written into its
item below, and the rules both groups inherit are in Standing rules for a run group above.
A group decides nothing for itself and asks Jon nothing.

### Group 1, transport headers in the rendered exhibit

Branch `feature/transport-headers-in-exhibit` off `master`. Worktree
`C:\Code\worktrees\eet-transport-headers`. Run log
`C:\Code_data\email-evidence-tools\RUN_2026-09-06_G1.md`.

- **transport-headers** Preserve the mail transport header chain (`Received`, `Return-Path`, `Authentication-Results`, `DKIM-Signature`) in the rendered evidence document, its CSV and its manifest, so a delivery or notice argument is citable from the exhibit instead of reconstructed from the source archive. `score: kind=feature gain=0.5/2/6 p=0.3 freq=2 hours=0.5/1/2 ai=2 risk=0.1x0.5 rev=two-way conf=opinion flags=legal id=transport-headers` `return: likelihood 1 in 3 per rendered case that delivery or notice is actually at issue, about 2 renders a year, so about once in two years, estimated, nothing was counted, there is no run counter and C:\Code_data\email-evidence-tools holds no render output; impact 0.5 to 6 h of Jon's time on the one occurrence, going back to the source archive to pull the Received chain and authentication results for the messages at issue by hand, re-hashing what he quotes, and reissuing an exhibit that was already served; evidence render_mbox_to_markdown.py lines 399 to 421 write the addressing, threading and integrity headers and no transport headers, its CSV header at line 285 carries ten columns and none of them is a transport header, its manifest at lines 338 to 358 carries file hashes and counts only, and git log over that file since the repository opened shows no Received handling`
  - `worker: sonnet 1.5/3/6 h`
  - Goal. A rendered exhibit carries the delivery evidence that was already in the source archive, so a delivery or notice argument is cited from the exhibit rather than reconstructed from the mbox after the fact.
  - Read before changing anything. `THEORY.md` in full. In `render_mbox_to_markdown.py`: `header_str` at line 177, the record built at lines 264 to 272 (it keeps the parsed message under `rec["msg"]`, so no second parse pass is needed), `write_message` at line 366, the yaml block it writes at lines 400 to 420, the CSV header at line 284, the CSV row write at line 447, the manifest at lines 338 to 358. Then `tests/test_render_mbox_to_markdown.py` and `tests/mbox_builder.py`.
  - Current behaviour. `write_message` writes a yaml block holding `n`, `date_utc`, `date_header`, `from`, `to`, `cc`, `bcc`, `reply_to`, `sender`, `delivered_to`, `subject`, `message_id`, `in_reply_to`, `references`, `mime_version`, `source_offset`, `raw_size_bytes`, `raw_sha256`, `body_source`. The CSV header is `n, date_utc, date_raw, from, to, cc, subject, message_id, raw_sha256, attachment_count`. The manifest holds source and output hashes, message counts, attachment count and date range. A message whose `Received` chain shows when and by which relay it was delivered leaves no trace of that fact in any of the three outputs.
  - Wanted behaviour, markdown. After `body_source` in the same yaml block, and only when the message actually has the header, append these keys with exactly these names, in this order: `return_path`, `auth_results`, `received_count`, then `received_1` through `received_<n>`, then `dkim_signature_1` through `dkim_signature_<m>`. `received_N` is numbered in the order `msg.get_all("Received", [])` returns them, which is the order they appear in the file, newest relay first because each relay prepends its own. Say that ordering in the README so a reader of the exhibit is not left to guess. Each value is the header verbatim with CR and LF folded to single spaces, exactly as `header_str` already does; do not parse, normalise, reorder or shorten any of them, and do not truncate the `b=` tag of a DKIM signature, because a truncated signature is not citable. A message with no transport headers gets none of these keys, not blank ones.
  - Wanted behaviour, worked example. Input message carrying, in this file order, `Received: from mx2.example.net (mx2.example.net [203.0.113.9]) by mail.example.org with ESMTPS id abc123; Mon, 05 Jan 2026 09:00:04 +0000`, then `Received: from sender.example.com (sender.example.com [198.51.100.7]) by mx2.example.net with ESMTP id def456; Mon, 05 Jan 2026 09:00:01 +0000`, then `Return-Path: <a@example.com>`, then `Authentication-Results: mx2.example.net; spf=pass smtp.mailfrom=example.com; dkim=pass header.d=example.com`, then one `DKIM-Signature: v=1; a=rsa-sha256; d=example.com; s=sel; bh=AAAA; b=BBBB`. Output yaml gains `return_path:    <a@example.com>`, `auth_results:   mx2.example.net; spf=pass smtp.mailfrom=example.com; dkim=pass header.d=example.com`, `received_count: 2`, `received_1:     from mx2.example.net (mx2.example.net [203.0.113.9]) by mail.example.org with ESMTPS id abc123; Mon, 05 Jan 2026 09:00:04 +0000`, `received_2:     from sender.example.com (sender.example.com [198.51.100.7]) by mx2.example.net with ESMTP id def456; Mon, 05 Jan 2026 09:00:01 +0000`, `dkim_signature_1: v=1; a=rsa-sha256; d=example.com; s=sel; bh=AAAA; b=BBBB`. Key padding follows the block's existing style, value column aligned where it fits and allowed to run long where it does not.
  - Wanted behaviour, CSV. Append exactly three columns to the end of the existing header, never inserted among the current ten, because position is how any existing consumer reads that file: `received_count`, `return_path`, `auth_results`. `received_count` is an integer and is `0` when there are none. `return_path` and `auth_results` are the verbatim folded header values and are empty strings when absent. DKIM signatures do not go in the CSV; they are too long for a tabular index and the markdown carries them.
  - Wanted behaviour, manifest. Add exactly three integer keys after `attachments_total`: `messages_with_received`, `messages_with_auth_results`, `messages_with_dkim_signature`. Each counts messages having at least one of that header. This is what lets the manifest attest transport coverage across the whole exhibit rather than message by message.
  - The test that proves it. Add `transport_message(...)` to `tests/mbox_builder.py`, built the same way as `plain_message`, taking the two `Received` lines, the `Return-Path`, the `Authentication-Results` and the `DKIM-Signature` above as defaults. Add `test_transport_header_chain_is_rendered_and_counted(tmp_path)` to `tests/test_render_mbox_to_markdown.py`, rendering one `transport_message` and one `plain_message` in one mbox, and asserting all of: `received_count: 2` appears in the markdown; `received_1` holds the `mx2.example.net` line and `received_2` holds the `sender.example.com` line, in that order and not swapped; `return_path`, `auth_results` and `dkim_signature_1` each appear with their full verbatim value including the `b=BBBB` tag; the transport message's CSV row ends with `2`, the return path and the authentication results; the plain message's CSV row ends with `0` and two empty cells; the plain message's yaml block contains none of the strings `received_`, `return_path`, `auth_results` or `dkim_signature`; and the manifest reads `messages_with_received: 1`, `messages_with_auth_results: 1`, `messages_with_dkim_signature: 1`. Prove the test is real before committing: stash only the change to `render_mbox_to_markdown.py`, confirm the new test fails, restore it, confirm it passes.
  - Out of scope. No parsing, validating, scoring or interpreting of SPF, DKIM or DMARC results; the exhibit reproduces what the headers say and takes no position on whether they are true. No cryptographic verification of a signature. No change to `scan_mbox_for_evidence.py`, `extract_messages_by_address.py`, `strip_attachments_from_mbox.py`, `clean_evidence_csv.py`, `run_evidence_pipeline.py` or `label_matching_emails_via_imap.py`. No reordering or renaming of the ten existing CSV columns. No change to how hashes are computed. README changes are limited to documenting the new yaml keys, the three new CSV columns, the three new manifest keys and the `Received` ordering.
  - Definition of done. The full suite is green from `C:\Code\venvs\email-evidence-tools\Scripts\python.exe -m pytest`, with output written to `C:\Code_data\email-evidence-tools\suite_2026-09-06_G1.log` and that log read. The new test has been shown to fail without the source change. `git diff --stat master` touches only `render_mbox_to_markdown.py`, `tests/test_render_mbox_to_markdown.py`, `tests/mbox_builder.py` and `README.md`. One commit on the branch, message describing what changed. Nothing merged, nothing pushed.
  - Rollback. Nothing landed on `master`, so recovery is to delete the branch and the worktree: `git worktree remove C:\Code\worktrees\eet-transport-headers` then `git branch -D feature/transport-headers-in-exhibit`.

### Group 2, THEORY.md re-checked against the tree

Branch `docs/theory-recheck-against-tree` off `master`. Worktree
`C:\Code\worktrees\eet-theory-recheck`. Run log
`C:\Code_data\email-evidence-tools\RUN_2026-09-06_G2.md`.

- **theory-subject-stale** `THEORY.md` still tells every session the scanner reads bodies only and misses a subject-only lure, which stopped being true on 2026-08-12; re-check every assertion in that file against the code and correct the ones the tree no longer supports. `score: kind=docs gain=0.5/2/4 p=0.15 freq=20 hours=0.1/0.25/0.5 ai=1 risk=0.05x0.25 rev=two-way conf=assessed flags=legal id=theory-subject-stale` `return: likelihood 15 in 100 per session that touches the scanner that the session leans on the stale line instead of reading the code, and about 20 such sessions a year, so about 3 a year, the 20 is measured from 8 distinct commit days touching scan_mbox_for_evidence.py between 2026-04-13 and 2026-09-06 which is 8 in 146 days, the 15 in 100 is estimated and nothing was counted; impact 0.5 to 4 h of Jon's time on the one occurrence, either rebuilding subject scanning that already shipped in 95ce9da or telling a case that a subject-only lure went undetected when the scan already covered it, then re-running the scan and reissuing the finding; evidence THEORY.md line 31 read against scan_mbox_for_evidence.py lines 279 to 307 which scan the subject as its own source and write a location column naming which source each hit came from, commit 95ce9da dated 2026-08-12 that shipped it, and git log --date=short -- scan_mbox_for_evidence.py for the 8 commit days`
  - `worker: haiku 0.5/1/2 h`
  - Goal. `THEORY.md` stops asserting limitations the tool does not have, so a session that reads it before changing anything is reading the current system rather than the August one.
  - Current behaviour. `THEORY.md` line 31, under Known soft spots, reads "The scanner reads bodies only. A lure that lives entirely in the `Subject` header produces no hit." `scan_mbox_for_evidence.py` lines 303 to 307 scan the subject as its own source, line 280 gives every row a `location` column naming which source produced the hit, and lines 220 to 222 record that a subject is quoted whole rather than split into sentences. Commit 95ce9da, 2026-08-12, shipped all of it.
  - Wanted behaviour. That bullet is replaced with one the code supports, and every other assertion in the file gets the same treatment: kept with the file and line that still proves it, or corrected. Replacement text for the stale bullet, use this wording unless the code says otherwise: "The scanner reads the message body and the `Subject` header, and each row's `location` column names which one the hit came from. It reads no other header, so a lure that lives in a display name, a `Reply-To` or a `Received` line produces no hit."
  - The check that proves it. There is no unit test for a document, so the proof is written down. Produce `C:\Code_data\email-evidence-tools\theory_recheck_2026-09-06.md` with one row per assertion in `THEORY.md`: the assertion as written, the file and line number that confirms or refutes it, and the verdict, one of confirmed, corrected, or removed. An assertion with no citation is not confirmed, it is a finding. Every assertion in the file must appear in that table, including the ones that turn out to be fine.
  - Out of scope. No code change of any kind, in any file. If the re-check turns up a bullet that describes a real defect rather than a stale claim, add it to the `## Scored index` in `FUTURE_FEATURES.md` with a full `score:` and `return:` block and leave the defect alone. Do not touch `README.md`, `CHANGELOG.md` or `WORK_BOARD.md`.
  - Definition of done. Every assertion in `THEORY.md` has a tree citation in the re-check file. `THEORY.md` is still under 60 lines, which is the playbook's limit for the file being read at all. `git diff --stat master` touches `THEORY.md` and, only if the re-check found a real defect, `FUTURE_FEATURES.md`, and nothing else. The full suite is run once anyway and logged to `C:\Code_data\email-evidence-tools\suite_2026-09-06_G2.log`, to prove the branch is green before Jon merges, even though no code moved. One commit on the branch. Nothing merged, nothing pushed.
  - Rollback. `git checkout master -- THEORY.md`, or delete the branch and worktree as in Group 1.

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
