import unittest
from unittest.mock import patch
from backend.config import Settings
from backend.service import Service, Problem
from backend.connectors import parse_metadata
import time

class ConnectorTests(unittest.TestCase):
    def test_parse_and_missing_fields(self):
        result = parse_metadata({'info': {'name': 'demo', 'version': '1', 'requires_dist': ['dep']}, 'urls': []})
        self.assertEqual(result['version'], '1')
        self.assertIsNone(result['published_at'])
        with self.assertRaises(ValueError):
            parse_metadata({'info': {}})

    def test_real_pipeline_and_failure_no_fallback(self):
        service = Service(Settings(stage_delay=0))
        self.addCleanup(service.close)
        source = next(s for s in service.sources.values() if s['mode'] == 'PUBLIC_API')
        with self.assertRaises(Problem):
            service.source_action(source['id'], 'approve')
        service.source_action(source['id'], 'approve', {'note': 'Internal metadata monitoring using official API'})
        job = service.create_job({'name': 'real API test', 'source_id': source['id']})
        payload = {'title': 'demo 1', 'package': 'demo', 'version': '1', 'source_url': 'https://pypi.org/project/demo/'}
        evidence = {'uri': 'https://pypi.org/pypi/demo/json', 'raw': {'name': 'demo'}, 'response_sha256': 'abc'}
        with patch('backend.service.fetch_metadata', return_value=(payload, evidence)):
            run = service.start(job['id'])
            self.wait(service, run['id'])
        record = next(iter(service.records.values()))
        self.assertEqual(record['mode'], 'PUBLIC_API')
        self.assertEqual(record['status'], 'PUBLISHED')
        with patch('backend.service.fetch_metadata', side_effect=ValueError('network failure')):
            run = service.start(job['id'])
            self.wait(service, run['id'])
        self.assertEqual(service.runs[run['id']]['status'], 'FAILED')
        self.assertEqual(len(service.records), 1)

    def wait(self, service, rid):
        for _ in range(100):
            if service.state()['runs'][0]['status'] in ('FAILED', 'SUCCEEDED'):
                return
            time.sleep(.01)
        self.fail('timeout')
