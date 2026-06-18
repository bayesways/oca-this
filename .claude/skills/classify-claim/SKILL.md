---
description: Classify the OCA claim type (medical/dental/vision/etc.) for any claim with type=null by reading the receipt PDF. Learns from user corrections. (project)
---

# Classify Claim Skill

Set the `type` field on claims that don't have one yet. This works for both direct claims and UHC-imported claims. It reads each receipt, proposes a type, and persists it after the user confirms.

**Important design property: this skill learns.** When the user corrects a classification, Claude appends a concrete rule to the "Classification rules learned" section at the bottom of this file. Subsequent runs read those rules first, so error rate drops over time.

## Command

`/classify-claim`

## Arguments

- `claim_id` (optional): Classify one specific claim by ID
- `--all` (optional): Iterate every claim with `type=null`

If neither is given, ask the user which claim(s) to classify.

## Example Usage

```
/classify-claim 2026-04-12_002
/classify-claim --all
```

## Valid Types

From `src/storage/models.py`: `prescriptions`, `dental`, `vision`, `medical`, `mental-health`, `equipment`, `wellness`.

## Process

### Step 1: Fetch Target Claims

**Single claim:**
```bash
uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli get <claim_id>
```

**Batch (`--all`):**
```bash
uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli list --json
```
Filter the result to entries where `type` is `null`.

Do NOT touch claims that already have a non-null type — if the user targets one by id, tell them it's already set and ask before overwriting.

### Step 2: For Each Target Claim, Propose a Type

For each claim:

1. **Read the receipts** listed in the claim's `receipts` array. Use the Read tool on each PDF path. Some claims will be direct receipts; others will be UHC-extracted sub-PDFs.

2. **Consult the "Classification rules learned" section at the bottom of this file FIRST.** If a rule matches the claim's provider + service text, use the rule's type.

3. **Otherwise, apply the default heuristics** (below) to pick a type. If no heuristic matches, fall back to `medical` — that's the prior for UHC EOB claims (copays, OON deductibles, radiology, labs, outpatient, ER all live under OCA's Medical CoPays account).

4. **Present to the user**: claim id, provider, amount, service date, proposed type, and a one-sentence reason citing the evidence (e.g. "`RADIOLOGY SERVICES` line item"). Ask:
   > Accept `medical`? (y / n / different type)

### Step 3: Persist or Correct

**On confirmation (`y` or silence):**
```bash
uv --directory "$(git rev-parse --show-toplevel)" run python -m src.storage.cli update <claim_id> --type <type>
```

**On correction** (user says `n` or names a different type):
1. Persist the correct type with the same CLI command.
2. **Edit this SKILL.md** using the Edit tool: append a one-line rule to the "Classification rules learned" section at the bottom, just before the closing `<!-- Append new rules above this line -->` marker. Format:
   ```
   - Provider "<provider>" with signal "<key phrase from PDF>" → <type> (noted YYYY-MM-DD)
   ```
   Keep rules short and concrete — provider name plus one specific signal. Don't record generic rules; the heuristics already cover those.

### Step 4: Summary

- Single claim: show the final claim record with its new type.
- Batch: report how many were classified, how many were corrected, and whether any new rules were added.

## Default Heuristics

Applied in order. First match wins. If nothing matches, default to `medical`.

**UHC pharmacy EOB shortcut:** when all three of these signals appear together — `Provider: Pharmacy` (literal, UHC EOB label), a `PRESCRIPTION DRUGS` service line, and claim code `FB` (UHC explains it as "THIS CLAIM WAS PROCESSED BY YOUR PHARMACY DRUG BENEFIT PROGRAM.") — classification is high-confidence `prescriptions`. Still follow the normal confirm-with-user flow, but propose it directly ("this is `prescriptions`") rather than hedging. Any single one of these three is already strong evidence on its own.

| Type | Signals in receipt text |
|---|---|
| `dental` | `DENTAL`, `ORTHODONTIC`, `DDS`, "dentist", cleaning, filling, crown, root canal |
| `vision` | `OPTICAL`, `OPTOMETRY`, `VISION`, `EYE EXAM`, `OD` (doctor of optometry), eyeglasses, contacts |
| `mental-health` | `PSYCHIATRY`, `PSYCHOLOGY`, `PSYCHOTHERAPY`, `COUNSELING`, `BEHAVIORAL HEALTH`, LCSW, LMHC. `THERAPY` alone is ambiguous (could be physical therapy) — ask the user |
| `prescriptions` | Provider field is literally `Pharmacy` (UHC EOB label), receipt contains `PRESCRIPTION DRUGS` service line, or claim code `FB` (UHC's "processed by pharmacy drug benefit program") — any of these is strong evidence, all three together is essentially certain. Also: `PHARMACY`, `RX`, prescription drug names, CVS / Walgreens / Duane Reade / Rite Aid as provider |
| `equipment` | `DME`, `DURABLE MEDICAL EQUIPMENT`, CPAP, wheelchair, crutches, orthotics, braces |
| `wellness` | `GYM`, `FITNESS`, wellness program, acupuncture — always ask the user (plan-dependent) |
| `medical` | Default. Also: `RADIOLOGY`, `LABORATORY`, `OUTPATIENT`, `MEDICAL SERVICES`, `EMERGENCY`, copays, OON deductibles, primary care |

## Notes

- Never auto-submit when this skill is run directly. This skill only sets `type`. The
  user may use `/submit-claim` separately, or `/submit-claim` may invoke this
  classification workflow inline when a receipt-created claim is missing `type`.
- Do not overwrite a non-null `type` without explicit user permission.
- If the receipt PDF is unreadable or ambiguous, ask the user directly rather than guessing.
- Keep the "Classification rules learned" list terse. Duplicate rules should be deduplicated when found.
- If a heuristic is consistently wrong, consider proposing an edit to the heuristics table above (flag it to the user, don't edit unilaterally).

## Classification rules learned

Rules learned from user corrections. Claude: read these before applying default heuristics.

No project-specific correction rules are tracked in the shared repo. Keep personal
provider details, exact amounts, and service descriptions in local-only notes if
they are needed for a private workflow.
<!-- Append new rules above this line -->
