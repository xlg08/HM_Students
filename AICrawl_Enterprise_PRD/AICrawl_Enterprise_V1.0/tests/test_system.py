import json
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from backend.service import Service
from backend.server import handler


class SystemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = Service()
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), handler(cls.service))
        cls.base = 'http://127.0.0.1:' + str(cls.server.server_port)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.service.close()
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, path, data=None):
        req = Request(self.base + '/api/v1/' + path, data=None if data is None else json.dumps(data).encode(), headers={'Content-Type': 'application/json'})
        with urlopen(req, timeout=5) as response:
            return json.load(response)

    def wait_run(self, rid):
        for _ in range(100):
            run = next(r for r in self.request('state')['runs'] if r['id'] == rid)
            if run['status'] in ('SUCCEEDED', 'FAILED', 'CANCELLED'):
                return run
            time.sleep(.1)
        self.fail('运行未在期限内结束')

    def test_end_to_end(self):
        source = self.request('sources', {'name': '测试招聘源', 'kind': 'jobs'})
        with self.assertRaises(HTTPError) as error:
            self.request('jobs', {'name': '未批准任务', 'source_id': source['id']})
        self.assertEqual(error.exception.code, 409)
        self.request(f"sources/{source['id']}/approve", {})
        job = self.request('jobs', {'name': '测试任务', 'source_id': source['id']})
        run = self.request(f"jobs/{job['id']}/runs", {})
        with self.assertRaises(HTTPError):
            self.request(f"jobs/{job['id']}/runs", {})
        self.request(f"runs/{run['id']}/pause", {})
        time.sleep(.8)
        paused = next(r for r in self.request('state')['runs'] if r['id'] == run['id'])
        self.assertEqual(paused['status'], 'PAUSED')
        self.request(f"runs/{run['id']}/resume", {})
        self.assertEqual(self.wait_run(run['id'])['status'], 'SUCCEEDED')
        records = [r for r in self.request('state')['records'] if r['source_id'] == source['id']]
        self.assertEqual(len(records), 3)
        self.assertEqual(sum(r['status'] == 'PUBLISHED' for r in records), 2)
        review = next(r for r in records if r['status'] == 'REVIEW')
        self.assertEqual(review['payload'], review['evidence']['raw'])
        with self.assertRaises(HTTPError):
            self.request(f"records/{review['id']}/review", {'decision': 'approve', 'note': '强行发布'})
        self.request(f"records/{review['id']}/review", {'decision': 'reject', 'note': '公司字段缺失'})
        again = self.request(f"jobs/{job['id']}/runs", {})
        self.assertEqual(self.wait_run(again['id'])['count'], 0)
        with urlopen(self.base + '/api/v1/export.csv') as response:
            csv = response.read().decode('utf-8-sig')
        self.assertIn('Python', csv)
        self.assertNotIn('AI 应用工程师', csv)

    def test_cancel_no_publish(self):
        job = next(iter(self.service.jobs.values()))
        run = self.request(f"jobs/{job['id']}/runs", {})
        self.request(f"runs/{run['id']}/cancel", {})
        time.sleep(.8)
        self.assertFalse(any(r['run_id'] == run['id'] for r in self.request('state')['records']))

    def test_invalid_requests_and_static(self):
        with self.assertRaises(HTTPError) as error:
            self.request('sources', {'name': '', 'kind': 'bad'})
        self.assertEqual(error.exception.code, 400)
        with self.assertRaises(HTTPError) as error:
            self.request('sources', [])
        self.assertEqual(error.exception.code, 400)
        for path in ('/', '/app.js', '/style.css'):
            with urlopen(self.base + path) as response:
                self.assertEqual(response.status, 200)
        req = Request(self.base + '/api/v1/sources', data=b'{}', headers={'Content-Type': 'application/json', 'Origin': 'https://untrusted.example'})
        with self.assertRaises(HTTPError) as error:
            urlopen(req)
        self.assertEqual(error.exception.code, 403)


if __name__ == '__main__':
    unittest.main()
