from contextlib import redirect_stderr
import io
import os
from pathlib import Path
import tempfile
import unittest
import sys
import types

sys.modules.setdefault("fitz", types.SimpleNamespace())

import src.eob_parser as eob_parser
from src.config import detect_claimant_from_text, normalize_claimant_name, resolve_claimant_marker
from src.eob_parser import ParsedClaim, VerificationError, _verify_total, parse_eob
from src.storage.models import extract_uhc_claim_number


class EobParserTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_claimant_config = os.environ.get("OCA_CLAIMANT_CONFIG")
        self.claimant_config = Path(self.tmpdir.name) / "claimants.toml"
        self.claimant_config.write_text(
            "[claimants]\nallowed = [\n  \"Alex Example\",\n  \"Blair Example\",\n]\n"
        )
        os.environ["OCA_CLAIMANT_CONFIG"] = str(self.claimant_config)

    def tearDown(self):
        if self.original_claimant_config is None:
            os.environ.pop("OCA_CLAIMANT_CONFIG", None)
        else:
            os.environ["OCA_CLAIMANT_CONFIG"] = self.original_claimant_config
        self.tmpdir.cleanup()

    def test_verify_total_raises_on_mismatch(self):
        claims = [
            ParsedClaim("FN1", "Provider A", "2026-01-01", 10.0, [1]),
            ParsedClaim("FN2", "Provider B", "2026-01-02", 5.0, [2]),
        ]

        with self.assertRaises(VerificationError):
            _verify_total("sample.pdf", 20.0, claims)

    def test_extract_uhc_claim_number_reads_legacy_note(self):
        self.assertEqual(
            extract_uhc_claim_number("Paid already. UHC Claim FN1234567890 extra text"),
            "FN1234567890",
        )

    def test_detect_claimant_from_text_uses_first_name_alias(self):
        self.assertEqual(
            detect_claimant_from_text("Claim detail for ALEX\nClaim number: FN123"),
            "Alex Example",
        )

    def test_detect_claimant_from_text_returns_none_for_unconfigured_member(self):
        self.assertIsNone(
            detect_claimant_from_text("Claim detail for CHARLIE\nClaim number: FN123")
        )

    def test_parse_eob_warns_when_claimant_marker_is_unconfigured(self):
        class FakePage:
            def __init__(self, text):
                self._text = text

            def get_text(self):
                return self._text

        class FakeDoc:
            def __init__(self, pages):
                self._pages = [FakePage(text) for text in pages]

            def __len__(self):
                return len(self._pages)

            def __getitem__(self, idx):
                return self._pages[idx]

            def close(self):
                return None

        original_open = getattr(eob_parser.fitz, "open", None)
        eob_parser.fitz.open = lambda _: FakeDoc([
            "Your total amount owed\n$10.00",
            "Claim detail for CHARLIE\nProvider: Example Provider\nClaim number: FN123",
        ])
        try:
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                total_owed, oop_claims, all_claims = parse_eob("sample.pdf")
        finally:
            if original_open is None:
                delattr(eob_parser.fitz, "open")
            else:
                eob_parser.fitz.open = original_open

        self.assertEqual(total_owed, 10.0)
        self.assertEqual(oop_claims, [])
        self.assertEqual(all_claims, [])
        self.assertIn("claimant marker 'CHARLIE' is unconfigured or ambiguous", stderr.getvalue())

    def test_resolve_claimant_marker_handles_none_unknown_and_known(self):
        self.assertIsNone(resolve_claimant_marker(None))
        self.assertIsNone(resolve_claimant_marker("CHARLIE"))
        self.assertEqual(resolve_claimant_marker("ALEX"), "Alex Example")

    def test_normalize_claimant_name_accepts_full_name_case_insensitively(self):
        self.assertEqual(
            normalize_claimant_name("ALEX EXAMPLE"),
            "Alex Example",
        )


if __name__ == "__main__":
    unittest.main()
