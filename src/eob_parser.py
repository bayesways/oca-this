#!/usr/bin/env python3
"""Parse UHC Explanation of Benefits (EOB) PDFs into OCA-submittable claims."""

import argparse
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

# Allow running as script or module
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.config import extract_claimant_first_name_from_text, resolve_claimant_marker
from src.storage.claims import create_claim, add_receipt, update_claim, list_claims
from src.storage.models import LEGACY_UHC_CLAIM_PREFIX, extract_uhc_claim_number


def _load_existing_uhc_claims() -> dict[str, str]:
    """Map UHC claim number -> local claim id."""
    mapping: dict[str, str] = {}
    for claim in list_claims():
        source_claim_number = claim.get("source_claim_number")
        if source_claim_number:
            mapping[source_claim_number] = claim.get("id", "")
            continue
        notes = claim.get("notes") or ""
        source_claim_number = extract_uhc_claim_number(notes)
        if source_claim_number:
            mapping[source_claim_number] = claim.get("id", "")
    return mapping


@dataclass
class ParsedClaim:
    """A claim extracted from an EOB."""
    claim_number: str
    provider: str
    service_date: str  # earliest date, YYYY-MM-DD
    amount_owed: float
    pages: list[int] = field(default_factory=list)  # 1-indexed page numbers
    claimant: str | None = None


def parse_total_owed(page_text: str) -> float | None:
    """Extract 'Your total amount owed' from the front page."""
    match = re.search(r"Your total amount owed\s*\n?\$?([\d,]+\.\d{2})", page_text)
    if match:
        return float(match.group(1).replace(",", ""))
    return None


def _parse_date(date_str: str) -> str:
    """Convert MM/DD/YYYY to YYYY-MM-DD."""
    parts = date_str.strip().split("/")
    if len(parts) == 3:
        return f"{parts[2]}-{parts[0]:>02}-{parts[1]:>02}"
    return date_str


def _extract_claims_from_page(text: str) -> list[dict]:
    """Extract claim headers and totals from a single page's text.

    Returns a list of dicts with keys: claim_number, provider, has_total,
    total_owed, dates (list of service dates found).
    """
    claims = []

    # Find all claim headers on this page:
    # Pattern: "Provider: <name>\n...\nClaim number: <number>"
    header_pattern = re.compile(
        r"Provider:\s*([^\n]+).*?Claim number:\s*(\S+)",
        re.DOTALL,
    )

    for match in header_pattern.finditer(text):
        provider = match.group(1).strip()
        claim_number = match.group(2).strip()
        start_pos = match.start()
        claims.append({
            "claim_number": claim_number,
            "provider": provider,
            "start_pos": start_pos,
            "has_total": False,
            "total_owed": 0.0,
            "dates": [],
        })

    # For each claim section, find dates and totals
    for i, claim in enumerate(claims):
        # Section runs from this header to the next header (or end of text)
        start = claim["start_pos"]
        end = claims[i + 1]["start_pos"] if i + 1 < len(claims) else len(text)
        section = text[start:end]

        # Extract service dates (MM/DD/YYYY patterns)
        date_pattern = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")
        claim["dates"] = [_parse_date(d) for d in date_pattern.findall(section)]

        # Check for "Total amount" row — values are on separate lines after it
        # 9 values: billed, saved, allowed, plan paid, deductible, copay,
        # coinsurance, plan does not cover, amount you owe (last one)
        total_match = re.search(
            r"Total amount\n((?:[-\$\d,]+\.\d{2}\n){9})", section
        )
        if total_match:
            claim["has_total"] = True
            amounts = re.findall(r"[-\$\d,]+\.\d{2}", total_match.group(1))
            if len(amounts) >= 9:
                # Last amount is "Amount you owe"
                claim["total_owed"] = float(
                    amounts[-1].replace("$", "").replace(",", "")
                )

    # Clean up internal field
    for claim in claims:
        del claim["start_pos"]

    return claims


def parse_eob(pdf_path: str) -> tuple[float, list[ParsedClaim], list[ParsedClaim]]:
    """Parse an EOB PDF.

    Returns:
        (total_owed_from_front_page, oop_claims, all_detected_claims)
        where oop_claims are claims with amount_owed > 0, and
        all_detected_claims includes zero-OOP claims too (for verification).
    """
    doc = fitz.open(pdf_path)

    # Stage 1: Front page gate check
    front_text = doc[0].get_text()
    total_owed = parse_total_owed(front_text)
    if total_owed is None:
        doc.close()
        raise ValueError("Could not find 'Your total amount owed' on the front page.")
    if total_owed == 0.0:
        doc.close()
        return 0.0, [], []

    # Stage 2: Parse claim detail pages
    # Track claims by claim_number -> ParsedClaim
    claims_map: dict[str, ParsedClaim] = {}
    # Track which claims are still open (no Total row seen yet)
    open_claims: set[str] = set()

    for page_idx in range(len(doc)):
        page_num = page_idx + 1  # 1-indexed
        text = doc[page_idx].get_text()

        claimant_marker = extract_claimant_first_name_from_text(text)
        page_claimant = resolve_claimant_marker(claimant_marker)
        if page_claimant is None:
            if claimant_marker is not None:
                print(
                    f"SKIP page {page_num}: claimant marker '{claimant_marker}' "
                    "is unconfigured or ambiguous.",
                    file=sys.stderr,
                )
            continue

        page_claims = _extract_claims_from_page(text)

        if not page_claims and open_claims:
            # Continuation page with no new headers — belongs to open claims
            for cn in open_claims:
                if page_num not in claims_map[cn].pages:
                    claims_map[cn].pages.append(page_num)
            continue

        for pc in page_claims:
            cn = pc["claim_number"]

            if cn not in claims_map:
                # New claim
                earliest_date = min(pc["dates"]) if pc["dates"] else ""
                claims_map[cn] = ParsedClaim(
                    claim_number=cn,
                    provider=pc["provider"],
                    service_date=earliest_date,
                    amount_owed=0.0,
                    pages=[page_num],
                    claimant=page_claimant,
                )
                open_claims.add(cn)
            else:
                # Continuation of existing claim on a new page
                if page_num not in claims_map[cn].pages:
                    claims_map[cn].pages.append(page_num)
                if claims_map[cn].claimant != page_claimant:
                    raise ValueError(
                        f"Claim {cn} changed claimant across pages: "
                        f"{claims_map[cn].claimant} -> {page_claimant}"
                    )
                # Update earliest date if we found earlier ones
                if pc["dates"]:
                    all_dates = [claims_map[cn].service_date] + pc["dates"]
                    all_dates = [d for d in all_dates if d]
                    claims_map[cn].service_date = min(all_dates)

            if pc["has_total"]:
                claims_map[cn].amount_owed = pc["total_owed"]
                open_claims.discard(cn)

    doc.close()

    all_claims = list(claims_map.values())
    # Filter to claims with OOP > 0
    oop_claims = [c for c in all_claims if c.amount_owed > 0]

    return total_owed, oop_claims, all_claims


def extract_pages(pdf_path: str, pages: list[int], output_path: str):
    """Extract specific pages (1-indexed) from a PDF into a new PDF."""
    doc = fitz.open(pdf_path)
    new_doc = fitz.open()
    for page_num in sorted(pages):
        new_doc.insert_pdf(doc, from_page=page_num - 1, to_page=page_num - 1)
    new_doc.save(output_path)
    new_doc.close()
    doc.close()


class VerificationError(Exception):
    """Raised when per-claim OOPs don't sum to the front-page total."""


def _verify_total(
    pdf_path: str,
    total_owed: float,
    all_claims: list[ParsedClaim],
) -> float:
    """Cross-check sum of per-claim OOPs vs front-page total. Raise on mismatch."""
    sum_claims = sum(c.amount_owed for c in all_claims)
    if abs(sum_claims - total_owed) > 0.01:
        lines = [
            f"Verification FAILED for {pdf_path}",
            f"  Front-page total:      ${total_owed:,.2f}",
            f"  Sum of detected claims: ${sum_claims:,.2f}",
            f"  Difference:             ${total_owed - sum_claims:,.2f}",
            f"  Detected {len(all_claims)} claim(s):",
        ]
        for c in all_claims:
            lines.append(
                f"    - {c.claim_number} | {c.provider} | ${c.amount_owed:,.2f} | pages {c.pages}"
            )
        raise VerificationError("\n".join(lines))
    return sum_claims


def run(
    pdf_path: str,
    dry_run: bool = False,
    seen_uhc_claims: dict[str, str] | None = None,
) -> tuple[int, int]:
    """Parse EOB and optionally create claims.

    Returns (created_or_shown_count, skipped_duplicate_count).

    `seen_uhc_claims` maps UHC claim number -> local claim id. If None, it is
    loaded from existing claims so across-run duplicates are caught. Pass a
    shared dict in directory mode to also catch within-run duplicates across
    multiple EOBs.
    """
    if seen_uhc_claims is None:
        seen_uhc_claims = _load_existing_uhc_claims()

    total_owed, claims, all_claims = parse_eob(pdf_path)

    print(f"\nEOB Parser Results: {pdf_path}")
    print(f"==================")
    print(f"Total amount owed (front page): ${total_owed:,.2f}")

    if total_owed == 0:
        print("\nNo out-of-pocket costs. Nothing to submit.")
        return 0, 0

    # Verify before any side effects
    sum_claims = _verify_total(pdf_path, total_owed, all_claims)
    print(
        f"Verification passed: sum of {len(all_claims)} detected claim(s) "
        f"= ${sum_claims:,.2f} matches front page."
    )

    if not claims:
        print("\nNo individual claims with out-of-pocket costs found.")
        return 0, 0

    # Partition into new vs. duplicates so counts and messaging are honest.
    new_claims: list[ParsedClaim] = []
    skipped = 0
    for c in claims:
        if c.claim_number in seen_uhc_claims:
            existing_id = seen_uhc_claims[c.claim_number] or "<unknown>"
            print(
                f"SKIP: UHC claim {c.claim_number} already exists as "
                f"{existing_id} — not creating duplicate."
            )
            skipped += 1
        else:
            new_claims.append(c)

    total_oop = sum(c.amount_owed for c in new_claims)

    if dry_run:
        if new_claims:
            print(f"\nClaims with out-of-pocket costs:\n")
            for i, c in enumerate(new_claims, 1):
                print(f"  {i}. Claim {c.claim_number}")
                print(f"     Claimant:     {c.claimant}")
                print(f"     Provider:     {c.provider}")
                print(f"     Service date: {c.service_date}")
                print(f"     Amount owed:  ${c.amount_owed:,.2f}")
                print(f"     Pages:        {', '.join(str(p) for p in c.pages)}")
                print(f"     Type:         unknown (set before OCA submission)")
                print()
            # Reserve the claim number so later dry-run EOBs in the same batch
            # also see this as a duplicate.
            for c in new_claims:
                seen_uhc_claims.setdefault(c.claim_number, "<pending-dry-run>")
        print(
            f"Total out-of-pocket (new): ${total_oop:,.2f} "
            f"({len(new_claims)} to create, {skipped} duplicate{'s' if skipped != 1 else ''} skipped)"
        )
        if new_claims:
            print(f"Run without --dry-run to create claims.")
        return len(new_claims), skipped
    else:
        if new_claims:
            print(f"\nCreated {len(new_claims)} claim(s) ({skipped} duplicate(s) skipped):\n")
        else:
            print(f"\nNo new claims created ({skipped} duplicate(s) skipped).")
        for i, c in enumerate(new_claims, 1):
            # Create claim entry
            claim = create_claim(
                claim_type=None,
                source="uhc",
                source_claim_number=c.claim_number,
            )
            # Update metadata
            update_claim(
                claim.id,
                service_date=c.service_date,
                amount=c.amount_owed,
                provider=c.provider,
                claimant=c.claimant,
                notes=f"{LEGACY_UHC_CLAIM_PREFIX}{c.claim_number}",
                source_claim_number=c.claim_number,
            )
            # Extract pages into a temp PDF, then add as receipt
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                extract_pages(pdf_path, c.pages, tmp_path)
                receipt_path = add_receipt(claim.id, tmp_path)
            finally:
                Path(tmp_path).unlink(missing_ok=True)

            # Record so subsequent EOBs in the same batch don't double-create.
            seen_uhc_claims[c.claim_number] = claim.id

            print(f"  {i}. {claim.id} - {c.provider} - ${c.amount_owed:,.2f}")
            print(f"     Claimant: {c.claimant}")
            print(f"     Receipt: {receipt_path} ({len(c.pages)} page{'s' if len(c.pages) != 1 else ''})")
            print(f"     source: uhc | type: needs to be set")
            print()

        if new_claims:
            print(f"Total out-of-pocket: ${total_oop:,.2f}")
            print("Set claim types, then use /submit-claim --id <claim_id> for each.")
        return len(new_claims), skipped


def _collect_pdfs(path: Path) -> list[Path]:
    """Return list of PDF paths. If `path` is a file, returns [path].
    If a directory, returns *.pdf / *.PDF matches (non-recursive)."""
    if path.is_file():
        return [path]
    pdfs = sorted({*path.glob("*.pdf"), *path.glob("*.PDF")})
    return list(pdfs)


def main():
    parser = argparse.ArgumentParser(
        description="Parse UHC EOB PDFs and create claims for out-of-pocket costs.",
    )
    parser.add_argument(
        "eob_pdf",
        help="Path to an EOB PDF file, or a directory containing EOB PDFs",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and display results without creating claims",
    )
    args = parser.parse_args()

    input_path = Path(args.eob_pdf)
    if not input_path.exists():
        print(f"Error: Path not found: {args.eob_pdf}", file=sys.stderr)
        sys.exit(1)

    pdfs = _collect_pdfs(input_path)
    if not pdfs:
        print(f"Error: No PDFs found in {args.eob_pdf}", file=sys.stderr)
        sys.exit(1)

    # Single-file mode: preserve existing behavior (no summary footer).
    if input_path.is_file():
        try:
            run(str(pdfs[0]), dry_run=args.dry_run)
        except VerificationError as e:
            print(f"\n{e}", file=sys.stderr)
            sys.exit(2)
        return

    # Directory mode: process each, continue on verification failure.
    # Share one seen-map across all EOBs so duplicates within the batch are caught.
    seen_uhc_claims = _load_existing_uhc_claims()
    processed = 0
    failed = 0
    total_claims = 0
    total_skipped = 0
    for pdf in pdfs:
        try:
            n, skipped = run(str(pdf), dry_run=args.dry_run, seen_uhc_claims=seen_uhc_claims)
            processed += 1
            total_claims += n
            total_skipped += skipped
        except VerificationError as e:
            print(f"\n{e}", file=sys.stderr)
            failed += 1
        except Exception as e:
            print(f"\nError processing {pdf}: {e}", file=sys.stderr)
            failed += 1

    print()
    print("=" * 50)
    print(
        f"{processed} EOB{'s' if processed != 1 else ''} processed, "
        f"{total_claims} claim{'s' if total_claims != 1 else ''} "
        f"{'shown' if args.dry_run else 'created'}, "
        f"{total_skipped} duplicate{'s' if total_skipped != 1 else ''} skipped, "
        f"{failed} EOB{'s' if failed != 1 else ''} failed verification"
    )
    if failed:
        sys.exit(2)


if __name__ == "__main__":
    main()
