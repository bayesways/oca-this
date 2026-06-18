"""Project configuration helpers."""

from dataclasses import dataclass
import os
from pathlib import Path
import re
import tomllib


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLAIMANT_CONFIG_FILE = PROJECT_ROOT / "config" / "claimants.toml"
CLAIMANT_CONFIG_EXAMPLE_FILE = PROJECT_ROOT / "config" / "claimants.example.toml"
CLAIMANT_MARKER_RE = re.compile(r"Claim detail for\s+([A-Za-z]+)", re.IGNORECASE)


@dataclass(frozen=True)
class ClaimantDirectory:
    """Configured claimant names plus accepted aliases."""

    claimants: tuple[str, ...]
    aliases: dict[str, str]


def _clean_claimant_name(name: str) -> str:
    """Normalize spacing without changing the claimant's configured case."""
    cleaned = " ".join(name.strip().split())
    if not cleaned:
        raise ValueError("Claimant name cannot be empty.")
    return cleaned


def _alias_key(name: str) -> str:
    """Return a case-insensitive lookup key for claimant names."""
    return _clean_claimant_name(name).casefold()


def _claimant_config_path(config_path: Path | None = None) -> Path:
    """Resolve the claimant config file path."""
    if config_path is not None:
        return config_path
    env_path = os.environ.get("OCA_CLAIMANT_CONFIG")
    if env_path:
        return Path(env_path)
    return CLAIMANT_CONFIG_FILE


def load_claimant_directory(config_path: Path | None = None) -> ClaimantDirectory:
    """Load allowed claimant names from the project config file."""
    config_path = _claimant_config_path(config_path)
    if not config_path.exists():
        raise ValueError(
            f"Claimant config not found at {config_path}. "
            f"Create it from {CLAIMANT_CONFIG_EXAMPLE_FILE}."
        )

    with open(config_path, "rb") as f:
        raw = tomllib.load(f)

    claimants = raw.get("claimants", {}).get("allowed")
    if not isinstance(claimants, list) or not claimants:
        raise ValueError(
            f"{config_path} must define [claimants].allowed with at least one claimant."
        )

    cleaned_claimants = tuple(_clean_claimant_name(str(name)) for name in claimants)

    aliases: dict[str, str] = {}
    first_name_candidates: dict[str, set[str]] = {}
    for claimant in cleaned_claimants:
        aliases[_alias_key(claimant)] = claimant
        first_name = claimant.split()[0]
        first_name_candidates.setdefault(_alias_key(first_name), set()).add(claimant)

    for key, matches in first_name_candidates.items():
        if len(matches) == 1:
            aliases[key] = next(iter(matches))

    return ClaimantDirectory(claimants=cleaned_claimants, aliases=aliases)


def normalize_claimant_name(
    name: str,
    *,
    strict: bool = True,
    config_path: Path | None = None,
) -> str:
    """Resolve a claimant name or first-name alias to its configured full name."""
    directory = load_claimant_directory(config_path)
    cleaned = _clean_claimant_name(name)
    resolved = directory.aliases.get(cleaned.casefold())
    if resolved:
        return resolved
    if strict:
        raise ValueError(
            f"Unknown claimant '{cleaned}'. Allowed claimants: "
            f"{', '.join(directory.claimants)}."
        )
    return cleaned


def extract_claimant_first_name_from_text(text: str) -> str | None:
    """Extract the claimant marker first name from a UHC detail page.

    This intentionally matches ASCII letters only because current claimant names
    are Latin-script first names in the source PDFs.
    """
    match = CLAIMANT_MARKER_RE.search(text)
    if not match:
        return None
    return match.group(1)


def resolve_claimant_marker(
    first_name: str | None, *, config_path: Path | None = None
) -> str | None:
    """Resolve an already-extracted marker first name to a configured full name.

    Returns None when the marker is missing, unknown, or ambiguous. Callers that
    have already scanned the page should use this together with
    `extract_claimant_first_name_from_text` to avoid running the marker regex twice.
    """
    if first_name is None:
        return None
    try:
        return normalize_claimant_name(first_name, config_path=config_path)
    except ValueError:
        return None


def detect_claimant_from_text(text: str, *, config_path: Path | None = None) -> str | None:
    """Return the configured claimant referenced in a UHC detail page, if any."""
    return resolve_claimant_marker(
        extract_claimant_first_name_from_text(text), config_path=config_path
    )
