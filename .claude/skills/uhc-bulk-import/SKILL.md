---
description: Import UHC Explanation-of-Benefits PDFs and create one OCA-submittable claim per out-of-pocket line item. This is the UHC intake path. (project)
---

# uhc-bulk-import

Run the deterministic UHC parser at `src/eob_parser.py`. Each imported out-of-pocket line item becomes a claim with:

- `source=uhc`
- parsed `service_date`, `amount`, and `provider`
- `type=null`
- `source_claim_number=<UHC claim number>`

## Usage

```text
/uhc-bulk-import <path> [--dry-run]
```

## Process

1. Default to `--dry-run` first unless the user explicitly asked to skip preview
2. Run:

```bash
uv --directory "$(git rev-parse --show-toplevel)" run python src/eob_parser.py "<path>" [--dry-run]
```

3. Relay:
   - verification success or failure
   - duplicate UHC claim numbers skipped
   - created claim ids
4. Tell the user to run:

```text
/classify-claim --all
```

before `/submit-claim --all` to submit the ready claim queue in one batch,
including the imported claims you just classified

## Notes

- This is an import/preprocessing step, not a submission path
- Re-running the same EOB should not create duplicates because imports dedupe on `source_claim_number`
- Use `/submit-claim <receipt_path>...` for direct single-receipt claims, or
  `/new-claim` if the user wants to create without submitting yet
