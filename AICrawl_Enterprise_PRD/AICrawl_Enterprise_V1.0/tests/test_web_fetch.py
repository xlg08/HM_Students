import unittest
import time
from unittest.mock import patch
from backend.web_fetch import normalize_url, public_addresses, fetch_page, FetchBlocked
from backend.service import Service, Problem
from backend.config import Settings

class WebTests(unittest.TestCase):
    def test_ssrf_validation(self):
        for url in ['http://example.com', 'https://127.0.0.1/', 'https://[::1]/', 'https://169.254.169.254/', 'https://localhost/', 'https://example.com:8443/', 'https://user:pass@example.com/', 'file:///etc/passwd']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                normalize_url(url)
        with patch('backend.web_fetch.socket.getaddrinfo', return_value=[(2,1,6,'',('10.0.0.1',443))]):
            with self.assertRaises(FetchBlocked): public_addresses('public.example')

    def test_robots_deny_no_target_request(self):
        with patch('backend.web_fetch.read_url', return_value=(200, {}, b'User-agent: *\nDisallow: /')) as request:
            with self.assertRaises(FetchBlocked): fetch_page('https://www.baidu.com/')
            self.assertEqual(request.call_count, 1)

    def test_extract_no_script_and_absolute_links(self):
        responses=[(404, {}, b''), (200, {'Content-Type': 'text/html; charset=utf-8'}, b'<title>Example</title><script>secret()</script><p>Hello world</p><a href="/docs">Docs</a>')]
        with patch('backend.web_fetch.read_url', side_effect=responses):
            payload, evidence = fetch_page('https://example.com/')
        self.assertEqual(payload['title'], 'Example')
        self.assertNotIn('secret()', payload['text'])
        self.assertEqual(payload['links'], ['https://example.com/docs'])
        self.assertEqual(len(evidence['response_sha256']), 64)

    def test_redirect_and_login_blocked(self):
        for target in [(302, {'Location': 'https://127.0.0.1/'}, b''), (200, {'Content-Type':'text/html'}, b'<title>captcha</title>')]:
            with patch('backend.web_fetch.read_url', side_effect=[(404, {}, b''), target]):
                with self.assertRaises(FetchBlocked): fetch_page('https://example.com/')

    def test_web_test_pipeline_and_blocked_state(self):
        s=Service(Settings(stage_delay=0))
        self.addCleanup(s.close)
        with self.assertRaises(Problem): s.web_test({'url':'https://example.com/'})
        with patch('backend.service.fetch_page', side_effect=FetchBlocked('robots denied')):
            run=s.web_test({'url':'https://example.com/','note':'Owned page test','authorized':True})
            for _ in range(100):
                current=s.state()['runs'][0]
                if current['status']=='BLOCKED': break
                time.sleep(.01)
        self.assertEqual(current['status'],'BLOCKED')
        self.assertEqual(len(s.records),0)
