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
- Work in the worktree the item names, never in `<workspace_root>\projects\email-evidence-tools` itself.
  Another session may hold that tree.
- Workers never commit. The group orchestrator reviews each result against the item's definition of
  done and commits what meets it. Workers kill only processes they started, by PID.
- Every commit is authored by Jon Bowker alone, the message says what changed, and it carries no AI
  attribution of any kind (CORE-05, CORE-06).
- Generated output, logs and reports go to `<data_root>\email-evidence-tools\`, never into the
  repository (CORE-01).
- Tests run from `<workspace_root>\venvs\email-evidence-tools\Scripts\python.exe`, output redirected to a log
  file under the data root, and the log is what gets read.
- Failure budget: if the same test fails twice after a fix attempt, stop. Write the failing output to
  the data root, leave the branch as it stands, and record the stop on this board. Do not widen the
  change to make a test pass.
- Overrun: if a group passes its `worker:` high estimate in wall clock, stop at the last green commit
  and record what is left in its run log. Do not carry on.

## Pending

Nothing pending.

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
