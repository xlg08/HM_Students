"""Explicit public API connectors. Never executes downloaded code."""
import hashlib
import json
import threading
import time
from urllib.request import build_opener, ProxyHandler, HTTPRedirectHandler, Request
from urllib.error import HTTPError, URLError

CATALOG = {
    "pypi-fastapi": "fastapi",
    "pypi-scrapy": "scrapy",
    "pypi-playwright": "playwright",
}
_lock = threading.Lock()
_last_request = 0.0


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def parse_metadata(document):
    info = document.get("info")
    if not isinstance(info, dict) or not isinstance(info.get("name"), str) or not info.get("version"):
        raise ValueError("PyPI ?????????????")
    files = document.get("urls", [])
    dates = [f.get("upload_time_iso_8601", "") for f in files if isinstance(f, dict)]
    return dict(title=info["name"] + " " + str(info["version"]), package=info["name"],
                version=info["version"], summary=info.get("summary") or "",
                requires_python=info.get("requires_python"), dependencies=info.get("requires_dist") or [],
                license_expression=info.get("license_expression"),
                published_at=min(filter(None, dates), default=None),
                source_url="https://pypi.org/project/" + info["name"] + "/")


def fetch_metadata(connector):
    global _last_request
    if connector not in CATALOG:
        raise ValueError("??????????")
    # A fixed HTTPS host and path; redirects/proxies disabled and TLS certificates verified.
    url = "https://pypi.org/pypi/" + CATALOG[connector] + "/json"
    with _lock:
        time.sleep(max(0, 1 - (time.monotonic() - _last_request)))
        _last_request = time.monotonic()
    request = Request(url, headers={"User-Agent": "AICrawl/1.2 (public package metadata)", "Accept": "application/json"})
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=8) as response:
            if response.headers.get_content_type() != "application/json":
                raise ValueError("????? JSON")
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError("???? 2MB ??")
            document = json.loads(raw)
    except HTTPError as exc:
        raise ValueError(f"PyPI HTTP {exc.code}??????????") from exc
    except URLError as exc:
        raise ValueError("PyPI ?????????????????") from exc
    return parse_metadata(document), dict(uri=url, pointer="/info", raw=document["info"],
        response_sha256=hashlib.sha256(raw).hexdigest(), http_status=200, extractor_version="pypi-json-v1")
