#!/usr/bin/env python3
"""Bounded public technical-document retrieval; no engineering acceptance logic.

Inputs contain public URLs and public product labels only. Raw documents are
temporary workflow artifacts, never committed. Robots denial and access errors
are recorded and not bypassed. PDF extraction preserves page numbering; extracted
tables/text remain unverified transcription requiring source inspection.
"""
from __future__ import annotations
import argparse, concurrent.futures, hashlib, ipaddress, json, os, re, shutil
import socket, sys, time, urllib.error, urllib.parse, urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.robotparser import RobotFileParser

AGENT = 'PublicTechnicalDocumentResearch/1.0 (+https://github.com/criticalcareresearchny-debug/hardware-discovery-test)'
MAX_BYTES = 40 * 1024 * 1024
TIMEOUT = 25
DELAY = 1.25
ALLOWED_KEYS = {'manufacturer', 'model', 'url', 'document_hint', 'language'}
TECH = re.compile(r'(manual|datasheet|data.?sheet|specification|technical|catalog|brochur|bedien|datenblatt|technisch|notice|catalogue|仕様|取扱|技术|技术|说明|설명|характерист)', re.I)

def utc(): return datetime.now(timezone.utc).isoformat()
def sha(data): return hashlib.sha256(data).hexdigest()
def dump(path, data): path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl): return None

class Retriever:
    def __init__(self, out):
        self.out = out
        self.opener = urllib.request.build_opener(NoRedirect)
        self.robots = {}
        self.last = {}

    def validate_url(self, url):
        p = urllib.parse.urlsplit(url)
        if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
            raise ValueError('Only public unauthenticated HTTP(S) URLs accepted')
        if p.port not in (None, 80, 443): raise ValueError('Unexpected port')
        for addr in socket.getaddrinfo(p.hostname, p.port or 443, type=socket.SOCK_STREAM):
            if not ipaddress.ip_address(addr[4][0]).is_global:
                raise ValueError('Non-public network target rejected')
        return p

    def request_once(self, url, limit):
        p = self.validate_url(url)
        wait = DELAY - (time.monotonic() - self.last.get(p.netloc, 0))
        if wait > 0: time.sleep(wait)
        self.last[p.netloc] = time.monotonic()
        req = urllib.request.Request(url, headers={'User-Agent': AGENT, 'Accept': 'application/pdf,text/html,application/xml,text/plain,*/*;q=0.1'})
        try:
            with self.opener.open(req, timeout=TIMEOUT) as r:
                body = r.read(limit + 1)
                if len(body) > limit: raise ValueError('Document exceeds configured maximum bytes')
                return r.status, dict(r.headers), body
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), b''

    def permit(self, url):
        p = urllib.parse.urlsplit(url)
        origin = p.scheme + '://' + p.netloc
        if origin not in self.robots:
            ru = origin + '/robots.txt'
            rec = {'url': ru, 'retrieved_utc': utc()}
            parser = None
            try:
                status, headers, raw = self.request_once(ru, 1024 * 1024)
                rec.update(http_status=status, sha256=sha(raw), bytes=len(raw))
                if status == 200:
                    parser = RobotFileParser(ru)
                    parser.parse(raw.decode('utf-8', 'replace').splitlines())
                    rp = self.out / 'robots' / (sha(origin.encode())[:20] + '.txt')
                    rp.parent.mkdir(exist_ok=True)
                    rp.write_bytes(raw)
                    rec['artifact_path'] = str(rp.relative_to(self.out))
                elif status in (404, 410):
                    parser = RobotFileParser(ru); parser.parse([])
                    rec['interpretation'] = 'No robots file at this origin (404/410)'
                else: rec['interpretation'] = 'Robots unavailable; conservative skip'
            except Exception as e: rec['error'] = type(e).__name__ + ': ' + str(e)[:300]
            self.robots[origin] = parser, rec
        parser, rec = self.robots[origin]
        allowed = bool(parser and parser.can_fetch(AGENT, url))
        if parser:
            delay = parser.crawl_delay(AGENT) or parser.crawl_delay('*')
            if delay:
                wait = delay - (time.monotonic() - self.last.get(p.netloc, 0))
                if wait > 0: time.sleep(min(wait, 120))
        return allowed, rec

    def retrieve(self, source):
        key = sha(source['url'].encode())[:20]
        dest = self.out / 'documents' / key
        dest.mkdir(parents=True, exist_ok=True)
        result = {'source': source, 'retrieved_utc': utc(), 'key': key, 'redirects': [], 'interpretation': 'UNREVIEWED_ORIGINAL_SOURCE_RETRIEVAL'}
        url = source['url']
        try:
            for n in range(6):
                allowed, robots = self.permit(url)
                result.setdefault('robots_checks', []).append(robots | {'permitted': allowed})
                if not allowed:
                    result['outcome'] = 'SKIPPED_ROBOTS_OR_ROBOTS_UNAVAILABLE'; break
                status, headers, body = self.request_once(url, MAX_BYTES)
                result['http_status'] = status
                if status in (301, 302, 303, 307, 308):
                    next_url = urllib.parse.urljoin(url, headers.get('Location', headers.get('location', '')))
                    if not next_url or next_url == url: raise ValueError('Redirect lacks usable destination')
                    result['redirects'].append({'from': url, 'to': next_url, 'status': status})
                    url = next_url; continue
                result['final_url'] = url
                result['content_type'] = headers.get('Content-Type', headers.get('content-type', ''))
                result['last_modified'] = headers.get('Last-Modified', headers.get('last-modified'))
                if status != 200:
                    result['outcome'] = 'HTTP_' + str(status); break
                is_pdf = body.startswith(b'%PDF-')
                ext = '.pdf' if is_pdf else '.html' if 'html' in result['content_type'] else '.bin'
                payload = dest / ('original' + ext)
                payload.write_bytes(body)
                result.update(outcome='RETRIEVED', bytes=len(body), sha256=sha(body), original_filename=urllib.parse.unquote(Path(urllib.parse.urlsplit(url).path).name), payload=str(payload.relative_to(self.out)))
                self.extract(payload, result, dest)
                break
            else: result['outcome'] = 'REDIRECT_LIMIT'
        except Exception as e:
            result.update(outcome='RETRIEVAL_ERROR', error=type(e).__name__ + ': ' + str(e)[:400])
        dump(dest / 'record.json', result)
        return result

    def extract(self, payload, result, dest):
        try:
            pages = []
            if payload.suffix == '.pdf':
                from pypdf import PdfReader
                reader = PdfReader(str(payload))
                result['pdf_metadata'] = {str(k): str(v) for k, v in (reader.metadata or {}).items()}
                result['pdf_page_count'] = len(reader.pages)
                for i, page in enumerate(reader.pages):
                    text = page.extract_text(extraction_mode='layout') or ''
                    pages.append({'page_1_based': i + 1, 'text': text})
                result['extraction_note'] = 'pypdf layout text; order, symbols and table alignment require verification against original PDF'
            elif payload.suffix == '.html':
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(payload.read_bytes(), 'html.parser')
                result['title'] = soup.title.get_text(' ', strip=True) if soup.title else None
                tables = [[[' '.join(c.stripped_strings) for c in row.find_all(['th','td'])] for row in table.find_all('tr')] for table in soup.find_all('table')]
                dump(dest / 'html_tables.json', tables)
                links = []
                for a in soup.find_all('a', href=True):
                    label = a.get_text(' ', strip=True)
                    href = urllib.parse.urljoin(result['final_url'], a['href'])
                    if urllib.parse.urlsplit(href).scheme in ('http','https') and ('.pdf' in href.lower() or TECH.search(label + ' ' + href)):
                        links.append({'label': label, 'url': href})
                dump(dest / 'document_links.json', list({x['url']:x for x in links}.values()))
                for x in soup(['script','style','noscript','svg']): x.decompose()
                pages = [{'page_1_based': None, 'text': soup.get_text('\n', strip=True)}]
                result['extraction_note'] = 'Static HTML text and table transcription; JavaScript-loaded data may be absent'
            else: result['extraction_note'] = 'Unrecognized media type; raw bytes preserved'
            dump(dest / 'pages.json', pages)
            (dest / 'extracted.txt').write_text('\n\n'.join(('=== PDF PAGE %s ===\n' % p['page_1_based'] if p['page_1_based'] else '=== HTML DOCUMENT ===\n') + p['text'] for p in pages), encoding='utf-8')
            model = result['source'].get('model', '')
            model_words = [s for s in re.split(r'\s+', model) if len(s) > 2]
            hints = []
            for p in pages:
                for n, line in enumerate(p['text'].splitlines()):
                    if any(w.lower() in line.lower() for w in model_words) or TECH.search(line):
                        hints.append({'page_1_based': p['page_1_based'], 'line_1_based': n + 1, 'text': line[:500]})
            dump(dest / 'locator_hints.json', hints)
        except Exception as e:
            result['extraction_error'] = type(e).__name__ + ': ' + str(e)[:400]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sources', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--shard', type=int, default=0)
    ap.add_argument('--shards', type=int, default=1)
    args = ap.parse_args()
    out = Path(args.output); out.mkdir(parents=True, exist_ok=True)
    raw = Path(args.sources).read_text(encoding='utf-8')
    if re.search(r'\bIN\d{4,}\b|RESEARCH_STAGING|AUTHORITATIVE|library_file_id|file_0000', raw, re.I):
        raise ValueError('Private identifier guard rejected input')
    sources = json.loads(raw)
    if not isinstance(sources, list) or len(sources) > 600: raise ValueError('Expected at most 600 public source records per run')
    for s in sources:
        if not isinstance(s, dict) or set(s) - ALLOWED_KEYS or not s.get('url'): raise ValueError('Unexpected source schema')
    selected = [s for s in sources if int(sha(urllib.parse.urlsplit(s['url']).netloc.encode()), 16) % args.shards == args.shard]
    dump(out / 'public_sources_used.json', selected)
    shutil.copyfile(__file__, out / 'recover_public_documents.py')
    run = {'started_utc': utc(), 'script_sha256': sha(Path(__file__).read_bytes()), 'source_manifest_sha256': sha(raw.encode()), 'python': sys.version, 'shard': args.shard, 'shards': args.shards, 'selected_sources': len(selected), 'github': {k:os.getenv(k) for k in ('GITHUB_REPOSITORY','GITHUB_SHA','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_JOB','GITHUB_REF_NAME')}, 'engineering_acceptance_performed': False}
    groups = defaultdict(list)
    for s in selected: groups[urllib.parse.urlsplit(s['url']).netloc].append(s)
    def group(items):
        r = Retriever(out)
        return [r.retrieve(item) for item in items]
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        for res in pool.map(group, groups.values()):
            results.extend(res)
            print(json.dumps({'completed_sources': len(results), 'outcomes': dict(Counter(x['outcome'] for x in results))}), flush=True)
    results.sort(key=lambda x:x['source']['url'])
    dump(out / 'results.json', results)
    run.update(finished_utc=utc(), outcomes=dict(Counter(x['outcome'] for x in results)))
    dump(out / 'run_metadata.json', run)
    files = [{'path': str(p.relative_to(out)), 'bytes': p.stat().st_size, 'sha256': sha(p.read_bytes())} for p in sorted(out.rglob('*')) if p.is_file()]
    dump(out / 'SHA256_MANIFEST.json', files)
    print(json.dumps(run, ensure_ascii=False), flush=True)

if __name__ == '__main__': main()
