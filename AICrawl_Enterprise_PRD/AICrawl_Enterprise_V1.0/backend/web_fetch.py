"""Single-page HTTPS fetch with pinned public IP, robots and bounded responses."""
import hashlib
import http.client
import ipaddress
import socket
import ssl
import threading
import time
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit, urljoin
from urllib.robotparser import RobotFileParser

AGENT = 'AICrawlTest/1.0'
MAX_BYTES = 1_000_000
_lock = threading.Lock()
_last = 0.0


class FetchBlocked(ValueError):
    pass


def normalize_url(url):
    if not isinstance(url, str) or not url or len(url) > 2048 or any(ord(c) < 33 for c in url):
        raise ValueError('请输入有效 HTTPS 地址，长度不超过 2048，不含空白或控制字符')
    p = urlsplit(url)
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None, 443):
        raise ValueError('仅支持 HTTPS 标准端口，不允许账号密码和自定义端口')
    host = p.hostname.encode('idna').decode('ascii')
    try:
        if not ipaddress.ip_address(host).is_global:
            raise ValueError('不允许访问内网、本机或保留地址')
    except ValueError as exc:
        if ':' in host or host.replace('.', '').isdigit():
            raise ValueError('不允许访问内网或不规范 IP 地址') from exc
    if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal')):
        raise ValueError('不允许访问本机或内部主机')
    # Keep URLs ASCII on the wire. Users may paste international paths.
    from urllib.parse import quote
    netloc = '[' + host + ']' if ':' in host else host
    return urlunsplit(('https', netloc, quote(p.path or '/', safe='/%:@!$&()*+,;=-._~'), quote(p.query, safe='=&%/:?+;,.-_~'), ''))


def public_addresses(host):
    addresses = list(dict.fromkeys(x[4][0] for x in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)))
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
        raise FetchBlocked('DNS 解析含内网、本机或保留地址，已阻止访问')
    return addresses


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address):
        super().__init__(host, timeout=8, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        raw = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def read_url(url):
    global _last
    p = urlsplit(normalize_url(url))
    address = public_addresses(p.hostname)[0]
    # Serialize remote requests, including robots. No proxy or ambient cookies.
    with _lock:
        time.sleep(max(0, 1 - (time.monotonic() - _last)))
        _last = time.monotonic()
        connection = PinnedHTTPS(p.hostname, address)
        try:
            connection.request('GET', p.path + ('?' + p.query if p.query else ''), headers={'User-Agent': AGENT, 'Accept': 'text/html,text/plain;q=0.9', 'Accept-Encoding': 'identity'})
            response = connection.getresponse()
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise FetchBlocked('响应超过 1MB，已停止读取')
            return response.status, dict(response.getheaders()), raw
        finally:
            connection.close()


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.in_title = False
        self.title = []
        self.text = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self.hidden += 1
        if tag == 'title':
            self.in_title = True
        if tag == 'a' and not self.hidden:
            href = dict(attrs).get('href', '')
            if href and len(self.links) < 100:
                self.links.append(href)

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'):
            self.hidden = max(0, self.hidden - 1)
        if tag == 'title':
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)
        elif not self.hidden and data.strip():
            self.text.append(data.strip())


def fetch_page(url):
    url = normalize_url(url)
    p = urlsplit(url)
    robots_url = urlunsplit((p.scheme, p.netloc, '/robots.txt', '', ''))
    status, headers, raw = read_url(robots_url)
    if status == 200:
        robots = RobotFileParser()
        robots.parse(raw.decode('utf-8', errors='replace').splitlines())
        if not robots.can_fetch(AGENT, url):
            raise FetchBlocked('robots.txt 禁止此 User-Agent 访问该路径，已停止采集')
        delay = robots.crawl_delay(AGENT)
        if delay and delay > 1:
            raise FetchBlocked('站点要求更长 crawl-delay，请使用专用调度适配器')
    elif status not in (404, 410):
        raise FetchBlocked(f'robots.txt 返回 HTTP {status}，无法确认访问规则；未请求目标页')
    policy_hash = hashlib.sha256(raw).hexdigest()
    status, headers, raw = read_url(url)
    if status != 200:
        raise FetchBlocked(f'目标返回 HTTP {status}；重定向、限流及访问拒绝不自动重试')
    content_type = next((v for k,v in headers.items() if k.lower() == 'content-type'), '')
    if not content_type.lower().startswith(('text/html', 'text/plain')):
        raise FetchBlocked('当前仅支持 HTML 或纯文本，不下载二进制或执行脚本')
    import re
    encoding = re.search(r'charset=([\w-]+)', content_type, re.I)
    charset = encoding.group(1) if encoding else 'utf-8'
    try:
        text = raw.decode(charset, errors='replace')
    except LookupError:
        text = raw.decode('utf-8', errors='replace')
    parser = PageParser()
    parser.feed(text)
    title = ' '.join(parser.title).strip()
    body = '\n'.join(parser.text) if 'html' in content_type else text
    if any(word in (title + body[:300]).lower() for word in ('captcha', '验证码', '安全验证', '访问验证', '请先登录', 'access denied')):
        raise FetchBlocked('页面包含验证码、登录或访问验证提示，已隔离，未发布为业务结果')
    links = list(dict.fromkeys(urljoin(url, href) for href in parser.links if urlsplit(urljoin(url, href)).scheme in ('http', 'https')))
    payload = dict(title=title or p.hostname, source_url=url, text=body[:20000], links=links, content_type=content_type, text_length=len(body))
    evidence = dict(uri=url, pointer='html/title + visible text', raw=text[:50000], raw_truncated=len(text)>50000, response_sha256=hashlib.sha256(raw).hexdigest(), http_status=status, robots_url=robots_url, robots_sha256=policy_hash, extractor_version='single-page-v1')
    return payload, evidence
