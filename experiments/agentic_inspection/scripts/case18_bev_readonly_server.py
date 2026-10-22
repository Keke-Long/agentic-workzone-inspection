"""Read-only case pages with shared navigation; legacy URLs remain available."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
import gzip
import json
import re

import sys
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / 'tools'))
from project_layout import load_cases
CASE_CONFIGS = load_cases(PROJECT_ROOT)
CASES = {n: c['resolved_paths']['viewer'].parent for n, c in CASE_CONFIGS.items()}
ROUTES = {}
for number, case in CASE_CONFIGS.items():
    for suffix in ['', '/bev']:
        ROUTES[f'/workzone{number}{suffix}'] = (number, case['resolved_paths']['viewer'])
    for suffix, filename in [('/bev-overview.png', 'bev_overview.png'), ('/sensor_bev_preview.png', 'sensor_bev_preview.png')]:
        ROUTES[f'/workzone{number}{suffix}'] = (number, CASES[number] / filename)
DEFAULT_CASE = min(CASE_CONFIGS)
for route in ['/', '/bev']:
    ROUTES[route] = (DEFAULT_CASE, CASE_CONFIGS[DEFAULT_CASE]['resolved_paths']['viewer'])


def navigation(case, route):
    links = ''.join(
        f'<a href="/workzone{i}/bev"'+(' aria-current="page"' if i == case else '')+
        f'>Workzone {i}</a>' for i in CASES
    )
    metadata = CASE_CONFIGS[case]
    result = json.loads(metadata['resolved_paths']['report'].read_text())
    labels = {'pass':'通过', 'fail':'未通过', 'unknown':'证据不足', 'pending':'待评判', 'na':'不适用'}
    status = metadata['layout'] + ' · ' + ' · '.join(f"{count} 条{labels.get(key,key)}" for key,count in result['counts'].items())
    return '''<style>
.wz-nav{box-sizing:border-box;display:flex;flex-wrap:wrap;align-items:center;gap:10px;padding:12px 20px;margin:0 0 12px;background:#142b42;color:#fff;font:14px/1.5 system-ui;border-radius:0}
.wz-nav a{display:inline-block;padding:7px 12px;border:1px solid #8194a7;border-radius:6px;color:#fff;text-decoration:none;white-space:nowrap}
.wz-nav a:hover,.wz-nav a:focus-visible{background:#345571;outline:2px solid #bbdcff}
.wz-nav a[aria-current=page]{background:#fff;color:#142b42;font-weight:700}
.wz-nav .wz-state{flex:1;min-width:180px;color:#d4e3f0}.wz-nav .wz-local{font-size:13px}
</style><nav class="wz-nav" aria-label="Workzone 案例导航">''' + links + \
        f'<span class="wz-state">{status}</span><a class="wz-local" href="/workzone{case}/bev">'+ \
        'BEV' + \
        f'</a><a class="wz-local" href="/workzone{case}/bev#case-report">'+ \
        '规范结果' + '</a>' + '</nav>'


def add_navigation(data, case, route):
    text = data.decode('utf-8')
    # Canonicalize old Workzone 2 links to stay within its own case page.
    if case == 2:
        text = text.replace('href="/report"', 'href="/workzone2/report"').replace('href="/bev"', 'href="/workzone2/bev"')
    nav = navigation(case, route)
    match = re.search(r'<body\b[^>]*>', text, flags=re.I)
    if match:
        return (text[:match.end()] + nav + text[match.end():]).encode('utf-8')
    match = re.search(r'<(?:header|h1)\b', text, flags=re.I)
    if not match:
        raise ValueError('HTML page has no insertion point for case navigation')
    return (text[:match.start()] + nav + text[match.start():]).encode('utf-8')


def add_report_module(data, case):
    """Append the derived checklist directly to the BEV document."""
    module = CASE_CONFIGS[case]['resolved_paths']['report_module'].read_text()
    text = data.decode('utf-8')
    marker = '</body>' if '</body>' in text else '</html>'
    return text.replace(marker, module + marker, 1).encode('utf-8')


class Handler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.serve(head=True)

    def json_reply(self, status, value):
        data=json.dumps(value,ensure_ascii=False).encode()
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)

    def do_POST(self):
        self.send_error(405, 'Final viewer is read-only')

    def do_GET(self):
        self.serve()

    def serve(self, head=False):
        route = urlsplit(self.path).path.rstrip('/') or '/'
        report_match = re.fullmatch(r'/workzone([0-9]+)/report', route)
        if report_match or route == '/report':
            case = int(report_match[1]) if report_match else DEFAULT_CASE
            if case not in CASE_CONFIGS:
                self.send_error(404)
                return
            self.send_response(302)
            self.send_header('Location', f'/workzone{case}/bev#case-report')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            return
        record = ROUTES.get(route)
        if record is None:
            self.send_error(404)
            return
        case, path = record
        if not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        is_html = path.suffix == '.html'
        if is_html:
            embedded_report = route.endswith('/report') and parse_qs(urlsplit(self.path).query).get('embed') == ['1']
            if not embedded_report:
                data = add_navigation(data, case, route)
            if path == CASE_CONFIGS[case]['resolved_paths']['viewer']:
                data = add_report_module(data, case)
        compressed = is_html and 'gzip' in self.headers.get('Accept-Encoding', '')
        if compressed:
            data = gzip.compress(data, compresslevel=5)
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8' if is_html else ('image/jpeg' if path.suffix == '.jpg' else 'image/png'))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Vary', 'Accept-Encoding')
        if compressed:
            self.send_header('Content-Encoding', 'gzip')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        if not head:
            self.wfile.write(data)


if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', 8768), Handler).serve_forever()
