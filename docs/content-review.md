# Content Review

> **AI reviewer - read before editing.** Keep this document public-safe. Do not add exact evidence paths, personal names, party names, complaint numbers, email addresses, or secrets.

Reviewed on 2026-05-07 while reframing the repository as `email-evidence-tools`.

## Decision

Keep this repo as a standalone email evidence utility repo. The scripts are generally useful for mbox processing, attachment reduction, CSV cleanup, and IMAP labeling, but the previous repository name, headers, defaults, and labeler configuration were too matter-specific for a reusable or public-safe tool.

## Updated

| Area                       | Decision                            | Reason                                                                 |
| -------------------------- | ----------------------------------- | ---------------------------------------------------------------------- |
| Repository name            | Rename to `email-evidence-tools`    | Describes the reusable function without case-specific names.           |
| Script headers             | Neutralize                          | Removes matter-specific metadata from source files.                    |
| Evidence paths             | Move to docs                        | Avoids hardcoded personal paths in executable code.                    |
| Exact local evidence paths | Keep in gitignored local note       | Preserves operational breadcrumbs without publishing private paths.    |
| IMAP labeler               | Make domains and label configurable | Removes hardcoded matter-specific domains and label names.             |
| Generated outputs          | Ignore                              | Prevents mbox, CSV, checkpoint, and inventory files from entering git. |

## Data Safety Rules

- Do not commit mbox files, generated evidence CSVs, attachment inventories, checkpoints, `.env` files, or local path notes.
- Keep exact evidence locations only in `docs\evidence-location.local.md`.
- Configure scripts with command-line arguments or environment variables.
- Treat this repo as tooling only; evidence data belongs outside the repo.

