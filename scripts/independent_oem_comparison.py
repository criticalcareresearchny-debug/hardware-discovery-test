#!/usr/bin/env python3
"""One-off, public-OEM catalogue discovery experiment (NOT a Master importer).

Uses Python standard library only. The catalogue seeds are public company pages,
not Master extracts, model lists, or unpublished research. No payment, tokens,
workbook reads/writes, bulk crawling, or automatically certified components.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

SEEDS = [
    ("Analog Devices", "United States", "North America",
     "https://www.analog.com/en/product-category/accelerometers.html"),
    ("STMicroelectronics", "Europe", "Europe",
     "https://www.st.com/en/mems-and-sensors/inemo-inertial-modules/products.html"),
    ("ROHM", "Japan", "East Asia",
     "https://www.rohm.com/products/sensors-mems"),
    ("Mindgrove", "India", "South Asia",
     "https://www.mindgrovetech.in/"),
    ("Cytron", "Malaysia", "Southeast Asia",
     "https://my.cytron.io/cytron-industry"),
    ("VIBSENS", "Türkiye", "West Asia",
     "https://www.vibsens.com/"),
    ("OrionM2M", "Kazakhstan", "Central Asia",
     "https://orionm2m.kz/"),
    ("OWEN", "Russia", "North Asia",
     "https://owen.ru/"),
    ("ROBOTIS", "South Korea", "East Asia",
     "https://en.robotis.com/"),
    ("Seeed Studio", "China", "East Asia",
     "https://www.seeedstudio.com/"),
]
# This is a limited test sample, NOT a limit on the research programme.
MAX_CHILD_PAGES_PER_OEM = 3
MAX_CATALOG_BYTES = 700_000
MAX_PRODUCT_BYTES = 320_000
MAX_ROBOTS_BYTES = 120_000
MAX_TEST_SECONDS = 220  # stricter than workflow's 5-minute hard timeout
HTTP_TIMEOUT = 6
AGENT = "PublicOEMComparisonResearch/1.0 (+https://github.com/criticalcareresearchny-debug/hardware-discovery-test)"
HEADERS = {"User-Agent": AGENT, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5"}
ROBOT_CACHE = {}
START = time.monotonic()
# International model-code tokens, including Cyrillic; never treated as proof of identity.
TOKEN_RE = re.compile(r"(?<![A-ZА-ЯЁ0-9])([A-ZА-ЯЁ][A-ZА-ЯЁ0-9-]{3,23})(?![A-ZА-ЯЁ0-9])")
BLOCKED = {"HTML5", "UTF-8", "ISO9001", "COVID19", "HTTP404", "2026", "720P", "1080P"}
SPECS_RE = re.compile(r"(?<!\w)\d+(?:\.\d+)?\s*(?:µA|μA|mA|uA|V|mV|W|mW|kHz|MHz|Hz|°C|rpm|dps)(?!\w)", re.I)


class PublicPage(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text = []
        self.links = []
        self.anchor = None
        self.hidden = None
        self.title_mode = False
        self.title = []
        self.visible_chars = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in ("script", "style", "svg", "noscript"):
            self.hidden = tag
        if self.hidden:
            return
        if tag == "title":
            self.title_mode = True
        if tag == "a":
            properties = dict(attrs)
            self.anchor = [properties.get("href", ""), []]

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == self.hidden:
            self.hidden = None
            return
        if tag == "title":
            self.title_mode = False
        if tag == "a" and self.anchor:
            self.links.append((self.anchor[0], " ".join(self.anchor[1]).strip()))
            self.anchor = None

    def handle_data(self, data):
        if self.hidden:
            return
        value = " ".join(data.split())
        if not value:
            return
        if self.anchor:
            self.anchor[1].append(value)
        if self.title_mode:
            self.title.append(value)
        if self.visible_chars < 95_000:
            self.text.append(value)
            self.visible_chars += len(value) + 1


def domain(url):
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def same_company_site(a, b):
    aa, bb = domain(a), domain(b)
    return aa == bb or aa.endswith("." + bb) or bb.endswith("." + aa)


def request(url, byte_limit):
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=HTTP_TIMEOUT) as response:
        data = response.read(byte_limit + 1)
        return response.status, response.geturl(), response.headers.get("Content-Type", ""), data[:byte_limit]


def robots_permit(url):
    host = urlparse(url).netloc
    if host in ROBOT_CACHE:
        rp, reason = ROBOT_CACHE[host]
        return (rp.can_fetch(AGENT, url), reason) if rp else (False, reason)
    robots = urlparse(url).scheme + "://" + host + "/robots.txt"
    try:
        status, _, typ, payload = request(robots, MAX_ROBOTS_BYTES)
        rp = RobotFileParser()
        rp.parse(payload.decode("utf-8", "replace").splitlines())
        ROBOT_CACHE[host] = (rp, "robots.txt read")
        return rp.can_fetch(AGENT, url), "robots.txt read"
    except HTTPError as exc:
        if exc.code in (404, 410):
            rp = RobotFileParser()
            rp.parse([])
            ROBOT_CACHE[host] = (rp, "robots.txt absent (404/410)")
            return True, "robots.txt absent (404/410)"
        ROBOT_CACHE[host] = (None, "robots.txt HTTP " + str(exc.code))
        return False, "robots.txt HTTP " + str(exc.code)
    except (OSError, ValueError, TimeoutError, URLError) as exc:
        ROBOT_CACHE[host] = (None, "robots.txt unavailable (" + type(exc).__name__ + ")")
        return False, "robots.txt unavailable (" + type(exc).__name__ + ")"


def page(url, limit):
    allowed, robots = robots_permit(url)
    if not allowed:
        return {"outcome": "SKIPPED_ROBOTS", "robots": robots}
    try:
        status, final, typ, body = request(url, limit)
        if not same_company_site(final, url):
            return {"outcome": "CROSS_DOMAIN_REDIRECT", "robots": robots, "final": final}
        if "html" not in typ.lower():
            return {"outcome": "NOT_HTML", "robots": robots, "content_type": typ}
        parsed = PublicPage()
        parsed.feed(body.decode("utf-8", "replace"))
        return {"outcome": "HTML_OK", "robots": robots, "url": final,
                "bytes": len(body), "parser": parsed}
    except (HTTPError, URLError, OSError, TimeoutError, ValueError) as exc:
        return {"outcome": "FETCH_FAILED", "robots": robots,
                "error": str(exc)[:140]}


def model_codes(raw):
    found = []
    for m in TOKEN_RE.finditer(raw.upper()):
        token = m.group(1).strip("-")
        if (any(c.isdigit() for c in token)
                and any(c.isalpha() for c in token)
                and token not in BLOCKED and len(token) >= 5):
            found.append(token)
    return found


def candidate_links(seed_url, parser):
    unique = {}
    for href, anchor in parser.links:
        if not href or href.startswith(("#", "mailto:", "javascript:")):
            continue
        url = urljoin(seed_url, href.split("#", 1)[0])
        if urlparse(url).scheme != "https" or not same_company_site(seed_url, url):
            continue
        # Prefer model-bearing link titles; link paths can contain generic version tokens.
        codes = model_codes(anchor)
        if not codes:
            continue
        for model in codes[:2]:
            key = (model, url.split("?", 1)[0])
            unique[key] = {"model": model, "url": key[1], "anchor": anchor[:130]}
    # Deterministic broad sampling across links, avoiding newest/first-page bias.
    ranked = sorted(unique.values(),
                    key=lambda x: hashlib.sha256(("S05-ONE-TEST-2026|" + x["model"] + "|" +
                                                  x["url"]).encode()).hexdigest())
    return len(unique), ranked[:MAX_CHILD_PAGES_PER_OEM]


def excerpt(text, model):
    m = re.search(r"(?<![A-ZА-ЯЁ0-9])" + re.escape(model) + r"(?![A-ZА-ЯЁ0-9])",
                  text, re.I)
    if not m:
        return ""
    return " ".join(text[max(0, m.start()-85):m.end()+150].split())[:240]


def public_record(oem, country, region, model, url, anchor, detail):
    result = {"type": "CANDIDATE", "maker": oem, "country": country, "region": region,
              "model_lead": model, "public_url": url, "catalogue_anchor": anchor,
              "page_outcome": detail["outcome"], "evidence_level": "E1_OEM_INDEX_LEAD",
              "do_not_assign_research_id": True}
    if detail["outcome"] == "HTML_OK":
        parser = detail["parser"]
        rendered = " ".join(parser.text)
        context = excerpt(rendered, model)
        result["oem_page_title"] = " ".join(parser.title)[:140]
        result["model_visible_on_page"] = bool(context)
        result["exact_page_excerpt"] = context
        result["example_measurement_tokens"] = list(dict.fromkeys(SPECS_RE.findall(
            rendered[max(0, rendered.upper().find(model)-250):
                     max(0, rendered.upper().find(model)-250)+1100])))[:8] if context else []
        if context:
            result["evidence_level"] = "E2_OEM_PAGE_TEXT_ONLY"
    elif detail.get("error"):
        result["error"] = detail["error"]
    result["page_outcome"] = detail["outcome"]
    return result


def main():
    print("S05 INDEPENDENT PUBLIC OEM CATALOGUE EXPERIMENT; NO PRIVATE DATA OR MASTER")
    print("start_utc:", datetime.now(timezone.utc).isoformat(), flush=True)
    all_records, overview = [], []
    for oem, country, region, url in SEEDS:
        if time.monotonic() - START > MAX_TEST_SECONDS - 20:
            print(json.dumps({"type": "STOP", "reason": "global runtime budget"}, ensure_ascii=False))
            break
        source = page(url, MAX_CATALOG_BYTES)
        item = {"type": "OEM_CATALOGUE", "maker": oem, "country": country,
                "region": region, "source_url": url, "outcome": source["outcome"],
                "robots": source.get("robots", "")}
        if source.get("error"):
            item["error"] = source["error"]
        if source["outcome"] == "HTML_OK":
            pool_count, sample = candidate_links(url, source["parser"])
            item["candidate_links_in_index"] = pool_count
            item["sampled"] = len(sample)
            item["html_bytes"] = source["bytes"]
            for candidate in sample:
                if time.monotonic() - START > MAX_TEST_SECONDS - 12:
                    break
                time.sleep(0.25)
                detail = page(candidate["url"], MAX_PRODUCT_BYTES)
                result = public_record(oem, country, region, candidate["model"],
                                       candidate["url"], candidate["anchor"], detail)
                all_records.append(result)
                print(json.dumps(result, ensure_ascii=False), flush=True)
        overview.append(item)
        print(json.dumps(item, ensure_ascii=False), flush=True)

    seconds = round(time.monotonic() - START, 2)
    pages = [x for x in all_records if x["page_outcome"] == "HTML_OK"]
    exact = [x for x in all_records if x["evidence_level"] == "E2_OEM_PAGE_TEXT_ONLY"]
    spec = [x for x in exact if x.get("example_measurement_tokens")]
    regions = sorted({x["region"] for x in overview if x["outcome"] == "HTML_OK"})
    # A negative control: a fabricated model must not match real OEM excerpts.
    negative = "NO_SUCH_OEM_PART_987654"
    false_positive = any(negative in (x.get("exact_page_excerpt") or "") for x in all_records)
    metrics = {"type": "SUMMARY", "seconds": seconds,
               "catalogues_attempted": len(overview),
               "catalogues_accessible": sum(x["outcome"] == "HTML_OK" for x in overview),
               "candidate_links_in_accessible_indexes": sum(x.get("candidate_links_in_index",0) for x in overview),
               "candidate_pages_checked": len(all_records),
               "candidate_pages_retrieved": len(pages),
               "exact_model_visible_on_oem_page": len(exact),
               "exact_model_with_some_numeric_spec_tokens": len(spec),
               "regions_with_accessible_catalogues": regions,
               "negative_control_false_positive": false_positive,
               "confirmed_independent_new_master_components": 0,
               "reason": "No private Master accessible; public OEM model presence is not identity clearance or a primary datasheet audit"}
    print(json.dumps(metrics, ensure_ascii=False), flush=True)
    report = [
        "# One-off public OEM comparison: unverified discovery leads",
        "",
        "**This does not add anything to the research Master, assign Research IDs,",
        "validate C01–C32 labels, or certify a new independent physical unit.**",
        "",
        f"Executed: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"Python phase wall-clock: **{seconds} seconds**",
        "",
        "| Metric | Observed |",
        "|---|---:|",
        f"| Public OEM catalogue pages attempted | {metrics['catalogues_attempted']} |",
        f"| Public OEM catalogue pages accessible | {metrics['catalogues_accessible']} |",
        f"| Model-bearing catalogue links discovered | {metrics['candidate_links_in_accessible_indexes']} |",
        f"| Sampled candidate pages checked | {metrics['candidate_pages_checked']} |",
        f"| Pages with exact model text found on OEM site | {len(exact)} |",
        f"| Exact-model pages containing numerical spec tokens (not audited) | {len(spec)} |",
        f"| Independently certified new Master components | 0 |",
        "",
        "Accessible catalogue regions: " + (", ".join(regions) or "none"),
        "",
        "### OEM index attempts",
        "| OEM | Geography | Outcome | Model-bearing links found |",
        "|---|---|---|---:|",
    ]
    for x in overview:
        report.append(f"| {x['maker']} | {x['region']} | {x['outcome']} "
                      f"| {x.get('candidate_links_in_index',0)} |")
    report += ["", "### Public candidate leads (manual inspection required)",
               "| Maker | Model lead | OEM model-page result | Page |",
               "|---|---|---|---|"]
    for x in all_records:
        report.append(f"| {x['maker']} | {x['model_lead']} | {x['evidence_level']} "
                      f"| [OEM]({x['public_url']}) |")
    report += [
        "", "### Interpretation",
        "This experiment detects public OEM model-page leads and possible measurement tokens.",
        "Those are NOT verified device specifications. An engineer must examine exact-model",
        "primary documents, die/assembly/variant identity, C01–C32 and functions, regional origin,",
        "power/interface/dependencies, maturity and read-only Master overlap **outside this public repo**.",
        "No comprehensive worldwide coverage or discovery superiority is inferred from this narrow sample.",
        "No Master data, unpublished research rows, paid APIs or persistent artifacts used.",
    ]
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as stream:
            stream.write("\n".join(report) + "\n")


if __name__ == "__main__":
    main()
