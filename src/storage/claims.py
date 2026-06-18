"""Core logic for claims management."""

import json
import shutil
from datetime import date
from pathlib import Path
from typing import Optional

from src.config import normalize_claimant_name

from .models import Claim, VALID_SOURCES, VALID_STATUSES, VALID_TYPES, _now_iso


DATA_DIR = Path(__file__).parent.parent.parent / "data"
CLAIMS_DIR = DATA_DIR / "claims"
INDEX_FILE = DATA_DIR / "claims.json"


def _ensure_dirs():
    """Ensure data directories exist."""
    CLAIMS_DIR.mkdir(parents=True, exist_ok=True)


def _load_index() -> list[str]:
    """Load the claims index."""
    if not INDEX_FILE.exists():
        return []
    with open(INDEX_FILE) as f:
        data = json.load(f)
    return data.get("claims", [])


def _save_index(claim_ids: list[str]):
    """Save the claims index."""
    _ensure_dirs()
    with open(INDEX_FILE, "w") as f:
        json.dump({"claims": claim_ids}, f, indent=2)


def _generate_id() -> str:
    """Generate a unique claim ID: {date}_{sequence}."""
    today = date.today().isoformat()
    today_claims = [cid for cid in _load_index() if cid.startswith(today)]
    sequence = len(today_claims) + 1
    return f"{today}_{sequence:03d}"


def _get_claim_dir(claim_id: str) -> Path:
    """Get the directory path for a claim."""
    return CLAIMS_DIR / claim_id


def _get_claim_file(claim_id: str) -> Path:
    """Get the claim.json file path for a claim."""
    return _get_claim_dir(claim_id) / "claim.json"


def _get_receipts_dir(claim_id: str) -> Path:
    """Get the receipts directory for a claim."""
    return _get_claim_dir(claim_id) / "receipts"


def _validate_type(type_: Optional[str]):
    """Validate claim type when present."""
    if type_ is not None and type_ not in VALID_TYPES:
        raise ValueError(f"Invalid claim type: {type_}. Must be one of: {VALID_TYPES}")


def _validate_status(status: str):
    """Validate unified submission status."""
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}. Must be one of: {VALID_STATUSES}")


def _validate_source(source: str):
    """Validate claim source."""
    if source not in VALID_SOURCES:
        raise ValueError(f"Invalid source: {source}. Must be one of: {VALID_SOURCES}")


def _load_claim(claim_id: str) -> Claim:
    """Load one claim from disk."""
    claim_file = _get_claim_file(claim_id)
    if not claim_file.exists():
        raise ValueError(f"Claim not found: {claim_id}")
    with open(claim_file) as f:
        return Claim.from_dict(json.load(f))


def _save_claim(claim: Claim):
    """Persist one claim to disk."""
    with open(_get_claim_file(claim.id), "w") as f:
        f.write(claim.to_json())


def _iter_claim_files() -> list[Path]:
    """Return all claim.json files currently stored on disk."""
    if not CLAIMS_DIR.exists():
        return []
    return sorted(CLAIMS_DIR.glob("*/claim.json"))


def _receipt_paths(claim_id: str) -> list[str]:
    """Return sorted receipt paths for a claim."""
    receipts_dir = _get_receipts_dir(claim_id)
    if not receipts_dir.exists():
        return []
    return [str(p) for p in sorted(receipts_dir.glob("*")) if p.is_file()]


def create_claim(
    claim_type: Optional[str] = None,
    source: str = "direct",
    source_claim_number: Optional[str] = None,
    claimant: Optional[str] = None,
) -> Claim:
    """Create a new claim with empty metadata."""
    _validate_type(claim_type)
    _validate_source(source)

    _ensure_dirs()

    claim = Claim(
        id=_generate_id(),
        source=source,
        type=claim_type,
        source_claim_number=source_claim_number,
        claimant=normalize_claimant_name(claimant) if claimant is not None else None,
    )

    claim_dir = _get_claim_dir(claim.id)
    claim_dir.mkdir(parents=True, exist_ok=True)
    _get_receipts_dir(claim.id).mkdir(exist_ok=True)

    _save_claim(claim)

    index = _load_index()
    index.append(claim.id)
    _save_index(index)

    return claim


def add_receipt(claim_id: str, receipt_path: str) -> str:
    """Add a receipt to an existing claim."""
    claim_dir = _get_claim_dir(claim_id)
    if not claim_dir.exists():
        raise ValueError(f"Claim not found: {claim_id}")

    receipt_src = Path(receipt_path)
    if not receipt_src.exists():
        raise ValueError(f"Receipt file not found: {receipt_path}")

    receipts_dir = _get_receipts_dir(claim_id)
    receipts_dir.mkdir(exist_ok=True)

    existing = list(receipts_dir.glob("receipt_*"))
    sequence = len(existing) + 1
    ext = receipt_src.suffix or ".pdf"
    receipt_name = f"receipt_{sequence:03d}{ext}"

    receipt_dest = receipts_dir / receipt_name
    shutil.copy2(receipt_src, receipt_dest)
    return str(receipt_dest)


def migrate_claims(dry_run: bool = False) -> dict[str, object]:
    """Rewrite legacy claim files into the current schema intentionally."""
    _ensure_dirs()
    claim_files = _iter_claim_files()

    migrated_ids: list[str] = []
    for claim_file in claim_files:
        with open(claim_file) as f:
            raw_data = json.load(f)

        claim = Claim.from_dict(raw_data)
        normalized_data = claim.to_dict()
        if raw_data == normalized_data:
            continue

        migrated_ids.append(claim.id)
        if not dry_run:
            _save_claim(claim)

    return {
        "total_claims": len(claim_files),
        "migrated_claims": len(migrated_ids),
        "claim_ids": migrated_ids,
        "dry_run": dry_run,
    }


def list_claims(
    status: Optional[str] = None,
    source: Optional[str] = None,
    unparsed: bool = False,
    ready: bool = False,
) -> list[dict]:
    """List all claims with optional filtering."""
    if status:
        _validate_status(status)
    if source:
        _validate_source(source)

    claims = []
    for claim_id in _load_index():
        claim_file = _get_claim_file(claim_id)
        if not claim_file.exists():
            continue

        with open(claim_file) as f:
            claim = Claim.from_dict(json.load(f))

        if status and claim.status != status:
            continue
        if source and claim.source != source:
            continue
        if unparsed and claim.is_parsed():
            continue

        receipt_paths = _receipt_paths(claim_id)
        if ready and not claim.is_ready_for_submission():
            continue
        if ready and not receipt_paths:
            continue

        claim_dict = claim.to_dict()
        claim_dict["receipts"] = receipt_paths
        claims.append(claim_dict)

    return claims


def get_claim(claim_id: str) -> dict:
    """Get a single claim with its receipt paths."""
    claim = _load_claim(claim_id)
    claim_dict = claim.to_dict()
    claim_dict["receipts"] = _receipt_paths(claim_id)
    return claim_dict


def update_claim(
    claim_id: str,
    service_date: Optional[str] = None,
    amount: Optional[float] = None,
    provider: Optional[str] = None,
    claimant: Optional[str] = None,
    notes: Optional[str] = None,
    type_: Optional[str] = None,
    source_claim_number: Optional[str] = None,
) -> Claim:
    """Update claim metadata fields."""
    _validate_type(type_)

    claim = _load_claim(claim_id)

    if service_date is not None:
        claim.service_date = service_date
    if amount is not None:
        claim.amount = amount
    if provider is not None:
        claim.provider = provider
    if claimant is not None:
        claim.claimant = normalize_claimant_name(claimant)
    if notes is not None:
        claim.notes = notes
    if type_ is not None:
        claim.type = type_
    if source_claim_number is not None:
        claim.source_claim_number = source_claim_number

    _save_claim(claim)
    return claim


def set_status(claim_id: str, status: str) -> Claim:
    """Update the unified OCA submission status."""
    _validate_status(status)

    claim = _load_claim(claim_id)
    claim.status = status
    if status == "submitted" and claim.submitted_at is None:
        claim.submitted_at = _now_iso()

    _save_claim(claim)
    return claim
