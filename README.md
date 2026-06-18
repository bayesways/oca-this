# OCA Claim Submission Agent

This repo manages reimbursement claims that ultimately get submitted to the OCA WealthCare portal.

There is one submission path:

- `/submit-claim <receipt-file>...` creates direct claim(s) from receipt file(s) and
  submits them to OCA
- `/submit-claim --id <claim_id>` submits an already-prepared claim to OCA
- `/submit-claim --all` submits every ready pending claim to OCA

There are two ways to create those claims:

- `direct` claims: usually created inline by `/submit-claim <receipt-file>...`, or
  manually with `/new-claim`
- `uhc` claims: created from a UHC EOB batch with `/uhc-bulk-import`

## Flow A: Direct Claim

### Step 1: Create and Submit the Claim

```bash
/submit-claim <receipt-file>... [--type <type>] [--claimant "Name"]
```

This command:

- creates one claim per receipt file with `source=direct`
- stores the receipt
- extracts `service_date`, `amount`, and `provider` from the receipt
- resolves any provided claimant against `config/claimants.toml`
- uses the provided `type`, or classifies the claim before submission if `type` is
  omitted
- treats a provided `--type` as explicit user intent
- asks the user if classification is still unclear
- submits each ready claim to OCA in sequence
- continues past individual submission failures unless you tell it to stop; failed
  claims remain pending

If parsing is partial, the claim is still created so it can be fixed manually before
submission.

### Optional: Create Without Submitting

```bash
/new-claim <receipt-file> [--type <type>] [--claimant "Name"]
```

Use this when you want to create a direct claim first and submit it later.

### Alternative: Submit an Existing Direct Claim

```bash
/submit-claim --id <claim_id> [--claimant "Name"]
```

`--claimant` is resolved against `config/claimants.toml`. Unique first names are
accepted and expanded to the configured full name. If provided, it overrides the
stored claimant on that claim before submission.

## Flow B: UHC Bulk Import

### Step 1: Import UHC EOBs

```bash
/uhc-bulk-import <file-or-dir> [--dry-run]
```

Or run the parser directly:

```bash
uv --directory "$(git rev-parse --show-toplevel)" run python src/eob_parser.py <file-or-dir> [--dry-run]
```

This command:

- reads a single UHC EOB PDF or a directory of PDFs
- verifies that per-claim out-of-pocket totals match the front-page total
- creates one claim per out-of-pocket line item with `source=uhc`
- extracts a sub-PDF receipt for each imported claim
- detects the claimant from the UHC member page using the configured claimant list
- sets `type=null`
- stores the UHC claim number in `source_claim_number` for deduplication

### Step 2: Classify Imported Claims

```bash
/classify-claim <claim_id>
/classify-claim --all
```

### Step 3: Submit to OCA

```bash
/submit-claim --all
```

## What Runs Under Each Command

- `/uhc-bulk-import`
  Wraps the native parser script:
  `uv --directory "$(git rev-parse --show-toplevel)" run python src/eob_parser.py <file-or-dir> [--dry-run]`
  in [src/eob_parser.py](src/eob_parser.py). This is the deterministic UHC EOB importer that verifies totals, creates `source=uhc` claims, and extracts per-claim receipt PDFs.

- `/new-claim`
  This is a skill-driven workflow, not a single Python script. Under the hood it calls the storage CLI in [src/storage/cli.py](src/storage/cli.py), mainly `new`, `add-receipt`, and `update`, then reads the receipt and persists any parsed metadata.

- `/parse-claim`
  This is also a skill workflow over [src/storage/cli.py](src/storage/cli.py). It loads an existing claim, re-reads its stored receipt files, re-extracts metadata, and writes repairs back through `update`.

- `/classify-claim`
  This is a skill workflow rather than a native Python command. It reads receipt PDFs, proposes a claim `type` using rules and heuristics, then persists the chosen type via `uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli update <claim_id> --type <type>`.

- `/submit-claim`
  This is a mixed workflow rather than one Python entrypoint. For direct receipts it first creates claims via [src/storage/cli.py](src/storage/cli.py); for existing claims it loads them from storage; then it uses browser automation to fill the OCA portal and finally marks success with `uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli set-status <claim_id> submitted`.

## Claim Model

Each claim now has:

- `source`: `direct` | `uhc`
- `status`: `pending` | `submitted`
- `type`
- `service_date`
- `amount`
- `provider`
- `claimant`
- `source_claim_number` for UHC-imported claims
- receipt files under `data/claims/<claim_id>/receipts/`

A claim is ready for submission when:

- `status=pending`
- `type` is set
- `service_date` and `amount` are populated
- at least one receipt exists

## Storage CLI

Claims are stored as files under `data/`.

Configured claimants live in a local-only `config/claimants.toml`, which is gitignored.
Use [config/claimants.example.toml](config/claimants.example.toml)
as the template for your private claimant list.

Useful commands:

```bash
uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli list
uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli list --ready
uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli list --source uhc
uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli get <claim_id>
uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli update <claim_id> --type medical --provider "..."
uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli set-status <claim_id> submitted
uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli migrate --dry-run
```

## Technical Notes

- Claims are stored in `data/claims/<claim_id>/claim.json`
- The EOB parser uses PyMuPDF and creates imported claims deterministically
- Duplicate UHC imports are prevented using `source_claim_number`
- OCA submission is browser-automation driven; the user still handles login
- Legacy claim files remain readable, and `uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli migrate` rewrites them intentionally into the new schema
