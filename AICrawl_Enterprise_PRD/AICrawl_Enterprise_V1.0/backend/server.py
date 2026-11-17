"""Standard-library JSON API and static frontend server."""
import argparse
import csv
import io
import json
import copy
import logging
import time
import uuid
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from .service import Service, Problem
from .config import Settings
from .observability import configure, request_id

FRONTEND = Path(__file__).resolve().parent.parent / 'frontend'


class ApplicationServer(ThreadingHTTPServer):
    """Bound both active HTTP handlers and waiting connections."""
    def __init__(self, address, handler_class):
        super().__init__(address, handler_class)
        self.pool = ThreadPoolExecutor(max_workers=16, thread_name_prefix='http')
        self.slots = threading.BoundedSemaphore(32)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        self.pool.submit(self.handle_bounded, request, client_address)

    def handle_bounded(self, request, client_address):
        try:
            self.process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def server_close(self):
        super().server_close()
        self.pool.shutdown(wait=True)


def handler(service):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'AICrawl/1.1'

        def setup(self):
            super().setup()
            self.connection.settimeout(service.settings.request_timeout)

        def log_message(self, format, *args):
            pass  # Structured logging below replaces the standard access log.

        def dispatch(self, method):
            incoming = self.headers.get('X-Request-ID', '')
            rid = incoming if re.fullmatch(r'[A-Za-z0-9_-]{1,64}', incoming) else uuid.uuid4().hex
            token = request_id.set(rid)
            started = time.monotonic()
            self.response_status = 500
            try:
                method()
            except Problem as exc:
                self.send(exc.status, {'error': {'code': 'HTTP_' + str(exc.status), 'message': exc.message, 'request_id': rid}})
            except (ValueError, TypeError, UnicodeError):
                self.send(400, {'error': {'code': 'INVALID_REQUEST', 'message': '请求格式无效', 'request_id': rid}})
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                logging.getLogger('aicrawl').warning('client_disconnected')
            except Exception:
                logging.getLogger('aicrawl').exception('unhandled_request_error')
                self.send(500, {'error': {'code': 'INTERNAL_ERROR', 'message': '服务内部错误，请凭请求 ID 排查', 'request_id': rid}})
            finally:
                logging.getLogger('aicrawl').info(json.dumps(dict(method=self.command, path=urlsplit(self.path).path,
                    status=self.response_status, duration_ms=round((time.monotonic()-started)*1000, 2))))
                request_id.reset(token)

        def do_GET(self):
            self.dispatch(self.get)

        def do_POST(self):
            self.dispatch(self.post)

        def send(self, status, body, content_type='application/json; charset=utf-8'):
            self.response_status = status
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Request-ID', request_id.get())
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(body)

        def get(self):
            path = urlsplit(self.path).path
            if path == '/api/v1/health':
                return self.send(200, dict(status='ok', storage='memory', mode='fixtures-and-public-api'))
            if path == '/api/v1/state':
                return self.send(200, service.state())
            if path == '/api/v1/metrics':
                return self.send(200, service.metrics())
            if path == '/api/v1/ready':
                ready = not service.stopping.is_set()
                return self.send(200 if ready else 503, {'ready': ready})
            parts = path.strip('/').split('/')
            if len(parts) == 3 and parts[:2] == ['api', 'v1'] and parts[2] in ('sources', 'jobs', 'runs', 'records', 'audit'):
                query = parse_qs(urlsplit(self.path).query)
                return self.send(200, service.list_resource(parts[2], int(query.get('page', ['1'])[0]),
                    int(query.get('page_size', ['20'])[0]), query.get('status', [''])[0], query.get('q', [''])[0]))
            if path == '/api/v1/export.csv':
                output = io.StringIO(newline='')
                writer = csv.writer(output)
                writer.writerow(['id', 'kind', 'source_id', 'run_id', 'data', 'evidence', 'created_at'])
                for r in service.state()['records']:
                    if r['status'] == 'PUBLISHED':
                        writer.writerow([r['id'], r['kind'], r['source_id'], r['run_id'], json.dumps(r['payload'], ensure_ascii=False), r['evidence']['uri'], r['created_at']])
                return self.send(200, ('\ufeff' + output.getvalue()).encode(), 'text/csv; charset=utf-8')
            assets = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'), '/style.css': ('style.css', 'text/css')}
            if path in assets:
                filename, mime = assets[path]
                return self.send(200, (FRONTEND / filename).read_bytes(), mime + '; charset=utf-8')
            raise Problem('接口或页面不存在', 404)

        def post(self):
            try:
                # Local mutations only; block cross-origin form submissions.
                origin = self.headers.get('Origin')
                if origin and urlsplit(origin).netloc != self.headers.get('Host'):
                    raise Problem('不允许跨来源修改', 403)
                if self.headers.get_content_type() != 'application/json':
                    raise Problem('请求必须为 application/json', 415)
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 65536:
                    raise Problem('请求体为空或超过 64KB', 413)
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise Problem('请求体必须为 JSON 对象')
                parts = urlsplit(self.path).path.strip('/').split('/')
                if parts[:2] != ['api', 'v1']:
                    raise Problem('接口不存在', 404)
                p = parts[2:]
                if p == ['sources']:
                    result = service.create_source(data)
                elif p == ['jobs']:
                    result = service.create_job(data)
                elif len(p) == 3 and p[0] == 'sources':
                    result = service.source_action(p[1], p[2], data)
                elif len(p) == 3 and p[0] == 'jobs' and p[2] == 'runs':
                    result = service.start(p[1], self.headers.get('Idempotency-Key'))
                elif len(p) == 3 and p[0] == 'runs':
                    result = service.run_action(p[1], p[2])
                elif len(p) == 3 and p[0] == 'records' and p[2] == 'review':
                    result = service.review(p[1], data)
                else:
                    raise Problem('接口不存在', 404)
                with service.lock:
                    result = copy.deepcopy(result)
                self.send(200, result)
            except Problem:
                raise

    return Handler


def main():
    settings = Settings.from_env()
    configure()
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=settings.port)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('port must be between 1 and 65535')
    service = Service(settings)
    server = ApplicationServer(('127.0.0.1', args.port), handler(service))
    print(f'AICrawl prototype: http://127.0.0.1:{args.port}  (Ctrl+C to stop)', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        service.close()
        server.server_close()


if __name__ == '__main__':
    main()
