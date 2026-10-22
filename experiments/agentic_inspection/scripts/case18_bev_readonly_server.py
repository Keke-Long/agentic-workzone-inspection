"""Read-only case pages with shared navigation; legacy URLs remain available."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
import gzip
import json
import re

REPORTS = Path(__file__).resolve().parents[1] / 'reports'
CASES = {
    1: REPORTS / 'workzone_01/bev',
    2: REPORTS / 'workzone_02/ta22_user_selected/post_review_20261021',
    3: REPORTS / 'workzone_03',
}
ROUTES = {}
for case, root in CASES.items():
    bev = 'bev.html'
    report = 'final/report.html' if case == 3 else 'report.html'
    for suffix, filename in {'': bev, '/bev': bev, '/report': report,
                             '/bev-overview.png': 'bev_overview.png',
                             '/sensor_bev_preview.png': 'sensor_bev_preview.png'}.items():
        ROUTES[f'/workzone{case}{suffix}'] = (case, root / filename)
for url, filename in {'/': 'bev.html', '/bev': 'bev.html', '/report': 'report.html',
                       '/bev-overview.png': 'bev_overview.png'}.items():
    ROUTES[url] = (2, CASES[2] / filename)




def navigation(case, route):
    links = ''.join(
        f'<a href="/workzone{i}/bev"'+(' aria-current="page"' if i == case else '')+
        f'>Workzone {i}</a>' for i in CASES
    )
    status = {1: 'TA-30 · 最终 PDF：16 条通过 · 2 条未通过 · 1 条未评判', 2: '对象 BEV · 规范报告含证据限制',
              3: 'TA-19 · Stage 0–6 已完成 · 报告含证据限制'}[case]
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
    module = (REPORTS / f'workzone_{case:02d}/inspection_summary/module.html').read_text()
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
        report_match = re.fullmatch(r'/workzone([123])/report', route)
        if report_match or route == '/report':
            case = int(report_match[1]) if report_match else 2
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
            if path.name == 'bev.html':
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
