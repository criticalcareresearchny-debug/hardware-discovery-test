#!/usr/bin/env python3
"""Small, read-only public OEM web-access test. No paid APIs, uploads or crawling."""
from __future__ import annotations

import html
import json
import os
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

SOURCES = [
    ("Sensirion (Switzerland)", "SHT45", "https://sensirion.com/products/catalog/SHT45"),
    ("STMicroelectronics (Europe)", "VL53L8CX", "https://www.st.com/en/imaging-and-photonics-solutions/vl53l8cx.html"),
    ("Analog Devices (USA)", "ADXL367", "https://www.analog.com/en/products/adxl367.html"),
    ("ROHM (Japan)", "BH1790GLC", "https://www.rohm.com/products/sensors-mems/optical-sensor-for-heart-rate-monitor/bh1790glc-product"),
]
USER_AGENT = "HardwareDiscoveryProofOfConcept/0.1 (+https://github.com/criticalcareresearchny-debug/hardware-discovery-test)"
HEADERS = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
MAX_PAGE_BYTES = 1_000_000
MAX_ROBOTS_BYTES = 250_000
NETWORK_TIMEOUT_SECONDS = 10


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title_parts = []
        self.description = ""
        self.visible_parts = []
        self.in_title = False
        self.skip_tag = None
        self.visible_chars = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if self.skip_tag:
            return
        if tag in {"script", "style", "svg", "noscript"}:
            self.skip_tag = tag
            return
        if tag == "title":
            self.in_title = True
        if tag == "meta":
            d = {k.lower(): (v or "") for k, v in attrs}
            if (d.get("name", "").lower() == "description"
                    or d.get("property", "").lower() == "og:description"):
                if not self.description:
                    self.description = d.get("content", "").strip()

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == self.skip_tag:
            self.skip_tag = None
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.skip_tag:
            return
        part = " ".join(data.split())
        if not part:
            return
        if self.in_title:
            self.title_parts.append(part)
        elif self.visible_chars < 80_000:
            self.visible_parts.append(part)
            self.visible_chars += len(part) + 1


def fetch(url, max_bytes):
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=NETWORK_TIMEOUT_SECONDS) as response:
        final_url = response.geturl()
        content_type = response.headers.get("Content-Type", "")
        data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            data = data[:max_bytes]
        return response.status, final_url, content_type, data


def allowed_by_robots(url):
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        _, _, _, raw = fetch(robots_url, MAX_ROBOTS_BYTES)
        rp = RobotFileParser()
        rp.parse(raw.decode("utf-8", errors="replace").splitlines())
        allowed = rp.can_fetch(USER_AGENT.split("/", 1)[0], url)
        return allowed, "robots.txt permits" if allowed else "robots.txt disallows"
    except HTTPError as exc:
        if exc.code in (404, 410):
            return True, f"robots.txt not found (HTTP {exc.code})"
        return False, f"robots.txt HTTP {exc.code}; skipped conservatively"
    except (OSError, URLError, ValueError) as exc:
        return False, f"robots.txt inaccessible ({type(exc).__name__}); skipped conservatively"


def check_source(maker, model, url):
    record = {"manufacturer": maker, "model": model, "url": url}
    allowed, reason = allowed_by_robots(url)
    record["robots"] = reason
    if not allowed:
        record["result"] = "SKIPPED_ROBOTS"
        return record
    try:
        status, final_url, content_type, raw = fetch(url, MAX_PAGE_BYTES)
        record["http"] = status
        record["final_url"] = final_url
        record["bytes_read"] = len(raw)
        if "html" not in content_type.lower():
            record["result"] = "REVIEW_CONTENT_TYPE"
            record["content_type"] = content_type
            return record
        p = PageText()
        p.feed(raw.decode("utf-8", errors="replace"))
        title = " ".join(p.title_parts).strip()
        text = " ".join(p.visible_parts)
        visible = " ".join([title, p.description, text])
        match = re.search(r"(?<![A-Z0-9])" + re.escape(model) + r"(?![A-Z0-9])",
                          visible, flags=re.IGNORECASE)
        record["title"] = title[:160]
        record["description"] = p.description[:240]
        record["model_visible"] = bool(match)
        if match:
            lo, hi = max(0, match.start() - 75), min(len(visible), match.end() + 140)
            record["evidence_excerpt"] = visible[lo:hi].strip()[:220]
            record["result"] = "MODEL_ON_OFFICIAL_PAGE"
        else:
            record["result"] = "REVIEW_MODEL_NOT_VISIBLE"
        return record
    except (HTTPError, URLError, OSError, TimeoutError, ValueError) as exc:
        record["result"] = "REQUEST_FAILED"
        record["error"] = f"{type(exc).__name__}: {str(exc)[:180]}"
        return record


def safe(text):
    return (html.escape(str(text), quote=False)
            .replace("|", "\\|").replace("\n", " ").replace("\r", " "))


def main():
    print("Public manufacturer-page test. No paid APIs, no Master, no files uploaded.")
    records = []
    for maker, model, url in SOURCES:
        result = check_source(maker, model, url)
        records.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        time.sleep(1.1)

    found = sum(r["result"] == "MODEL_ON_OFFICIAL_PAGE" for r in records)
    summary = [
        "# OEM internet-access smoke test",
        "",
        f"UTC run: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "",
        "Uses public manufacturer pages only; preliminary web evidence, **not** verified new Master entries.",
        "",
        "| Manufacturer | Model | Outcome | OEM page |",
        "|---|---|---|---|",
    ]
    for r in records:
        summary.append(
            f"| {safe(r['manufacturer'])} | {safe(r['model'])} | "
            f"{safe(r['result'])} | [Source]({r['url']}) |"
        )
    summary.extend(["", f"**Confirmed accessible OEM model pages: {found}/{len(records)}**", ""])
    for r in records:
        summary.append(f"### {safe(r['manufacturer'])} — {safe(r['model'])}")
        summary.append(f"- Robots check: {safe(r['robots'])}")
        if r.get("title"):
            summary.append(f"- Title: {safe(r['title'])}")
        if r.get("description"):
            summary.append(f"- Description: {safe(r['description'])}")
        if r.get("evidence_excerpt"):
            summary.append(f"- Visible model context: {safe(r['evidence_excerpt'])}")
        if r.get("error"):
            summary.append(f"- Error: {safe(r['error'])}")
        summary.append("")
    summary.append("No automatic classification, identity clearance, workbook changes or commits were performed.")
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(summary) + "\n")
    print(f"Completed: {found}/{len(records)} models found on their official manufacturer pages.")
    if found == 0:
        raise SystemExit("No model pages retrieved; inspect robots, HTTP results, or networking.")


if __name__ == "__main__":
    main()
