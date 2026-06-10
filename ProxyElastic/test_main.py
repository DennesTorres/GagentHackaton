import importlib.util
import os
import unittest
from unittest.mock import Mock, patch

from flask import Flask, request


os.environ["PROXY_SECRET"] = "test-secret"
os.environ["ELASTIC_API_KEY"] = "test-api-key"

spec = importlib.util.spec_from_file_location("proxy_elastic", os.path.join(os.path.dirname(__file__), "main.py"))
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)


class ProxyElasticTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def post(self, upstream=None, secret="test-secret"):
        with self.app.test_request_context(
            f"/?secret={secret}",
            method="POST",
            data=b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}',
            headers={"Content-Type": "application/json"},
        ):
            if upstream is not None:
                patcher = patch.object(proxy.requests, "request", return_value=upstream)
                patcher.start()
                self.addCleanup(patcher.stop)
            return proxy.proxy_elastic_request(request)

    @staticmethod
    def upstream_response(content=b'{}', status=200, headers=None):
        r = Mock()
        r.status_code = status
        r.headers = {"Content-Type": "application/json", **(headers or {})}
        r.content = content
        return r

    def test_wrong_secret_returns_401(self):
        response = self.post(upstream=self.upstream_response(), secret="wrong")
        self.assertEqual(401, response.status_code)

    def test_request_forwarded_with_api_key_auth(self):
        upstream = self.upstream_response()
        with patch.object(proxy.requests, "request", return_value=upstream) as mock_req:
            with self.app.test_request_context("/?secret=test-secret", method="POST", data=b'{}'):
                proxy.proxy_elastic_request(request)
        self.assertEqual("ApiKey test-api-key", mock_req.call_args[1]["headers"]["Authorization"])

    def test_upstream_status_code_preserved(self):
        response = self.post(upstream=self.upstream_response(status=404))
        self.assertEqual(404, response.status_code)

    def test_hop_by_hop_headers_stripped_from_response(self):
        upstream = self.upstream_response(headers={"Transfer-Encoding": "chunked", "X-Custom": "keep"})
        response = self.post(upstream=upstream)
        self.assertNotIn("Transfer-Encoding", response.headers)
        self.assertIn("X-Custom", response.headers)

    def test_upstream_authorization_header_is_not_forwarded(self):
        upstream = self.upstream_response()
        with patch.object(proxy.requests, "request", return_value=upstream) as mock_req:
            with self.app.test_request_context(
                "/?secret=test-secret",
                method="POST",
                data=b'{}',
                headers={"Authorization": "Bearer client-token"},
            ):
                proxy.proxy_elastic_request(request)
        forwarded = mock_req.call_args[1]["headers"]
        self.assertEqual("ApiKey test-api-key", forwarded["Authorization"])


if __name__ == "__main__":
    unittest.main()
