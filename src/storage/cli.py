#!/usr/bin/env python3
"""CLI for claims management."""

import argparse
import json
import sys

from .claims import (
    add_receipt,
    create_claim,
    get_claim,
    list_claims,
    migrate_claims,
    set_status,
    update_claim,
)
from .models import VALID_SOURCES, VALID_STATUSES, VALID_TYPES


def cmd_new(args):
    """Create a new claim."""
    try:
        claim = create_claim(
            claim_type=args.type,
            source=args.source,
            source_claim_number=args.source_claim_number,
            claimant=args.claimant,
        )
        print(json.dumps(claim.to_dict(), indent=2))
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_add_receipt(args):
    """Add a receipt to a claim."""
    try:
        receipt_path = add_receipt(args.claim_id, args.receipt)
        print(json.dumps({"claim_id": args.claim_id, "receipt_path": receipt_path}))
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_list(args):
    """List all claims."""
    try:
        claims = list_claims(
            status=getattr(args, "status", None),
            source=getattr(args, "source", None),
            unparsed=args.unparsed,
            ready=getattr(args, "ready", False),
        )

        if args.json:
            print(json.dumps(claims, indent=2))
            return

        if not claims:
            print("No claims found.")
            return

        print(f"{'ID':<20} {'Source':<8} {'Status':<10} {'Type':<14} {'Amount':<10} {'Provider':<15}")
        print("-" * 92)
        for c in claims:
            amount = f"${c['amount']:.2f}" if c["amount"] is not None else "-"
            provider = (
                c["provider"][:13] + ".."
                if c["provider"] and len(c["provider"]) > 15
                else (c["provider"] or "-")
            )
            parsed = " *" if not c["service_date"] or c["amount"] is None else ""
            ctype = c["type"] or "-"
            print(
                f"{c['id']:<20} {c['source']:<8} {c['status']:<10} "
                f"{ctype:<14} {amount:<10} {provider:<15}{parsed}"
            )

        print("\n* = needs metadata")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_get(args):
    """Get a claim by ID."""
    try:
        claim = get_claim(args.claim_id)
        print(json.dumps(claim, indent=2))
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_update(args):
    """Update claim metadata."""
    try:
        claim = update_claim(
            args.claim_id,
            service_date=args.service_date,
            amount=float(args.amount) if args.amount else None,
            provider=args.provider,
            claimant=args.claimant,
            notes=args.notes,
            type_=args.type,
            source_claim_number=args.source_claim_number,
        )
        print(json.dumps(claim.to_dict(), indent=2))
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_set_status(args):
    """Set claim status."""
    try:
        claim = set_status(args.claim_id, args.status)
        print(json.dumps(claim.to_dict(), indent=2))
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_migrate(args):
    """Rewrite legacy claim files into the current schema."""
    try:
        result = migrate_claims(dry_run=args.dry_run)
        if args.json:
            print(json.dumps(result, indent=2))
            return

        action = "Would migrate" if args.dry_run else "Migrated"
        print(
            f"{action} {result['migrated_claims']} of {result['total_claims']} claim file(s)."
        )
        if result["claim_ids"]:
            for claim_id in result["claim_ids"]:
                print(f"- {claim_id}")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Claims management CLI",
        prog="python -m src.storage.cli",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    new_parser = subparsers.add_parser("new", help="Create a new claim")
    new_parser.add_argument(
        "--type",
        "-t",
        choices=VALID_TYPES,
        help="Claim type",
    )
    new_parser.add_argument(
        "--source",
        choices=VALID_SOURCES,
        default="direct",
        help="Claim source",
    )
    new_parser.add_argument(
        "--source-claim-number",
        help="External source claim number for imported claims",
    )
    new_parser.add_argument(
        "--claimant",
        help="Claimant name from config/claimants.toml; unique first names are accepted",
    )
    new_parser.set_defaults(func=cmd_new)

    add_receipt_parser = subparsers.add_parser("add-receipt", help="Add a receipt to a claim")
    add_receipt_parser.add_argument("claim_id", help="Claim ID")
    add_receipt_parser.add_argument("receipt", help="Path to receipt file")
    add_receipt_parser.set_defaults(func=cmd_add_receipt)

    list_parser = subparsers.add_parser("list", help="List claims")
    list_parser.add_argument(
        "--status",
        choices=VALID_STATUSES,
        help="Filter by submission status",
    )
    list_parser.add_argument(
        "--source",
        choices=VALID_SOURCES,
        help="Filter by claim source",
    )
    list_parser.add_argument(
        "--unparsed",
        "-u",
        action="store_true",
        help="Only show claims missing parsed metadata",
    )
    list_parser.add_argument(
        "--ready",
        action="store_true",
        help="Only show claims ready for OCA submission",
    )
    list_parser.add_argument(
        "--json",
        "-j",
        action="store_true",
        help="Output as JSON",
    )
    list_parser.set_defaults(func=cmd_list)

    get_parser = subparsers.add_parser("get", help="Get a claim by ID")
    get_parser.add_argument("claim_id", help="Claim ID")
    get_parser.set_defaults(func=cmd_get)

    update_parser = subparsers.add_parser("update", help="Update claim metadata")
    update_parser.add_argument("claim_id", help="Claim ID")
    update_parser.add_argument("--service-date", help="Service date (YYYY-MM-DD)")
    update_parser.add_argument("--amount", help="Claim amount")
    update_parser.add_argument("--provider", help="Provider name")
    update_parser.add_argument(
        "--claimant",
        help="Claimant name from config/claimants.toml; unique first names are accepted",
    )
    update_parser.add_argument("--notes", help="Additional notes")
    update_parser.add_argument(
        "--type",
        choices=VALID_TYPES,
        help="Claim type",
    )
    update_parser.add_argument(
        "--source-claim-number",
        help="External source claim number for imported claims",
    )
    update_parser.set_defaults(func=cmd_update)

    set_status_parser = subparsers.add_parser("set-status", help="Set submission status")
    set_status_parser.add_argument("claim_id", help="Claim ID")
    set_status_parser.add_argument(
        "status",
        choices=VALID_STATUSES,
        help="New submission status",
    )
    set_status_parser.set_defaults(func=cmd_set_status)

    migrate_parser = subparsers.add_parser(
        "migrate",
        help="Rewrite legacy claim files into the current schema",
    )
    migrate_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview which claim files would be rewritten",
    )
    migrate_parser.add_argument(
        "--json",
        action="store_true",
        help="Output migration summary as JSON",
    )
    migrate_parser.set_defaults(func=cmd_migrate)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
