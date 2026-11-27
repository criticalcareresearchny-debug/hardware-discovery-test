#!/usr/bin/env python3
"""Index retrieved public documents without deciding engineering acceptance.

Run after recover_public_documents.py. Every indexed source retains its exact
source URL, document SHA-256, original page text, and page locator. Unicode NFKC
and whitespace normalization create a search aid only. No units are converted,
device identity inferred, availability certified, or engineering value accepted.

Only documents whose bytes and page extraction match the retrieval manifest are
indexed. Failed retrievals remain in the audit summary. This program makes no
network requests and accepts no reconciliation workbook or identity register.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

SOURCE_KEYS = {"manufacturer", "model", "url", "document_hint", "language"}
PRIVATE_MARKERS = re.compile(
    r"\bIN\d{4,}\b|RESEARCH_STAGING|AUTHORITATIVE|library_file_id|file_0000", re.I
)
SCHEMA_VERSION = "public-evidence-index-v1"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_url_for_search(url: str) -> str:
    """Normalize hostname/scheme and omit the fragment; retain query order."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Source URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ValueError("Source URL must not contain credentials")
    host = parsed.hostname.lower()
    if ":" in host:
        host = "[" + host + "]"
    port = parsed.port
    if port is not None and not (
        (parsed.scheme == "http" and port == 80)
        or (parsed.scheme == "https" and port == 443)
    ):
        host += ":" + str(port)
    return urlunsplit((parsed.scheme.lower(), host, parsed.path or "/", parsed.query, ""))


def search_text(text: str) -> str:
    """Search projection only: preserve original text alongside this value."""
    return " ".join(unicodedata.normalize("NFKC", text).split())


def relative_file(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not name:
        raise ValueError("Expected a nonempty relative artifact path")
    path = Path(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Artifact path escapes the evidence root")
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("Artifact symlink escapes the evidence root")
    if not resolved.is_file():
        raise ValueError("Referenced artifact file is absent")
    return resolved


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def verify_file(root: Path, rel: str, manifest: dict) -> str:
    path = relative_file(root, rel)
    expected = manifest.get(rel)
    if not expected or not isinstance(expected, dict):
        raise ValueError("File is absent from the retrieval checksum manifest: " + rel)
    raw = path.read_bytes()
    digest = sha256(raw)
    if len(raw) != expected.get("bytes") or digest != expected.get("sha256"):
        raise ValueError("Retrieval checksum mismatch: " + rel)
    return digest


def load_manifest(root: Path) -> tuple[dict, str]:
    path = root / "SHA256_MANIFEST.json"
    raw = path.read_bytes()
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("Expected an array in retrieval checksum manifest")
    manifest = {}
    for entry in data:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ValueError("Malformed checksum manifest entry")
        if entry["path"] in manifest:
            raise ValueError("Duplicate path in checksum manifest")
        manifest[entry["path"]] = entry
    return manifest, sha256(raw)


def validate_source(source: dict) -> None:
    if not isinstance(source, dict) or set(source) - SOURCE_KEYS or not source.get("url"):
        raise ValueError("Unexpected public source schema")
    if any(not isinstance(v, str) for v in source.values()):
        raise ValueError("Public source fields must be strings")
    if PRIVATE_MARKERS.search(json.dumps(source, ensure_ascii=False)):
        raise ValueError("Private identifier guard rejected source labels")
    canonical_url_for_search(source["url"])


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_index(root: Path, output: Path) -> dict:
    root, output = root.resolve(), output.resolve()
    if output == root:
        raise ValueError("Output must be a separate directory, not the evidence root")
    output.mkdir(parents=True, exist_ok=True)
    manifest, manifest_digest = load_manifest(root)
    records = sorted(root.glob("documents/*/record.json"))
    documents, pages, audit = [], [], []
    for record_path in records:
        rel_record = record_path.relative_to(root).as_posix()
        status = {"record_path": rel_record, "index_status": "ERROR"}
        try:
            record_digest = verify_file(root, rel_record, manifest)
            record = read_json(record_path)
            source = record.get("source")
            validate_source(source)
            status.update(source_url=source["url"], retrieval_outcome=record.get("outcome"))
            if record.get("outcome") != "RETRIEVED":
                status["index_status"] = "RETRIEVAL_NOT_SUCCESSFUL"
                audit.append(status)
                continue
            payload_rel = record.get("payload")
            payload_digest = verify_file(root, payload_rel, manifest)
            if payload_digest != record.get("sha256"):
                raise ValueError("Payload digest disagrees with retrieval record")
            pages_rel = (record_path.parent / "pages.json").relative_to(root).as_posix()
            pages_digest = verify_file(root, pages_rel, manifest)
            original_pages = read_json(relative_file(root, pages_rel))
            if not isinstance(original_pages, list):
                raise ValueError("Expected an array of extracted pages")
            document_id = sha256((source["url"] + "\0" + payload_digest).encode())
            page_rows = []
            for sequence, page in enumerate(original_pages, 1):
                if not isinstance(page, dict) or not isinstance(page.get("text"), str):
                    raise ValueError("Malformed extracted page")
                number = page.get("page_1_based")
                if number is not None and (type(number) is not int or number < 1):
                    raise ValueError("PDF page number must be a positive integer")
                page_rows.append({
                    "schema_version": SCHEMA_VERSION,
                    "document_id": document_id,
                    "source_url": source["url"],
                    "source_sha256": payload_digest,
                    "extraction_sha256": pages_digest,
                    "page_1_based": number,
                    "extraction_sequence_1_based": sequence,
                    "text_original": page["text"],
                    "text_for_search": search_text(page["text"]),
                    "interpretation": "UNREVIEWED_TRANSCRIPTION",
                })
            documents.append({
                "schema_version": SCHEMA_VERSION,
                "document_id": document_id,
                "source": source,
                "source_url_for_search": canonical_url_for_search(source["url"]),
                "retrieved_utc": record.get("retrieved_utc"),
                "final_url": record.get("final_url"),
                "source_sha256": payload_digest,
                "record_sha256": record_digest,
                "extraction_sha256": pages_digest,
                "payload_path": payload_rel,
                "record_path": rel_record,
                "pages_path": pages_rel,
                "page_count": len(page_rows),
                "extraction_note": record.get("extraction_note"),
                "extraction_error": record.get("extraction_error"),
                "interpretation": "RETRIEVED_DOCUMENT_REQUIRING_REVIEW",
            })
            pages.extend(page_rows)
            index_status = "INDEXED" if any(p["text_original"].strip() for p in page_rows) else "INDEXED_NO_TEXT"
            status.update(index_status=index_status, document_id=document_id, page_count=len(page_rows))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            status["error"] = type(exc).__name__ + ": " + str(exc)
        audit.append(status)
    if not records:
        audit.append({"index_status": "ERROR", "error": "No retrieval records found"})
    documents.sort(key=lambda row: row["document_id"])
    pages.sort(key=lambda row: (row["document_id"], row["extraction_sequence_1_based"]))
    for filename, rows in (("documents.jsonl", documents), ("pages.jsonl", pages)):
        with (output / filename).open("w", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    counts = dict(Counter(row["index_status"] for row in audit))
    summary = {
        "schema_version": SCHEMA_VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "script_sha256": sha256(Path(__file__).read_bytes()),
        "retrieval_manifest_sha256": manifest_digest,
        "record_count": len(records),
        "indexed_document_count": len(documents),
        "indexed_page_count": len(pages),
        "status_counts": counts,
        "engineering_acceptance_performed": False,
        "normalization": "Unicode NFKC plus whitespace collapse; original text retained; no unit conversion",
        "manifest_assurance": "Checks internal artifact consistency; does not authenticate the publisher",
        "source_label_guard": "Heuristic rejection only; public-only input review remains required",
        "github": {key: os.getenv(key) for key in ("GITHUB_REPOSITORY", "GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")},
        "audit": audit,
    }
    write_json(output / "summary.json", summary)
    index_manifest = [
        {"path": name, "bytes": (output / name).stat().st_size, "sha256": sha256((output / name).read_bytes())}
        for name in ("documents.jsonl", "pages.jsonl", "summary.json")
    ]
    write_json(output / "INDEX_SHA256_MANIFEST.json", index_manifest)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        summary = build_index(args.evidence_root, args.output)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"index_status": "ERROR", "error": type(exc).__name__ + ": " + str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps({key: summary[key] for key in ("indexed_document_count", "indexed_page_count", "status_counts", "engineering_acceptance_performed")}))
    return 1 if summary["status_counts"].get("ERROR") else 0


if __name__ == "__main__":
    raise SystemExit(main())
