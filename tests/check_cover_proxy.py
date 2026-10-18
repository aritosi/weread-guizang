#!/usr/bin/env python3
"""Offline cover proxy regression tests; never use the user's library or network."""
import concurrent.futures
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = tempfile.mkdtemp(prefix="guizang-cover-proxy-")
os.environ["GUIZANG_DATA"] = os.path.join(ROOT, "cache")
os.environ["GUIZANG_BOOKS"] = os.path.join(ROOT, "books")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ui_server

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 2000
URL = "https://wfqqreader-1252317822.image.myqcloud.com/cover/1.jpg"


class Response:
    def __init__(self, body=PNG, headers=None):
        self.body = body
        self.headers = headers or {}
        self.read_limit = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        self.read_limit = limit
        return self.body[:limit]


class CoverProxyTests(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(ui_server.COVER_DIR, ignore_errors=True)
        os.makedirs(ui_server.COVER_DIR, exist_ok=True)
        ui_server._cover_failed.clear()
        self.guard = patch.object(ui_server.clip_article, "ensure_redirect_guard")
        self.guard.start()

    def tearDown(self):
        self.guard.stop()

    def test_public_proxy_restricts_tencent_hosts(self):
        for url in (URL, "https://mmbiz.qpic.cn/1", "http://shp.qpic.cn/2",
                    "https://wfqqreader.com/1", "https://cdn.gtimg.cn/1"):
            self.assertTrue(ui_server._weread_cover_url(url), url)
        for url in ("http://127.0.0.1/", "https://qpic.cn.evil.test/1",
                    "https://evilqpic.cn/1", "https://your-user@qpic.cn/1",
                    "https://qpic.cn:8770/1", "file:///tmp/image"):
            self.assertFalse(ui_server._weread_cover_url(url), url)

    def test_cache_hit_has_no_network(self):
        with patch.object(ui_server.urllib.request, "urlopen", return_value=Response()) as net:
            first = ui_server.fetch_cover_url(URL)
            self.assertIsNotNone(first)
            self.assertEqual(first[1], "image/png")
            self.assertEqual(ui_server.fetch_cover_url(URL), first)
            self.assertEqual(net.call_count, 1)

    def test_rejects_non_image_and_backs_off(self):
        with patch.object(ui_server.urllib.request, "urlopen",
                          return_value=Response(b"<html>" + b"x" * 2000,
                                                {"Content-Type": "image/jpeg"})) as net:
            self.assertIsNone(ui_server.fetch_cover_url(URL))
            self.assertIsNone(ui_server.fetch_cover_url(URL))
            self.assertEqual(net.call_count, 1)
            self.assertFalse(os.path.exists(ui_server.cover_url_path(URL)))
        ui_server._cover_failed[URL] = 0
        with patch.object(ui_server.urllib.request, "urlopen", return_value=Response()):
            self.assertIsNotNone(ui_server.fetch_cover_url(URL))

    def test_oversized_payload_is_not_cached(self):
        response = Response(PNG + b"x" * ui_server._COVER_MAX_BYTES)
        with patch.object(ui_server.urllib.request, "urlopen", return_value=response):
            self.assertIsNone(ui_server.fetch_cover_url(URL))
        self.assertEqual(response.read_limit, ui_server._COVER_MAX_BYTES + 1)
        self.assertFalse(os.path.exists(ui_server.cover_url_path(URL)))

    def test_oversized_content_length_not_read(self):
        response = Response(headers={"Content-Length": str(ui_server._COVER_MAX_BYTES + 1)})
        with patch.object(ui_server.urllib.request, "urlopen", return_value=response):
            self.assertIsNone(ui_server.fetch_cover_url(URL))
        self.assertIsNone(response.read_limit)

    def test_concurrent_same_image_only_downloads_once(self):
        entered = threading.Event()
        release = threading.Event()
        def download(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(3))
            return Response()
        with patch.object(ui_server.urllib.request, "urlopen", side_effect=download) as net:
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                futures = [pool.submit(ui_server.fetch_cover_url, URL) for _ in range(8)]
                self.assertTrue(entered.wait(3))
                release.set()
                results = [f.result(4) for f in futures]
            self.assertEqual(net.call_count, 1)
            self.assertTrue(all(r == results[0] and r is not None for r in results))

    def test_local_url_rejected_before_network(self):
        with patch.object(ui_server.urllib.request, "urlopen") as net:
            self.assertIsNone(ui_server.fetch_cover_url("http://127.0.0.1/private.jpg"))
            net.assert_not_called()

    def test_redirect_to_local_url_stays_blocked(self):
        req = ui_server.urllib.request.Request("https://shp.qpic.cn/image")
        with self.assertRaises(ui_server.urllib.error.HTTPError):
            ui_server.clip_article.RedirectGuard().redirect_request(
                req, None, 302, "Found", {}, "http://127.0.0.1/private.jpg")


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        shutil.rmtree(ROOT, ignore_errors=True)
