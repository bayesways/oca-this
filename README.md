# OCA Claim Submission Agent

This project helps you submit healthcare reimbursement claims to the OCA
WealthCare portal. Give Claude a receipt or a folder of UHC Explanation of Benefits
(EOB) PDFs, and it will prepare the claims and enter them into OCA.

## Before You Begin

You will need:

- access to your OCA WealthCare account
- [Claude Code](https://code.claude.com/docs) with its
  [Chrome integration](https://code.claude.com/docs/en/chrome) enabled
- [uv](https://docs.astral.sh/uv/getting-started/installation/) installed
- your receipt or UHC EOB files saved on your computer

Claude fills out the OCA forms, but you handle the OCA login yourself.

> **Privacy:** Receipts, EOBs, claimant names, and saved claims may contain personal
> health information. Keep this repository private and do not commit or share the
> `data/` directory or `config/claimants.toml`.

## One-Time Setup

1. Download or clone this repository and open its folder in Claude Code.
2. Open a terminal in the project folder and install its dependencies:

   ```bash
   uv sync
   ```

3. Create your private claimant list:

   ```bash
   cp config/claimants.example.toml config/claimants.toml
   ```

4. Open `config/claimants.toml` and replace the example names with the names shown
   in your OCA account:

   ```toml
   [claimants]
   allowed = [
     "Alex Smith",
     "Blair Smith",
   ]
   ```

5. Start Claude Code with browser access:

   ```bash
   claude --chrome
   ```

   If Claude Code is already open, enter `/chrome` and connect it to Chrome or
   Microsoft Edge.

If you would rather not use the terminal yourself, ask Claude:

```text
Help me complete the one-time setup for this project.
```

## Submit a Receipt

In Claude Code, enter:

```text
/submit-claim "/Users/alex/Downloads/dentist-receipt.pdf" --claimant "Alex"
```

Replace the example path with the location of your receipt. Keep quotation marks
around paths that contain spaces.

Claude will:

1. read the receipt
2. identify the date, amount, provider, and expense type
3. ask you about anything unclear
4. open the OCA portal and wait while you log in
5. complete and submit the claim
6. tell you whether submission succeeded

You can submit several receipts at once:

```text
/submit-claim "/Users/alex/Downloads/receipt-1.pdf" "/Users/alex/Downloads/receipt-2.pdf" --claimant "Alex"
```

Each receipt becomes a separate claim.

### Save a Claim for Later

To prepare a claim without submitting it:

```text
/new-claim "/Users/alex/Downloads/receipt.pdf" --claimant "Alex"
```

Claude will give you a claim ID. Submit it later with:

```text
/submit-claim --id 2026-06-18_001
```

## Import UHC EOBs

If you have one or more UHC EOB PDFs, put them in a folder and run these commands in
Claude Code:

```text
/uhc-bulk-import "/Users/alex/Downloads/UHC EOBs"
/classify-claim --all
/submit-claim --all
```

The first command previews the import and creates claims from the EOBs. The second
checks each expense type with you. The third submits all claims that are ready.
Importing the same UHC claim again will not create a duplicate.

## Review or Retry Claims

- Submit a previously saved claim:

  ```text
  /submit-claim --id 2026-06-18_001
  ```

- Submit every claim that is ready:

  ```text
  /submit-claim --all
  ```

- Re-read a receipt when details were missed:

  ```text
  /parse-claim 2026-06-18_001
  ```

If a submission fails, the claim remains saved and can be retried. Claude does not
mark a claim as submitted unless the OCA submission succeeds.

## Troubleshooting

### Claude cannot find the receipt

Use the receipt's complete path and put it in quotation marks:

```text
/submit-claim "/Users/alex/My Receipts/receipt.pdf" --claimant "Alex"
```

### Claude does not recognize the claimant

Check that the person's full name appears in `config/claimants.toml`. You may use a
first name only when it identifies exactly one person in that file.

### Receipt details are missing

Claude saves a partially read claim instead of guessing. Correct the requested
details, or run `/parse-claim <claim-id>` to read its receipt again.

### The OCA portal is not opening

Enter `/chrome` in Claude Code and reconnect the browser extension. You may also
need to open the portal yourself and complete login before asking Claude to
continue.

## For Developers

Implementation details, storage commands, and the claim data model are documented
in [DEVELOPMENT.md](DEVELOPMENT.md).
