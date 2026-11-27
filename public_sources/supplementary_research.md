# Supplementary public evidence index

This additive research utility consumes the output of `scripts/recover_public_documents.py` and builds a searchable, provenance-linked index. It does not alter the original retrieval scripts, existing workflows, or any production system. Inputs must contain public source URLs and public labels only.

## Local use

```sh
python3 scripts/index_public_evidence.py --evidence-root evidence --output evidence/index
```

`documents.jsonl` links every indexed document to its original URL, source SHA-256, extraction SHA-256, retrieval record, and page extraction. `pages.jsonl` retains exact extracted text and its page locator, plus a Unicode NFKC and whitespace-normalized search projection. The projection does not convert units, interpret ranges, assign device identity, or establish engineering suitability. Review numerical values, table alignment, symbols, model boundaries, and interface details against the original document.

The indexer checks original bytes, retrieval records, and page extraction against the retriever's checksum manifest. A mismatch excludes the document and returns a nonzero exit status. These checks establish internal artifact consistency, not publisher authenticity. A hash does not establish that a public page is authoritative, current, correct, or a complete datasheet.

`summary.json` records successful, blocked, unsuccessful, and integrity-error outcomes. `INDEX_SHA256_MANIFEST.json` hashes the three index outputs. The original retrieval manifest remains untouched. Access errors remain evidence of access results only. The program makes no network requests and performs no engineering acceptance or identity reconciliation.

## Validation

```sh
python3 -m unittest discover -s tests -v
```

Tests use synthetic bytes and example URLs. They check source-hash integrity, extraction integrity, page locator preservation, Unicode projection, unsuccessful retrieval handling, restricted input fields, and path containment.

No confidential files, reconciliation records, internal identifiers, credentials, or unpublished conclusions may be added to a public source manifest or uploaded as public workflow artifacts. Schema checks and identifier heuristics supplement human input review; they cannot prove that arbitrary text is public.
