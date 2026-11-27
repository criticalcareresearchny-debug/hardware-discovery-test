# Public response content audit

`scripts/audit_public_evidence.py` runs after the existing retriever and provenance indexer. It distinguishes preserved HTTP responses from source text suitable for human review. It makes no decisions about product identity, novelty, publisher authority, numerical correctness, acquisition status, or engineering acceptance.

```sh
python3 scripts/audit_public_evidence.py --evidence-root evidence --output evidence/content_audit
```

The evidence root may be one retrieval artifact or a directory containing separate shard artifacts. Original payloads, retrieval records, extracted pages, and their checksum manifests remain unchanged. The audit verifies those checksums before examining content. It flags soft error/access pages, static JavaScript placeholders, PDF/image URLs returning another media type, nearly empty extraction, and suspicious text decoding. Original images remain available for visual review; no OCR or numerical interpretation is performed.

Gzip-compressed response bodies can be decoded into separate derived files with original and derived SHA-256 values. JavaScript files are preserved as source text and are never executed. Content flags are review aids; a lack of flags does not certify that a document is authoritative, current, complete, or appropriate for a particular engineering claim.

Optional public-source observations can mark manually observed extraction limitations. Their schema uses only public source URLs, generic flags, and text-extraction notes. Do not include private records or research judgments.

Outputs include `url_hash_manifest.json`, `content_audit_summary.json`, and `AUDIT_SHA256_MANIFEST.json`. The URL manifest records transport results, source hashes, readable-text availability, relative artifact paths, and extraction limitations. The summary reports counts and identifies byte-identical payloads across URLs without equating the associated products.

The source-only follow-up workflow is additive. It retains the earlier 188-URL manifest and original workflows without modification. Institutional manuscripts with personal-use-only distribution terms are excluded from public artifact retrieval. Public metadata can still be reviewed independently.
