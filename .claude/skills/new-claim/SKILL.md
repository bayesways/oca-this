---
description: Create a direct OCA claim from a single receipt, store the receipt, and parse service date, amount, and provider immediately. (project)
---

# new-claim

Create a direct OCA claim from a single receipt and parse it immediately, without
submitting it yet.

## Usage

```text
/new-claim <receipt_path> [--type <claim_type>] [--claimant "<Name>"]
```

Prefer `/submit-claim <receipt_path>...` for the normal direct-claim happy path. Use
`/new-claim` when the user explicitly wants to create or inspect a claim before
submission.

The user may also write claimant inline ("for Alex", "Alex's claim") — resolve the
name against `config/claimants.toml` and pass the configured full name as
`--claimant`. Unique first names are valid when they map to a single configured full
name.

## Arguments

- `receipt_path` (required): Path to the receipt file
- `--type` (optional): Claim type. If omitted, the claim is created with `type=null`
- `--claimant` (optional): Claimant name from `config/claimants.toml`. If omitted, the
  claim is created with `claimant=null`

## What This Skill Does

1. Creates a claim with `source=direct`
2. Stores the receipt in the claim folder
3. Reads the receipt and extracts:
   - service date
   - amount
   - provider
4. Saves any extracted metadata back to the claim
5. Leaves type as provided, or `null`; classification can happen later via
   `/classify-claim`, or inline when `/submit-claim --id <claim_id>` is run

If parsing is partial, the claim should still be created and the user should be told what remains missing.

## Implementation Steps

### Step 1: Validate the Receipt File

Verify the file exists.

### Step 2: Create the Claim

```bash
uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli new --source direct [--type <claim_type>] [--claimant "<Name>"]
```

### Step 3: Attach the Receipt

```bash
uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli add-receipt <claim_id> <receipt_path>
```

### Step 4: Parse the Receipt

Read the receipt file directly and extract:

- `service_date`
- `amount`
- `provider`

If the receipt is ambiguous, make a best effort and leave any uncertain fields empty.

**Note on names in receipts**: Names appearing on receipts (ship-to, billed-to, patient,
account holder, etc.) reflect the parent or account owner, not necessarily the claimant. Do not question the claimant name based on receipts.

### Step 5: Persist Parsed Fields

Update only the fields you could confidently extract:

```bash
uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli update <claim_id> \
  [--service-date <YYYY-MM-DD>] \
  [--amount <amount>] \
  [--provider "<provider_name>"]
```

### Step 6: Report Results

Show:

- claim id
- stored receipt path
- parsed fields
- any missing fields
- whether type still needs `/classify-claim`
- remind the user that `/submit-claim --id <claim_id>` can submit this claim later
