# Audit & reproducibility

Every export writes an audit record so any result can be rebuilt byte-for-byte.

```
reports/exports/nightly/<stem>_audit.json   full record
reports/exports/nightly/<stem>_audit.md     readable version (goes in the case study)
reports/exports/audit_log.jsonl             one line per export, newest last
```

Browse it:

```bash
make audit                        # list recent exports
python -m src.reporting.audit --show <run_id>
```

## What is captured

- **run** — `run_id`, timestamps, host, user, full `argv`, git commit.
- **parameters** — post/baseline windows, `alpha`, week/baseline/lag settings,
  borough + complaint-category filters, the alert policy in force, output formats.
- **environment** — python and package versions, platform, and a sha256 of
  `config/config.yaml` (so a silent threshold edit is visible).
- **datasets** — for each input frame: rows, columns, date span, distinct boroughs /
  categories, and a content fingerprint.
- **outputs** — every artefact with size and sha256.
- **replay_command** — the exact CLI that reproduces the export.

## Fingerprints

A dataset fingerprint is `sha256` over the canonical CSV of the frame with **sorted
columns and sorted rows**, so it is invariant to ordering and to how the frame was
loaded, but changes if any single value changes. `inputs_fingerprint` folds the
per-dataset digests together: two exports with the same `inputs_fingerprint` and the
same `parameters` must produce identical numbers.

## Reproducing a past export

```bash
python -m src.reporting.audit --show 4f2ab91c0d7e | sed -n '/```bash/,/```/p'
# then run the printed command, e.g.
python -m src.reporting.cohort_export --format all \
    --post-start 2024-06-01 --post-end 2024-06-07 \
    --baseline-start 2024-05-04 --baseline-end 2024-05-31 \
    --alpha 0.01 --borough "BROOKLYN"
```

Compare the new record's `inputs_fingerprint` with the old one: if they match and the
numbers differ, the difference is code, not data.
