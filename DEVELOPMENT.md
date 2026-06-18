# Development Guide

This document covers the internal architecture and maintenance commands for the OCA
Claim Submission Agent. For normal use, see [README.md](README.md).

## Command Architecture

### `/uhc-bulk-import`

Wraps the deterministic UHC EOB parser in [src/eob_parser.py](src/eob_parser.py):

```bash
uv --directory "$(git rev-parse --show-toplevel)" run python src/eob_parser.py <file-or-dir> [--dry-run]
```

It verifies totals, creates UHC claims, and extracts a receipt PDF for each claim.

### `/new-claim`

A skill-driven workflow over [src/storage/cli.py](src/storage/cli.py). It creates a
claim, stores its receipt, extracts metadata, and persists the parsed fields.

### `/parse-claim`

A maintenance workflow over [src/storage/cli.py](src/storage/cli.py). It reloads an
existing claim, reads its stored receipts, and repairs extracted metadata.

### `/classify-claim`

Reads receipt PDFs, proposes a claim type using rules and heuristics, and persists
the selected type through the storage CLI.

### `/submit-claim`

For direct receipts, this workflow creates claims through the storage CLI. For
existing claims, it loads them from storage. It then uses browser automation to
complete the OCA portal and marks successful claims as submitted.

## Claim Model

Each claim contains:

- `source`: `direct` or `uhc`
- `status`: `pending` or `submitted`
- `type`
- `service_date`
- `amount`
- `provider`
- `claimant`
- `source_claim_number` for UHC imports
- receipt files under `data/claims/<claim_id>/receipts/`

A claim is ready for submission when:

- its status is `pending`
- its type, service date, and amount are set
- it has at least one receipt

Claims are stored in `data/claims/<claim_id>/claim.json`.

## Storage CLI

Always anchor CLI calls to the repository root:

```bash
uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli list
uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli list --ready
uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli list --source uhc
uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli get <claim_id>
uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli update <claim_id> --type medical --provider "..."
uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli set-status <claim_id> submitted
uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli migrate --dry-run
```

The `--directory` argument is important because some browser-automation steps may
change the current working directory.

## Configuration and Storage

Private claimant names live in `config/claimants.toml`. Copy
[config/claimants.example.toml](config/claimants.example.toml) to create it.

The repository ignores both `config/claimants.toml` and `data/` because they may
contain sensitive personal and health information.

## Technical Notes

- The EOB parser uses PyMuPDF.
- UHC imports use `source_claim_number` to prevent duplicates.
- OCA submission is browser-automation driven; the user handles login.
- Legacy claim files remain readable.
- Run `python -m src.storage.cli migrate` through `uv --directory` to intentionally
  rewrite legacy files into the current schema.

## Tests

Run the test suite from the repository root:

```bash
uv run --with pytest python -m pytest
```
