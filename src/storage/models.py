"""Data models for claims management."""

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from typing import Optional

from src.config import normalize_claimant_name


VALID_STATUSES = ["pending", "submitted"]
VALID_SOURCES = ["direct", "uhc"]
LEGACY_UHC_CLAIM_PREFIX = "UHC Claim "


def _now_iso() -> str:
    """Return current timestamp in ISO format."""
    return datetime.now().isoformat()


@dataclass
class Claim:
    """Represents a reimbursement claim that will ultimately be submitted to OCA."""

    id: str
    source: str = "direct"
    status: str = "pending"
    submitted_at: Optional[str] = None
    type: Optional[str] = None
    service_date: Optional[str] = None
    amount: Optional[float] = None
    provider: Optional[str] = None
    claimant: Optional[str] = None
    source_claim_number: Optional[str] = None
    notes: str = ""

    def to_dict(self) -> dict:
        """Convert claim to dictionary."""
        return asdict(self)

    def to_json(self) -> str:
        """Convert claim to JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> "Claim":
        """Create claim from dictionary with migration support."""
        notes = data.get("notes", "")

        if "source" in data and "status" in data:
            return cls(
                id=data["id"],
                source=data.get("source", "direct"),
                status=data.get("status", "pending"),
                submitted_at=data.get("submitted_at"),
                type=data.get("type"),
                service_date=data.get("service_date"),
                amount=data.get("amount"),
                provider=data.get("provider"),
                claimant=_normalize_loaded_claimant(data.get("claimant")),
                source_claim_number=data.get("source_claim_number"),
                notes=notes,
            )

        legacy_status = data.get("status")
        if legacy_status is not None and "oca_status" not in data:
            status = "submitted" if legacy_status == "submitted" else "pending"
        else:
            status = data.get("oca_status", "pending")

        source = "direct"
        source_claim_number = data.get("source_claim_number")
        if source_claim_number:
            source = "uhc"
        else:
            uhc_note = extract_uhc_claim_number(notes)
            if uhc_note:
                source = "uhc"
                source_claim_number = uhc_note
            elif data.get("uhc_status") == "processed":
                source = "uhc"

        submitted_at = data.get("submitted_at") or data.get("oca_submitted_at")

        return cls(
            id=data["id"],
            source=source,
            status=status,
            submitted_at=submitted_at,
            type=data.get("type"),
            service_date=data.get("service_date"),
            amount=data.get("amount"),
            provider=data.get("provider"),
            claimant=_normalize_loaded_claimant(data.get("claimant")),
            source_claim_number=source_claim_number,
            notes=notes,
        )

    @classmethod
    def from_json(cls, json_str: str) -> "Claim":
        """Create claim from JSON string."""
        return cls.from_dict(json.loads(json_str))

    def is_parsed(self) -> bool:
        """Check if claim has enough extracted metadata for submission."""
        return self.service_date is not None and self.amount is not None

    def is_ready_for_submission(self) -> bool:
        """Check if claim is ready for OCA submission."""
        return self.is_parsed() and self.type is not None and self.status == "pending"


def extract_uhc_claim_number(notes: str) -> Optional[str]:
    """Parse legacy note text to recover a UHC source claim number."""
    if LEGACY_UHC_CLAIM_PREFIX not in notes:
        return None
    suffix = notes.split(LEGACY_UHC_CLAIM_PREFIX, 1)[1].strip()
    if not suffix:
        return None
    return suffix.split()[0]


def _normalize_loaded_claimant(claimant: Optional[str]) -> Optional[str]:
    """Canonicalize configured claimant names while preserving unknown legacy values."""
    if claimant is None:
        return None
    return normalize_claimant_name(claimant, strict=False)


VALID_TYPES = [
    "prescriptions",
    "dental",
    "vision",
    "medical",
    "mental-health",
    "equipment",
    "wellness",
]
