---
description: Submit a prepared reimbursement claim to the OCA WealthCare portal. This is the only submission path. (project)
---

# submit-claim

Submit claim(s) to OCA. By default this command accepts one or more direct receipt
files and goes all the way from claim creation through submission. It can also submit
an existing prepared claim via `--id`, or every ready pending claim via `--all`.

## Usage

```text
/submit-claim <receipt_path>... [--type <claim_type>] [--claimant "Name"]
/submit-claim --id <claim_id> [--claimant "Name"]
/submit-claim --all
```

Resolve any provided claimant against `config/claimants.toml`. Unique first names are
valid when they map to a single configured full name.

Interpretation rules:

- `--id <claim_id>` means "submit this already-created claim"
- `--all` means "submit every ready, pending claim"
- otherwise, every positional argument is a receipt file path and should create its own
  `source=direct` claim before submission
- multiple receipt paths mean multiple claims; do not combine them into one claim

`--type` is only valid on the receipt-file path, not with `--id` or `--all`.
If `--type` is provided on the receipt-file path, treat it as explicit user intent and
use it; only invoke classification when `type` is still null.

## Validation

For `--id`, load the claim with:

```bash
uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli get <claim_id>
```

For `--all`, load ready pending claims with:

```bash
uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli list --ready --json
```

If the result is empty, tell the user there are no ready claims to submit.
Before opening the portal, tell the user which claim ids you are about to submit, then
continue without waiting for an extra confirmation step.

For receipt-path input:

1. Verify each receipt file exists
2. For each receipt, create a direct claim:
   ```bash
   uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli new --source direct [--type <claim_type>] [--claimant "<Name>"]
   ```
3. Attach the receipt:
   ```bash
   uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli add-receipt <claim_id> <receipt_path>
   ```
4. Read the receipt directly and extract `service_date`, `amount`, and `provider`
5. Persist only the fields you could confidently extract:
   ```bash
   uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli update <claim_id> \
     [--service-date <YYYY-MM-DD>] \
     [--amount <amount>] \
     [--provider "<provider_name>"]
   ```
6. Re-load the claim:
   ```bash
   uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli get <claim_id>
   ```

Before submitting any claim:

- if `status` is `submitted`, tell the user it was already submitted
- if `type` is null, load `.claude/skills/classify-claim/SKILL.md` and follow that
  workflow for just this claim before continuing
- if classification remains ambiguous after applying the classify-claim rules and
  heuristics, ask the user to clarify the type before submitting
- if `service_date` or `amount` is missing, tell the user the claim still needs metadata
- if `receipts` is empty, tell the user to attach a receipt first

Determine the claimant before opening the form. Claimant normalization always happens at storage-write time (via `cli new --claimant` or `cli update --claimant`), never at submit time — this skill just reads the stored full name and selects it in the OCA dropdown.

- If the user passed `--claimant "<Name>"` on this `/submit-claim` invocation, persist and normalize it first, then re-load the claim:
  ```bash
  uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli update <claim_id> --claimant "<Name>"
  ```
- This overrides any previously stored claimant on the claim in both receipt-input and
  existing-claim modes (`--id` and each claim reached through `--all`).
- Otherwise, if the stored claim already has a `claimant`, use it directly.
- Otherwise, ask the user which configured claimant to use for that claim, then
  persist via the same `cli update --claimant` command before continuing. In `--all`
  mode this fallback is evaluated per claim, so most batches should proceed without
  interruption but a claim with a missing claimant may still need a one-off prompt.

## Process

1. Build the list of target claim ids:
   - `--id`: one existing claim
   - `--all`: every ready pending claim returned by `list --ready --json`
   - receipt paths: one newly created claim per receipt
2. Open or reuse the OCA portal tab once for the whole batch
3. If the user is not logged in, ask them to log in
4. For each target claim, in order:
   - navigate to the reimbursement request form
   - fill ONLY these four fields on the claim-detail page — leave every other field blank, including Service End Date, Provider Name, Account Number, and Comments:
     - **Service Start Date**
     - **Claimant**
     - **Account Type** (mapped from claim `type` per the table below)
     - **Claim Amount**

     Pitfalls:
     - **Date picker**: the per-day buttons aren't clickable until you click the calendar-icon button to open the popup. After picking Service Start Date, OCA auto-mirrors that date into Service End Date and pops the end-date calendar — leave the mirrored value as-is and dismiss the popup. Don't try to clear the end date; the form accepts the mirror and there's no clean way to leave it blank.
     - **Numeric fields (Claim Amount)**: use `mcp__claude-in-chrome__form_input` with a numeric value. Do NOT click + ctrl+a + type — the selection won't replace and you'll get garbage like `21760.00`.
     - **Refs invalidate at each step**: re-`find` after every NEXT click instead of carrying refs across pages.
   - upload receipts (do NOT use `mcp__claude-in-chrome__file_upload` — it returns `{"code":-32000,"message":"Not allowed"}` on this site). Instead:
     a. Kill any existing server, then start a fresh CORS-enabled HTTP server in the receipt
        directory:
        ```bash
        lsof -ti:7777 | xargs kill 2>/dev/null
        cd <claim_receipts_dir> && python3 -c "
        import http.server
        class H(http.server.SimpleHTTPRequestHandler):
            def end_headers(self):
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                self.send_header('Pragma', 'no-cache')
                self.send_header('Expires', '0')
                super().end_headers()
            def log_message(self, *a): pass
        http.server.HTTPServer(('127.0.0.1', 7777), H).serve_forever()
        " &
        ```
        The CORS header is required — the OCA page is HTTPS and will reject a plain
        `http.server` fetch. Use `127.0.0.1`, not `localhost`. Start a fresh server
        per claim; do not reuse a previous claim's server for a different receipt
        directory.
     b. In the OCA tab, inject each receipt with JS. Use a cache-busting query
        parameter (`?t=<timestamp>`) so Chrome never serves a stale cached response
        from a previous claim's server — all claims share the same filename
        `receipt_001.pdf` on the same port, so without busting the cache Chrome
        will return the first claim's file for every subsequent claim:
        ```javascript
        const r = await fetch(`http://127.0.0.1:7777/<filename>?t=${Date.now()}`);
        const f = new File([await r.blob()], '<filename>', {type:'application/pdf'});
        const input = document.getElementById('popup__file_el');
        const dt = new DataTransfer(); dt.items.add(f);
        input.files = dt.files;
        input.dispatchEvent(new Event('change', {bubbles:true}));
        ```
   - submit the claim without asking for an extra confirmation step
   - mark the claim submitted:

```bash
uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli set-status <claim_id> submitted
```

   - after each claim attempt, tear down the temporary receipt server before moving to
     the next claim:
     ```bash
     lsof -ti:7777 | xargs kill 2>/dev/null
     ```

If one claim in a multi-receipt batch is missing metadata or needs type clarification,
pause on that claim, resolve it with the user, and then continue. Do not silently skip
or auto-guess unresolved claims.

If one claim fails during portal submission, do not mark it submitted. Report the
failure, re-orient the browser to a clean reimbursement-request state, and continue
with the remaining claims unless the user asks to stop the batch.

## Account Type Mapping

- `prescriptions` -> Prescriptions
- `dental` -> Dental Treatments
- `vision` -> Vision Treatments
- `medical` -> Medical CoPays, OON Deductibles
- `mental-health` -> Mental Health
- `equipment` -> Medical Equipment
- `wellness` -> Wellness Treatments

## Notes

- The user handles login manually
- Do not update status if the submission fails
- This command applies to both `source=direct` and `source=uhc`
- For direct claims, `/submit-claim` is the preferred happy path; `/new-claim` remains
  available when the user wants to create without submitting yet
