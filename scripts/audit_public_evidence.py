#!/usr/bin/env python3
"""Separate transport success from readable source evidence, without acceptance.

Inputs are public retrieval artifacts only. Original bytes and extraction files
are never modified. Content flags are conservative review aids, not decisions
about publisher authority, product identity, engineering suitability, or novelty.
Gzip bodies and JavaScript source text can be decoded as separate derived files;
scripts are never executed. Every derivation retains the original payload hash.
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from index_public_evidence import load_manifest, read_json, relative_file, sha256, validate_source, verify_file, write_json

MAX_DECODED_BYTES = 40 * 1024 * 1024
ERROR_TITLE = re.compile(r"\b(?:404|403|page not found|not found|access denied|forbidden|just a moment|attention required|verify (?:you|your)|human verification|security check)\b", re.I)
ERROR_BODY = re.compile(r"\b(?:please (?:enable javascript and cookies|verify (?:you are|that you are) human)|checking your browser|access to this (?:page|site) has been denied)\b", re.I)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif", ".tiff"}


class VisibleHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.in_title = False
        self.text = []
        self.title = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden += 1
        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden = max(0, self.hidden - 1)
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)
        if not self.hidden and data.strip():
            self.text.append(data.strip())


def is_image(raw: bytes) -> bool:
    return (raw.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a", b"II*\0", b"MM\0*"))
            or (raw.startswith(b"RIFF") and raw[8:12] == b"WEBP"))


def decode_gzip(raw: bytes) -> bytes:
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        decoded = stream.read(MAX_DECODED_BYTES + 1)
    if len(decoded) > MAX_DECODED_BYTES:
        raise ValueError("Decoded payload exceeds bounded maximum")
    return decoded


def unusual_text_fraction(text: str) -> float:
    return sum((ord(c) < 32 and c not in "\t\n\r") or c == "\ufffd" for c in text) / max(1, len(text))


def content_flags(url: str, title: str, text: str, raw: bytes) -> list[str]:
    flags = []
    suffix = Path(urlsplit(url).path).suffix.lower()
    if ERROR_TITLE.search(title) or (len(text) < 8000 and ERROR_BODY.search(text)):
        flags.append("ERROR_OR_ACCESS_PAGE")
    if title.strip().casefold() in {"product name", "item name"} and "This is a description of the item" in text:
        flags.append("JAVASCRIPT_PLACEHOLDER")
    if suffix == ".pdf" and not raw.startswith(b"%PDF-"):
        flags.append("PDF_URL_RETURNED_OTHER_MEDIA")
    if suffix in IMAGE_EXTENSIONS and not is_image(raw):
        flags.append("IMAGE_URL_RETURNED_OTHER_MEDIA")
    if unusual_text_fraction(text) > 0.02:
        flags.append("EXTRACTION_ENCODING_SUSPECT")
    if not text.strip():
        flags.append("NO_EXTRACTED_TEXT")
    elif len(text.strip()) < 120:
        flags.append("VERY_LITTLE_EXTRACTED_TEXT")
    return flags


def review_class(flags: list[str], raw: bytes) -> str:
    if "ERROR_OR_ACCESS_PAGE" in flags:
        return "ERROR_OR_ACCESS_PAGE"
    if "JAVASCRIPT_PLACEHOLDER" in flags:
        return "PLACEHOLDER_PAGE"
    if "PDF_URL_RETURNED_OTHER_MEDIA" in flags or "IMAGE_URL_RETURNED_OTHER_MEDIA" in flags:
        return "UNEXPECTED_MEDIA"
    if is_image(raw):
        return "IMAGE_REQUIRES_VISUAL_REVIEW"
    if "PDF_FONT_MAPPING_GARBLED" in flags:
        return "PDF_REQUIRES_VISUAL_REVIEW"
    if any(f in flags for f in ("EXTRACTION_ENCODING_SUSPECT", "NO_EXTRACTED_TEXT", "VERY_LITTLE_EXTRACTED_TEXT")):
        return "NO_USABLE_TEXT"
    if "GZIP_DECODED_SEPARATELY" in flags:
        return "TEXT_AVAILABLE_AFTER_DECODING"
    if "JAVASCRIPT_SOURCE_NOT_EXECUTED" in flags:
        return "SOURCE_CODE_AVAILABLE_FOR_REVIEW"
    return "TEXT_AVAILABLE_FOR_REVIEW"


def audit(root: Path, output: Path, observations: dict | None = None) -> dict:
    root, output = root.resolve(), output.resolve()
    if root == output:
        raise ValueError("Use a separate output directory")
    output.mkdir(parents=True, exist_ok=True)
    roots = [root] if (root / "SHA256_MANIFEST.json").is_file() else [
        p for p in sorted(root.iterdir()) if p.is_dir() and (p / "SHA256_MANIFEST.json").is_file()
    ]
    if not roots:
        raise ValueError("No retrieval checksum manifests found")
    observations = observations or {}
    rows, receipts = [], []
    for evidence in roots:
        manifest, manifest_digest = load_manifest(evidence)
        run_path = evidence / "run_metadata.json"
        if run_path.exists():
            verify_file(evidence, "run_metadata.json", manifest)
            receipts.append({"directory": evidence.relative_to(root).as_posix(), "manifest_sha256": manifest_digest, "run_metadata": read_json(run_path)})
        for record_path in sorted(evidence.glob("documents/*/record.json")):
            row = {"record_path": record_path.relative_to(root).as_posix(), "review_class": "INTEGRITY_ERROR", "flags": []}
            try:
                verify_file(evidence, record_path.relative_to(evidence).as_posix(), manifest)
                record = read_json(record_path)
                validate_source(record["source"])
                url = record["source"]["url"]
                row.update(url=url, retrieval_outcome=record["outcome"], http_status=record.get("http_status"), final_url=record.get("final_url"))
                if record["outcome"] != "RETRIEVED":
                    row.update(review_class="NOT_RETRIEVED", retrieval_error=record.get("error"), robots_checks=record.get("robots_checks"))
                    rows.append(row)
                    continue
                payload = relative_file(evidence, record["payload"])
                digest = verify_file(evidence, record["payload"], manifest)
                if digest != record["sha256"]:
                    raise ValueError("Payload digest disagrees with retrieval record")
                raw = payload.read_bytes()
                page_path = (record_path.parent / "pages.json").relative_to(evidence).as_posix()
                verify_file(evidence, page_path, manifest)
                pages = read_json(evidence / page_path)
                text = "\n".join(p["text"] for p in pages)
                title = record.get("title") or ""
                flags = []
                original_encoding_fraction = unusual_text_fraction(text)
                derived = None
                if raw.startswith(b"\x1f\x8b"):
                    decoded = decode_gzip(raw)
                    parser = VisibleHTML()
                    parser.feed(decoded.decode("utf-8", "replace"))
                    text = "\n".join(parser.text)
                    title = " ".join(parser.title).strip()
                    directory = output / "derived" / sha256(url.encode())[:20]
                    directory.mkdir(parents=True, exist_ok=True)
                    (directory / "decoded.html").write_bytes(decoded)
                    (directory / "decoded_text.txt").write_text(text, encoding="utf-8")
                    derived = {"method": "gzip decompression and standard-library visible HTML extraction", "original_sha256": digest,
                               "decoded_payload": (directory / "decoded.html").relative_to(output).as_posix(), "decoded_sha256": sha256(decoded),
                               "text_path": (directory / "decoded_text.txt").relative_to(output).as_posix(), "text_sha256": sha256(text.encode())}
                    flags.append("GZIP_DECODED_SEPARATELY")
                elif not text.strip() and ("javascript" in record.get("content_type", "").lower() or Path(urlsplit(url).path).suffix.lower() == ".js"):
                    text = raw.decode("utf-8", "replace")
                    directory = output / "derived" / sha256(url.encode())[:20]
                    directory.mkdir(parents=True, exist_ok=True)
                    (directory / "source_text.txt").write_text(text, encoding="utf-8")
                    derived = {"method": "UTF-8 source decoding; JavaScript not executed", "original_sha256": digest,
                               "text_path": (directory / "source_text.txt").relative_to(output).as_posix(), "text_sha256": sha256(text.encode())}
                    flags.append("JAVASCRIPT_SOURCE_NOT_EXECUTED")
                flags.extend(content_flags(url, title, text, raw))
                observation = observations.get(url, {})
                flags.extend(observation.get("flags", []))
                limits = []
                if raw.startswith(b"%PDF-"):
                    limits.append("PDF layout extraction is unverified; inspect original tables, symbols, page numbers, and rendering")
                elif is_image(raw):
                    limits.append("Original image preserved; no OCR or numerical transcription performed")
                else:
                    limits.append("Static text may omit JavaScript data, images, and interactions")
                if record.get("extraction_error"):
                    limits.append(record["extraction_error"])
                if observation.get("note"):
                    limits.append(observation["note"])
                row.update(
                    review_class=review_class(flags, raw), flags=sorted(set(flags)), source_sha256=digest,
                    payload_path=payload.relative_to(root).as_posix(), bytes=len(raw), content_type=record.get("content_type"),
                    title=title or None, pdf_page_count=record.get("pdf_page_count"), extracted_page_count=len(pages),
                    extracted_text_chars=len(text), original_unusual_text_fraction=original_encoding_fraction,
                    extraction_limitations=limits, derived=derived, engineering_acceptance_performed=False,
                )
            except (OSError, ValueError, TypeError, KeyError) as exc:
                row["error"] = type(exc).__name__ + ": " + str(exc)
            rows.append(row)
    rows.sort(key=lambda row: row.get("url", row["record_path"]))
    duplicates = defaultdict(list)
    for row in rows:
        if row.get("source_sha256"):
            duplicates[row["source_sha256"]].append(row["url"])
    summary = {
        "schema_version": "public-content-audit-v1", "created_utc": datetime.now(timezone.utc).isoformat(),
        "script_sha256": sha256(Path(__file__).read_bytes()), "source_count": len(rows),
        "retrieval_outcomes": dict(Counter(r.get("retrieval_outcome", "UNKNOWN") for r in rows)),
        "review_classes": dict(Counter(r["review_class"] for r in rows)),
        "content_flag_counts": dict(Counter(f for r in rows for f in r["flags"])),
        "identical_payload_groups": [{"sha256": digest, "urls": urls} for digest, urls in sorted(duplicates.items()) if len(urls) > 1],
        "scope": "Transport/content review only; no authority, identity, novelty, acquisition, or engineering acceptance decision",
        "interpretation": "Text availability is not a valid engineering citation until source authority, exact model, and claim are reviewed",
        "engineering_acceptance_performed": False, "retrieval_receipts": receipts,
    }
    write_json(output / "url_hash_manifest.json", rows)
    write_json(output / "content_audit_summary.json", summary)
    files = [{"path": p.relative_to(output).as_posix(), "bytes": p.stat().st_size, "sha256": sha256(p.read_bytes())}
             for p in sorted(output.rglob("*")) if p.is_file() and p.name != "AUDIT_SHA256_MANIFEST.json"]
    write_json(output / "AUDIT_SHA256_MANIFEST.json", files)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--observations", type=Path)
    args = parser.parse_args()
    summary = audit(args.evidence_root, args.output, read_json(args.observations) if args.observations else None)
    print(json.dumps({key: summary[key] for key in ("source_count", "retrieval_outcomes", "review_classes", "content_flag_counts")}))
    return 1 if summary["review_classes"].get("INTEGRITY_ERROR") else 0


if __name__ == "__main__":
    raise SystemExit(main())
