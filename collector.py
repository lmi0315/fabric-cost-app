#!/usr/bin/env python3
"""Collect recent, attributable PUBLIC textile quotations; no auth or scraping bypass.

Outputs the existing PWA's data/prices.json schema plus provenance and diagnostics.
The sources are best-effort public pages; there is no guaranteed live-feed API.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parent
TARGET = ROOT / 'data' / 'prices.json'
TZ = dt.timezone(dt.timedelta(hours=8))
TODAY = dt.datetime.now(TZ).date()
NOW = dt.datetime.now(dt.timezone.utc)
MAX_AGE_DAYS = 30
MAX_BYTES = 2_000_000
SOURCES = [
    ('纺织网资讯', f'https://info.texnet.com.cn/pro--{page}.html', 20)
    for page in range(1, 5)
] + [
    ('全球纺织网', 'https://www.tnc.com.cn/market/', 30),
    ('中国棉花信息网', 'https://cottonchina.org.cn/', 10),
]
# Explicit product specifications. Do NOT map acrylic to acrylonitrile feedstock.
MATERIALS = {
    'polyester': ('涤纶短纤', '涤纶短纤', 3500, 30000),
    'spandex': ('氨纶', '氨纶', 12000, 100000),
    'viscose': ('粘胶短纤', '粘胶短纤(?:1[.]2D)?', 7000, 40000),
    'cotton': ('皮棉', '皮棉', 7000, 40000),
    'nylon': ('锦纶POY', '锦纶POY', 6000, 45000),
}

class PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chunks = []
        self.links = []
        self.current_link = None
        self.ignore = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self.ignore += 1
        if tag == 'a':
            self.current_link = {'href': dict(attrs).get('href', ''), 'texts': []}
        if tag in ('p', 'li', 'br', 'tr', 'div', 'h2', 'h3'):
            self.chunks.append(' ')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'):
            self.ignore = max(0, self.ignore - 1)
        if tag == 'a' and self.current_link:
            label = ' '.join(self.current_link['texts']).strip()
            if label:
                self.links.append((label, self.current_link['href']))
            self.current_link = None
        if tag in ('p', 'li', 'br', 'tr', 'div', 'h2', 'h3'):
            self.chunks.append(' ')

    def handle_data(self, data):
        if not self.ignore:
            self.chunks.append(data)
            if self.current_link is not None:
                self.current_link['texts'].append(data)

    def text(self):
        return re.sub(r'\s+', ' ', ' '.join(self.chunks))


def fetch_html(url):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (compatible; FabricCostResearch/2.1; public informational pages)',
        'Accept': 'text/html,application/xhtml+xml',
    })
    with urllib.request.urlopen(req, timeout=22) as response:
        content = response.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise ValueError('page over maximum size')
        declared = response.headers.get_content_charset()
        # Sites frequently use Chinese legacy encodings.
        encodings = [declared, 'utf-8', 'gb18030']
        for enc in filter(None, encodings):
            try:
                return content.decode(enc)
            except (UnicodeError, LookupError):
                pass
        return content.decode('utf-8', errors='replace')


def dated(day, month):
    month, day = int(month), int(day)
    possible = []
    for year in (TODAY.year, TODAY.year - 1):
        try:
            item = dt.date(year, month, day)
        except ValueError:
            continue
        age = (TODAY - item).days
        if 0 <= age <= MAX_AGE_DAYS:
            possible.append(item)
    return max(possible) if possible else None


def quote(key, price_per_ton, date, source, url, *, specification=None, priority=50):
    label, _, lower, upper = MATERIALS[key]
    if date is None or not lower <= price_per_ton <= upper:
        return None
    if not url.startswith(('https://', 'http://')):
        return None
    return {
        'key': key,
        'name': label,
        'priceYuanPerKg': round(price_per_ton / 1000, 4),
        'date': date.isoformat(),
        'source': source,
        'sourceUrl': url,
        'specification': specification or f'{label}行业报价，仅供成本估算',
        'status': 'market',
        '_priority': priority,
    }


def extract_headlines(label, url, html):
    page = PageText()
    page.feed(html)
    items = []
    # Prioritize individual article links; fallback to whole-page text, not nearby unrelated prices.
    sections = [(t, urllib.parse.urljoin(url, href)) for t, href in page.links]
    sections.append((page.text(), url))
    for text, link in sections:
        for key, (_, product_re, _, _) in MATERIALS.items():
            pattern = (r'(\d{1,2})月\s*(\d{1,2})日\s*(?:生意社)?\s*'
                       + product_re + r'\s*(?:基准价|价格)?\s*为\s*'
                       + r'(\d{3,7}(?:\.\d+)?)\s*元\s*/\s*吨')
            for match in re.finditer(pattern, text):
                try:
                    price = float(match.group(3))
                except ValueError:
                    continue
                day = dated(match.group(2), match.group(1))
                q = quote(key, price, day, label, link, priority=20 if '纺织网资讯' == label else 30)
                if q:
                    items.append(q)
    return items


def extract_cotton_index(label, url, html):
    page = PageText()
    page.feed(html)
    text = page.text()
    # CC Index 3128B is a specific cotton index; quote labelled explicitly.
    pattern = r'CC\s*Index\s*3128B.{0,110}?(20\d{2}-\d{2}-\d{2}).{0,60}?(\d{4,6}(?:\.\d+)?)\s*元\s*/\s*吨'
    out = []
    for match in re.finditer(pattern, text, re.IGNORECASE):
        try:
            date = dt.date.fromisoformat(match.group(1))
            price = float(match.group(2))
        except ValueError:
            continue
        if 0 <= (TODAY - date).days <= MAX_AGE_DAYS:
            q = quote('cotton', price, date, label, url,
                      specification='中国棉花价格指数 CC Index 3128B；不等于任意规格棉花采购价', priority=10)
            if q:
                out.append(q)
    return out


def main():
    try:
        old = json.loads(TARGET.read_text(encoding='utf-8'))
    except (FileNotFoundError, ValueError):
        old = {'prices': {}, 'updatedAt': None}
    prices = dict(old.get('prices') or {})
    diagnostics = []
    candidates = []
    for source, url, priority in SOURCES:
        try:
            html = fetch_html(url)
            found = extract_cotton_index(source, url, html) if source == '中国棉花信息网' else extract_headlines(source, url, html)
            candidates.extend(found)
            diagnostics.append({'source': source, 'url': url, 'status': 'ok' if found else 'no_matching_quotes', 'candidates': len(found)})
            print(f'{source}: {len(found)} dated quotations ({url})')
        except Exception as exc:
            diagnostics.append({'source': source, 'url': url, 'status': 'error', 'reason': str(exc)[:180]})
            print(f'{source}: failed {type(exc).__name__}: {exc}')
    # On a given day, prefer material-specific comparable data, then trusted source priority.
    # Never overwrite newer observations with older quotes.
    best = {}
    for q in candidates:
        key = q['key']
        current = best.get(key)
        if current is None or (q['date'], -q['_priority']) > (current['date'], -current['_priority']):
            best[key] = q
    changed = 0
    for key, entry in best.items():
        entry = {k: v for k, v in entry.items() if not k.startswith('_') and k != 'key'}
        prior = prices.get(key) or {}
        if prior.get('date', '') > entry['date']:
            continue
        if prior != entry:
            prices[key] = entry
            changed += 1
    # Do not misrepresent a collection attempt as a successful data refresh.
    updated_at = NOW.isoformat() if changed else old.get('updatedAt')
    result = {
        'updatedAt': updated_at,
        'lastCheckedAt': NOW.isoformat(),
        'method': 'public-multi-source-dated-headlines-v2.1',
        'prices': prices,
        'diagnostics': diagnostics,
        'note': '公开网页报价，非实时成交价。采集失败时不伪造行情；报价日期、规格和来源见各条记录。',
    }
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Candidates:', len(candidates), 'Materials with recent quotes:', len(best), 'Updated records:', changed)
    for key, entry in best.items():
        print(key, entry['date'], entry['priceYuanPerKg'], entry['source'], entry['sourceUrl'])

if __name__ == '__main__':
    main()
