"""Synthetic provenance tests; no publisher data, network, or private inputs."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "index_public_evidence", Path(__file__).resolve().parents[1] / "scripts" / "index_public_evidence.py"
)
INDEX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INDEX)


class EvidenceIndexTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "evidence"
        self.document = self.root / "documents" / "synthetic"
        self.document.mkdir(parents=True)
        self.output = Path(self.temporary.name) / "index"
        self.payload = b"Synthetic document bytes; no publisher content."
        (self.document / "original.bin").write_bytes(self.payload)
        self.original_text = "Nominal  １２ µL\nRange: 2\u00a0–\u00a04 mL/min"
        (self.document / "pages.json").write_text(json.dumps([
            {"page_1_based": 3, "text": self.original_text}
        ]), encoding="utf-8")
        self.record = {
            "source": {"manufacturer": "Example", "model": "Sample", "url": "https://example.org/manual#page=3"},
            "outcome": "RETRIEVED",
            "payload": "documents/synthetic/original.bin",
            "sha256": hashlib.sha256(self.payload).hexdigest(),
            "retrieved_utc": "2000-01-01T00:00:00+00:00",
        }
        self.write_record()
        self.write_manifest()

    def tearDown(self):
        self.temporary.cleanup()

    def write_record(self):
        (self.document / "record.json").write_text(json.dumps(self.record), encoding="utf-8")

    def write_manifest(self):
        manifest = [
            {"path": p.relative_to(self.root).as_posix(), "bytes": p.stat().st_size,
             "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in sorted(self.document.iterdir())
        ]
        (self.root / "SHA256_MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_preserves_original_unicode_and_page_while_normalizing_search(self):
        summary = INDEX.build_index(self.root, self.output)
        self.assertEqual(summary["status_counts"], {"INDEXED": 1})
        row = json.loads((self.output / "pages.jsonl").read_text())
        self.assertEqual(row["text_original"], self.original_text)
        self.assertEqual(row["text_for_search"], "Nominal 12 μL Range: 2 – 4 mL/min")
        self.assertEqual(row["page_1_based"], 3)
        self.assertEqual(row["source_sha256"], self.record["sha256"])
        self.assertFalse(summary["engineering_acceptance_performed"])

    def test_rejects_tampered_payload(self):
        (self.document / "original.bin").write_bytes(b"modified")
        summary = INDEX.build_index(self.root, self.output)
        self.assertEqual(summary["status_counts"], {"ERROR": 1})
        self.assertEqual(summary["indexed_page_count"], 0)

    def test_rejects_tampered_page_extraction(self):
        (self.document / "pages.json").write_text("[]", encoding="utf-8")
        summary = INDEX.build_index(self.root, self.output)
        self.assertEqual(summary["status_counts"], {"ERROR": 1})
        self.assertEqual(summary["indexed_document_count"], 0)

    def test_rejects_record_digest_disagreement(self):
        self.record["sha256"] = "0" * 64
        self.write_record()
        self.write_manifest()
        summary = INDEX.build_index(self.root, self.output)
        self.assertEqual(summary["status_counts"], {"ERROR": 1})

    def test_retains_failed_retrieval_without_inventing_evidence(self):
        self.record["outcome"] = "HTTP_404"
        self.write_record()
        self.write_manifest()
        summary = INDEX.build_index(self.root, self.output)
        self.assertEqual(summary["status_counts"], {"RETRIEVAL_NOT_SUCCESSFUL": 1})
        self.assertEqual(summary["indexed_page_count"], 0)

    def test_rejects_path_traversal_and_extra_source_fields(self):
        with self.assertRaises(ValueError):
            INDEX.relative_file(self.root, "../outside")
        self.record["source"]["internal_join_key"] = "forbidden synthetic field"
        self.write_record()
        self.write_manifest()
        summary = INDEX.build_index(self.root, self.output)
        self.assertEqual(summary["status_counts"], {"ERROR": 1})

    def test_normalizes_only_url_scheme_host_default_port_and_fragment(self):
        url = "https://EXAMPLE.ORG:443/a?second=2&first=1#page=3"
        self.assertEqual(INDEX.canonical_url_for_search(url), "https://example.org/a?second=2&first=1")

    def test_output_cannot_overwrite_evidence_root(self):
        with self.assertRaises(ValueError):
            INDEX.build_index(self.root, self.root)


if __name__ == "__main__":
    unittest.main()
