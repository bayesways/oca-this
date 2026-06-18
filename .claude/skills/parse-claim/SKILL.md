---
description: Re-parse receipt metadata for an existing claim when the original extraction was incomplete or needs repair. (project)
---

# parse-claim

Re-parse an existing claim's receipt metadata.

This is now a maintenance command, not part of the normal happy path. `/new-claim` already parses direct receipts during creation.

## Usage

```text
/parse-claim <claim_id>
/parse-claim --unparsed
```

## When To Use It

- the original `new-claim` parse was incomplete
- a claim's receipt changed
- an imported claim needs metadata repaired

## Process

1. Load the target claim with `uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli get <claim_id>` or `list --unparsed --json`
2. Read the receipt files
3. Extract `service_date`, `amount`, and `provider`
4. Persist the fields with:

```bash
uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli update <claim_id> \
  [--service-date <YYYY-MM-DD>] \
  [--amount <amount>] \
  [--provider "<provider_name>"]
```

Leave uncertain fields untouched rather than guessing.

**Note on names in receipts**: Names appearing on receipts (ship-to, billed-to, patient,
account holder, etc.) reflect the parent or account owner, not necessarily the claimant. Do not question the claimant name based on receipts.