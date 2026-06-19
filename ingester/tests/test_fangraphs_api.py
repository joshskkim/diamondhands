"""Unit tests for the FanGraphs projection fetcher (curl_cffi monkeypatched)."""
from __future__ import annotations

import sys
import types
import unittest

from ingester import fangraphs_api


class _FakeResp:
    def __init__(self, payload, content_type="application/json; charset=utf-8", status=200):
        self._payload = payload
        self.headers = {"content-type": content_type}
        self.status_code = status

    def json(self):
        return self._payload


def _install_fake_curl(get):
    """Inject a fake curl_cffi.requests module so fetch_projection's lazy import resolves."""
    mod = types.ModuleType("curl_cffi")
    req = types.ModuleType("curl_cffi.requests")
    req.get = get
    mod.requests = req
    sys.modules["curl_cffi"] = mod
    sys.modules["curl_cffi.requests"] = req


class TestFetchProjection(unittest.TestCase):
    def tearDown(self):
        sys.modules.pop("curl_cffi", None)
        sys.modules.pop("curl_cffi.requests", None)

    def test_systems_constant(self):
        self.assertEqual(
            fangraphs_api.SYSTEMS,
            ("steamer", "thebatx", "thebat", "atc", "fangraphsdc", "zips", "oopsy"),
        )

    def test_returns_dataframe_with_passthrough_columns(self):
        payload = [{"PlayerName": "Aaron Judge", "xMLBAMID": 592450,
                    "wOBA": 0.41, "ISO": 0.30, "K%": 0.25, "PA": 633}]
        _install_fake_curl(lambda *a, **k: _FakeResp(payload))
        df = fangraphs_api.fetch_projection("steamer")
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["xMLBAMID"], 592450)
        self.assertIn("wOBA", df.columns)

    def test_raises_on_cloudflare_html(self):
        _install_fake_curl(
            lambda *a, **k: _FakeResp("<html>Just a moment...</html>",
                                      content_type="text/html", status=403)
        )
        with self.assertRaises(RuntimeError):
            fangraphs_api.fetch_projection("steamer")


if __name__ == "__main__":
    unittest.main()
