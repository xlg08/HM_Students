import concurrent.futures
import json
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from backend.config import Settings
from backend.server import ApplicationServer, handler
from backend.service import Problem, Service


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.service = Service(Settings(workers=1, max_pending=2, stage_delay=.01))
        self.addCleanup(self.service.close)

    def wait(self, rid):
        for _ in range(100):
            run = next(r for r in self.service.state()['runs'] if r['id'] == rid)
            if run['status'] in ('SUCCEEDED', 'FAILED', 'CANCELLED'):
                return run
            time.sleep(.01)
        self.fail('运行超时')

    def test_concurrent_idempotency(self):
        jid = next(iter(self.service.jobs))
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.service.start(jid, 'same-key'), range(20)))
        self.assertEqual(len({r['id'] for r in results}), 1)
        rid = results[0]['id']
        self.assertEqual(self.wait(rid)['status'], 'SUCCEEDED')
        self.assertEqual(self.service.start(jid, 'same-key')['id'], rid)
        self.assertEqual(len(self.service.records), 3)

    def test_capacity_and_shutdown_paused_runs(self):
        jobs = list(self.service.jobs)
        first = self.service.start(jobs[0])
        self.service.run_action(first['id'], 'pause')
        second = self.service.start(jobs[1])
        self.service.run_action(second['id'], 'pause')
        with self.assertRaises(Problem) as error:
            self.service.start(jobs[2])
        self.assertEqual(error.exception.status, 429)
        self.service.close()
        self.assertEqual(self.service.metrics()['active_runs'], 0)
        self.assertEqual(len(self.service.records), 0)
        with self.assertRaises(Problem) as error:
            self.service.start(jobs[2])
        self.assertEqual(error.exception.status, 503)

    def test_suspended_source_prevents_publish(self):
        job = next(iter(self.service.jobs.values()))
        run = self.service.start(job['id'])
        self.service.source_action(job['source_id'], 'suspend')
        self.assertEqual(self.wait(run['id'])['status'], 'FAILED')
        self.assertFalse(self.service.records)

    def test_pagination_and_validation(self):
        result = self.service.list_resource('sources', page=2, page_size=2)
        self.assertEqual(result['total'], 6)
        self.assertEqual(len(result['items']), 2)
        self.assertEqual(self.service.list_resource('sources', query='招聘')['total'], 1)
        for operation in (
            lambda: self.service.list_resource('records', page_size=101),
            lambda: self.service.create_source({'name': 'x', 'kind': []}),
            lambda: self.service.create_job({'name': 'x', 'source_id': {}}),
        ):
            with self.assertRaises(Problem):
                operation()

    def test_http_errors_and_correlation(self):
        server = ApplicationServer(('127.0.0.1', 0), handler(self.service))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}/api/v1/'
        with urlopen(base + 'records?page_size=2') as response:
            self.assertEqual(json.load(response)['page_size'], 2)
            self.assertTrue(response.headers['X-Request-ID'])
            self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])
        req = Request(base + 'jobs', data=b'{broken', headers={'Content-Type': 'application/json', 'X-Request-ID': 'test-request'})
        with self.assertRaises(HTTPError) as error:
            urlopen(req)
        self.assertEqual(error.exception.code, 400)
        body = json.load(error.exception)
        self.assertEqual(body['error']['request_id'], 'test-request')
        req = Request(base + 'jobs', data=b'{"name":"x","source_id":[]}', headers={'Content-Type': 'application/json'})
        with self.assertRaises(HTTPError) as error:
            urlopen(req)
        self.assertEqual(error.exception.code, 400)
        with urlopen(base + 'ready') as response:
            self.assertTrue(json.load(response)['ready'])
