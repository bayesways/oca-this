import json
import os
import tempfile
import unittest
from pathlib import Path

from src.storage import claims
from src.storage.models import Claim


class ClaimsMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.config_tmpdir = tempfile.TemporaryDirectory()
        self.original_data_dir = claims.DATA_DIR
        self.original_claims_dir = claims.CLAIMS_DIR
        self.original_index_file = claims.INDEX_FILE
        self.original_claimant_config = os.environ.get("OCA_CLAIMANT_CONFIG")

        claims.DATA_DIR = Path(self.tmpdir.name)
        claims.CLAIMS_DIR = claims.DATA_DIR / "claims"
        claims.INDEX_FILE = claims.DATA_DIR / "claims.json"
        claims._ensure_dirs()

        self.claimant_config = Path(self.config_tmpdir.name) / "claimants.toml"
        self.claimant_config.write_text(
            "[claimants]\nallowed = [\n  \"Alex Example\",\n  \"Blair Example\",\n]\n"
        )
        os.environ["OCA_CLAIMANT_CONFIG"] = str(self.claimant_config)

    def tearDown(self):
        claims.DATA_DIR = self.original_data_dir
        claims.CLAIMS_DIR = self.original_claims_dir
        claims.INDEX_FILE = self.original_index_file
        if self.original_claimant_config is None:
            os.environ.pop("OCA_CLAIMANT_CONFIG", None)
        else:
            os.environ["OCA_CLAIMANT_CONFIG"] = self.original_claimant_config
        self.tmpdir.cleanup()
        self.config_tmpdir.cleanup()

    def test_migrate_claims_rewrites_legacy_shape_explicitly(self):
        claim_id = "2026-01-25_001"
        claim_dir = claims.CLAIMS_DIR / claim_id
        claim_dir.mkdir(parents=True)
        (claim_dir / "receipts").mkdir()

        with open(claims.INDEX_FILE, "w") as f:
            json.dump({"claims": [claim_id]}, f)

        legacy_claim = {
            "id": claim_id,
            "type": "medical",
            "oca_status": "submitted",
            "oca_submitted_at": "2026-04-18T10:06:53.449236",
            "uhc_status": "processed",
            "uhc_submitted_at": None,
            "service_date": "2026-01-25",
            "amount": 42.0,
            "provider": "Provider",
            "claimant": "Alex Example",
            "notes": "UHC Claim FN1234567890",
        }
        with open(claims._get_claim_file(claim_id), "w") as f:
            json.dump(legacy_claim, f, indent=2)

        preview = claims.migrate_claims(dry_run=True)
        self.assertEqual(preview["migrated_claims"], 1)
        with open(claims._get_claim_file(claim_id)) as f:
            self.assertIn("oca_status", json.load(f))

        result = claims.migrate_claims()
        self.assertEqual(result["migrated_claims"], 1)
        with open(claims._get_claim_file(claim_id)) as f:
            migrated = json.load(f)

        self.assertEqual(migrated["source"], "uhc")
        self.assertEqual(migrated["status"], "submitted")
        self.assertEqual(migrated["submitted_at"], "2026-04-18T10:06:53.449236")
        self.assertEqual(migrated["source_claim_number"], "FN1234567890")
        self.assertNotIn("oca_status", migrated)
        self.assertNotIn("uhc_status", migrated)

    def test_set_status_preserves_submitted_at_when_demoted(self):
        claim = claims.create_claim(claim_type="medical")
        submitted = claims.set_status(claim.id, "submitted")
        first_submitted_at = submitted.submitted_at

        pending = claims.set_status(claim.id, "pending")
        self.assertEqual(pending.status, "pending")
        self.assertEqual(pending.submitted_at, first_submitted_at)

    def test_claim_is_ready_without_provider(self):
        claim = claims.create_claim(claim_type="medical")

        receipt_path = claims.CLAIMS_DIR / "receipt.pdf"
        receipt_path.write_text("placeholder receipt")
        claims.add_receipt(claim.id, str(receipt_path))

        claims.update_claim(
            claim.id,
            service_date="2026-05-10",
            amount=21.76,
        )

        ready_claims = claims.list_claims(ready=True)
        self.assertEqual([c["id"] for c in ready_claims], [claim.id])

    def test_create_claim_resolves_unique_first_name_alias(self):
        claim = claims.create_claim(claim_type="medical", claimant="Alex")
        self.assertEqual(claim.claimant, "Alex Example")

    def test_update_claim_rejects_unknown_claimant(self):
        claim = claims.create_claim(claim_type="medical")
        with self.assertRaises(ValueError):
            claims.update_claim(claim.id, claimant="Unknown Person")

    def test_claim_without_provider_counts_as_parsed(self):
        claim = Claim(
            id="2026-05-10_001",
            type="medical",
            service_date="2026-05-10",
            amount=21.76,
            provider=None,
        )

        self.assertTrue(claim.is_parsed())


if __name__ == "__main__":
    unittest.main()
