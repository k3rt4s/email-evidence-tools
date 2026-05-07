# Evidence Location Notes

> **AI reviewer - read before editing.** This tracked document must stay public-safe. Do not put personal names, party names, complaint numbers, exact local evidence paths, email addresses, or secrets here. Use `docs/evidence-location.local.md` for exact local paths; that file is intentionally gitignored.

Reviewed on 2026-05-06.

## Purpose

The evidence inputs and generated outputs may move outside this repository. The scripts should not rely on hardcoded personal paths. Use environment variables or command-line arguments for active runs, and keep exact machine-specific paths in the local-only note.

## Local-Only Companion

Exact paths for this workstation are documented in:

```text
docs\evidence-location.local.md
```

That file is excluded by `.gitignore` and should not be committed.

## Path History

| Artifact                    | Previous location pattern                                        | Current location pattern                                      | Notes                                                                     |
| --------------------------- | ---------------------------------------------------------------- | ------------------------------------------------------------- | ------------------------------------------------------------------------- |
| Source mbox archive         | Personal cloud drive under a case/evidence folder                | Same personal cloud drive evidence folder on this workstation | Confirmed present during the 2026-05-06 review.                           |
| Attachment stripping input  | Personal cloud drive working folder for exported mail text       | Same personal cloud drive working folder on this workstation  | Confirmed present during the 2026-05-06 review.                           |
| Attachment-stripped archive | Derived beside the attachment stripping input                    | Derived beside the attachment stripping input                 | Found as a compressed no-attachments output during review.                |
| Attachment inventory CSV    | Derived beside the attachment stripping input or evidence folder | Evidence folder on this workstation                           | Found during review.                                                      |
| Evidence hit CSVs           | Script working directory at time of run                          | Personal cloud drive root on this workstation                 | Found during review; future runs should set an explicit output directory. |

## Script Guidance

- Set `MBOX_FILE` before running the mbox scanner.
- Set `MBOX_INPUT_PATH` before running the attachment stripper.
- Keep output CSVs outside the repository or under a gitignored local output folder.
- Do not commit mbox files, generated CSVs, attachment inventories, checkpoints, or local evidence path notes.

