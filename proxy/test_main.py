import importlib.util
import json
import os
import unittest
from unittest.mock import Mock, patch

from flask import Flask, request


os.environ["PROXY_SECRET"] = "test-secret"
spec = importlib.util.spec_from_file_location("proxy_main", os.path.join(os.path.dirname(__file__), "main.py"))
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)


class ProxyTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def post(self, payload, upstream=None):
        with self.app.test_request_context(
            "/?secret=test-secret",
            method="POST",
            json=payload,
            headers={"Accept": "application/json", "Mcp-Session-Id": "session-1"},
        ):
            patches = [patch.object(proxy, "get_entra_token", return_value="token")]
            if upstream is not None:
                patches.append(patch.object(proxy.requests, "request", return_value=upstream))
            for active_patch in patches:
                active_patch.start()
                self.addCleanup(active_patch.stop)
            return proxy.proxy_fabric_request(request)

    @staticmethod
    def upstream_json(payload, status=200, headers=None):
        response = Mock()
        response.status_code = status
        response.headers = {"Content-Type": "application/json", **(headers or {})}
        response.json.return_value = payload
        return response

    def test_tools_list_appends_valid_mcp_tools_and_preserves_session_header(self):
        upstream = self.upstream_json(
            {"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "upstream_tool"}]}},
            headers={"Mcp-Session-Id": "new-session"},
        )

        response = self.post({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, upstream)
        body = json.loads(response.get_data())

        self.assertEqual(["upstream_tool", "execute_notebook", "get_notebook_result", "list_item_job_instances"], [tool["name"] for tool in body["result"]["tools"]])
        self.assertIn("inputSchema", body["result"]["tools"][1])
        self.assertNotIn("function", body["result"]["tools"][1])
        self.assertEqual("new-session", response.headers["Mcp-Session-Id"])

    def test_tools_list_non_final_page_does_not_inject_local_tools(self):
        upstream = self.upstream_json(
            {"jsonrpc": "2.0", "id": 14, "result": {"tools": [{"name": "second_page_tool"}], "nextCursor": "next-page"}}
        )

        response = self.post(
            {"jsonrpc": "2.0", "id": 14, "method": "tools/list"},
            upstream,
        )
        body = json.loads(response.get_data())

        self.assertEqual(["second_page_tool"], [tool["name"] for tool in body["result"]["tools"]])

    def test_local_tool_call_is_not_forwarded(self):
        with patch.object(proxy, "execute_notebook", return_value={"status": 202, "location": "job-url"}), patch.dict(
            proxy.LOCAL_TOOL_HANDLERS, {"execute_notebook": proxy.execute_notebook}
        ), patch.object(proxy.requests, "request") as forwarded:
            response = self.post(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "execute_notebook", "arguments": {"workspaceId": "w", "notebookId": "n"}},
                }
            )

        body = json.loads(response.get_data())
        forwarded.assert_not_called()
        self.assertFalse(body["result"]["isError"])
        self.assertIn("job-url", body["result"]["content"][0]["text"])

    def test_remote_tool_call_is_forwarded_unchanged(self):
        upstream = self.upstream_json({"jsonrpc": "2.0", "id": 3, "result": {"content": []}})
        response = self.post(
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "upstream_tool", "arguments": {}}},
            upstream,
        )
        self.assertEqual(3, json.loads(response.get_data())["id"])

    def test_invalid_local_tool_arguments_return_invalid_params(self):
        response = self.post(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "execute_notebook", "arguments": {"workspaceId": "w"}},
            }
        )
        self.assertEqual(-32602, json.loads(response.get_data())["error"]["code"])

    def test_batch_tools_list_is_rewritten_without_crashing(self):
        upstream = self.upstream_json(
            [
                {"jsonrpc": "2.0", "id": 5, "result": {"tools": []}},
                {"jsonrpc": "2.0", "id": 6, "result": {"content": []}},
            ]
        )
        response = self.post(
            [
                {"jsonrpc": "2.0", "id": 5, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "upstream_tool", "arguments": {}}},
            ],
            upstream,
        )
        self.assertEqual(3, len(json.loads(response.get_data())[0]["result"]["tools"]))

    def test_execute_notebook_uses_documented_api_and_reads_async_headers(self):
        fabric_response = Mock()
        fabric_response.status_code = 202
        fabric_response.headers = {"Location": "job-url", "Retry-After": "60"}
        with patch.object(proxy, "get_entra_token", return_value="token"), patch.object(
            proxy.requests, "post", return_value=fabric_response
        ) as post:
            result = proxy.execute_notebook("workspace", "notebook")

        post.assert_called_once_with(
            "https://api.fabric.microsoft.com/v1/workspaces/workspace/notebooks/notebook/jobs/execute/instances?jobType=RunNotebook",
            headers={"Authorization": "Bearer token"},
            timeout=proxy.REQUEST_TIMEOUT,
        )
        self.assertEqual({"status": 202, "location": "job-url", "retryAfter": "60"}, result)

    def test_get_notebook_result_uses_item_and_job_instance_ids(self):
        fabric_response = Mock()
        fabric_response.json.return_value = {"status": "Completed"}
        with patch.object(proxy, "get_entra_token", return_value="token"), patch.object(
            proxy.requests, "get", return_value=fabric_response
        ) as get:
            result = proxy.get_notebook_result("workspace", "notebook", "job")

        get.assert_called_once_with(
            "https://api.fabric.microsoft.com/v1/workspaces/workspace/notebooks/notebook/jobs/execute/instances/job",
            headers={"Authorization": "Bearer token"},
            timeout=proxy.REQUEST_TIMEOUT,
        )
        self.assertEqual("Completed", result["status"])

    def test_list_item_job_instances_calls_correct_url(self):
        fabric_response = Mock()
        fabric_response.json.return_value = {"value": [{"id": "job-1"}]}
        with patch.object(proxy, "get_entra_token", return_value="token"), patch.object(
            proxy.requests, "get", return_value=fabric_response
        ) as get:
            result = proxy.list_item_job_instances("workspace", "item")

        get.assert_called_once_with(
            "https://api.fabric.microsoft.com/v1/workspaces/workspace/items/item/jobs/instances",
            headers={"Authorization": "Bearer token"},
            params={},
            timeout=proxy.REQUEST_TIMEOUT,
        )
        self.assertEqual("job-1", result["value"][0]["id"])

    def test_list_item_job_instances_passes_continuation_token(self):
        fabric_response = Mock()
        fabric_response.json.return_value = {"value": []}
        with patch.object(proxy, "get_entra_token", return_value="token"), patch.object(
            proxy.requests, "get", return_value=fabric_response
        ) as get:
            proxy.list_item_job_instances("workspace", "item", continuationToken="tok")

        get.assert_called_once_with(
            "https://api.fabric.microsoft.com/v1/workspaces/workspace/items/item/jobs/instances",
            headers={"Authorization": "Bearer token"},
            params={"continuationToken": "tok"},
            timeout=proxy.REQUEST_TIMEOUT,
        )


if __name__ == "__main__":
    unittest.main()
