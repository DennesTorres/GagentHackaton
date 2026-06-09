import json
import os
from collections.abc import Iterable

import requests
from flask import Request, Response, jsonify, stream_with_context
from msal import ConfidentialClientApplication


PROXY_SECRET = os.environ.get("PROXY_SECRET")
AZURE_TENANT_ID = os.environ.get("AZURE_TENANT_ID")
AZURE_CLIENT_ID = os.environ.get("AZURE_CLIENT_ID")
AZURE_CLIENT_SECRET = os.environ.get("AZURE_CLIENT_SECRET")

SCOPE = ["https://api.fabric.microsoft.com/.default"]
FABRIC_API_BASE_URL = "https://api.fabric.microsoft.com/v1"
TARGET_BASE_URL = f"{FABRIC_API_BASE_URL}/mcp/core"
REQUEST_TIMEOUT = (
    float(os.environ.get("HTTP_CONNECT_TIMEOUT_SECONDS", "10")),
    float(os.environ.get("HTTP_READ_TIMEOUT_SECONDS", "300")),
)

NOTEBOOK_TOOLS = [
    {
        "name": "execute_notebook",
        "description": "Starts a Microsoft Fabric notebook execution.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspaceId": {"type": "string", "description": "The workspace UUID."},
                "notebookId": {"type": "string", "description": "The notebook UUID."},
            },
            "required": ["workspaceId", "notebookId"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_notebook_result",
        "description": "Gets the current status and result metadata for a notebook execution.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspaceId": {"type": "string", "description": "The workspace UUID."},
                "notebookId": {"type": "string", "description": "The notebook UUID."},
                "jobInstanceId": {"type": "string", "description": "The job instance UUID."},
            },
            "required": ["workspaceId", "notebookId", "jobInstanceId"],
            "additionalProperties": False,
        },
    },
]

LOCAL_TOOL_HANDLERS = {}
HOP_BY_HOP_HEADERS = {
    "connection",
    "content-encoding",
    "content-length",
    "keep-alive",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


def get_entra_token():
    """Acquire an OAuth 2.0 token using the client credentials flow."""
    missing = [
        name
        for name, value in (
            ("AZURE_TENANT_ID", AZURE_TENANT_ID),
            ("AZURE_CLIENT_ID", AZURE_CLIENT_ID),
            ("AZURE_CLIENT_SECRET", AZURE_CLIENT_SECRET),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing required configuration: {', '.join(missing)}")

    authority = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}"
    app = ConfidentialClientApplication(
        AZURE_CLIENT_ID,
        authority=authority,
        client_credential=AZURE_CLIENT_SECRET,
    )
    result = app.acquire_token_for_client(scopes=SCOPE)
    if "access_token" not in result:
        message = result.get("error_description") or result.get("error") or "unknown token error"
        raise RuntimeError(f"Could not acquire token: {message}")
    return result["access_token"]


def _fabric_headers():
    return {"Authorization": f"Bearer {get_entra_token()}"}


def execute_notebook(workspaceId: str, notebookId: str):
    """Start a notebook execution and return the asynchronous job metadata."""
    url = (
        f"{FABRIC_API_BASE_URL}/workspaces/{workspaceId}/notebooks/{notebookId}"
        "/jobs/execute/instances?beta=false"
    )
    response = requests.post(url, headers=_fabric_headers(), timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return {
        "status": response.status_code,
        "location": response.headers.get("Location"),
        "retryAfter": response.headers.get("Retry-After"),
    }


def get_notebook_result(workspaceId: str, notebookId: str, jobInstanceId: str):
    """Get one notebook job instance."""
    url = (
        f"{FABRIC_API_BASE_URL}/workspaces/{workspaceId}/items/{notebookId}"
        f"/jobs/instances/{jobInstanceId}"
    )
    response = requests.get(url, headers=_fabric_headers(), timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


LOCAL_TOOL_HANDLERS.update(
    {
        "execute_notebook": execute_notebook,
        "get_notebook_result": get_notebook_result,
    }
)


def _json_rpc_error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _tool_result(request_id, result=None, error=None):
    is_error = error is not None
    text = error if is_error else json.dumps(result)
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {"content": [{"type": "text", "text": text}], "isError": is_error},
    }


def _handle_local_tool_call(message):
    params = message.get("params")
    if not isinstance(params, dict):
        return _json_rpc_error(message.get("id"), -32602, "Invalid tools/call params")

    tool_name = params.get("name")
    handler = LOCAL_TOOL_HANDLERS.get(tool_name)
    if handler is None:
        return None

    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        return _json_rpc_error(message.get("id"), -32602, "Tool arguments must be an object")

    schema = next(tool for tool in NOTEBOOK_TOOLS if tool["name"] == tool_name)["inputSchema"]
    required = schema["required"]
    missing = [name for name in required if not arguments.get(name)]
    unexpected = sorted(set(arguments) - set(schema["properties"]))
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected: {', '.join(unexpected)}")
        return _json_rpc_error(message.get("id"), -32602, f"Invalid tool arguments ({'; '.join(details)})")

    try:
        return _tool_result(message.get("id"), result=handler(**arguments))
    except requests.RequestException as exc:
        status = exc.response.status_code if exc.response is not None else None
        detail = f"Fabric API request failed{f' with HTTP {status}' if status else ''}"
        return _tool_result(message.get("id"), error=detail)
    except Exception:
        return _tool_result(message.get("id"), error="Local tool execution failed")


def _is_local_tool_call(message):
    return (
        isinstance(message, dict)
        and message.get("method") == "tools/call"
        and isinstance(message.get("params"), dict)
        and message["params"].get("name") in LOCAL_TOOL_HANDLERS
    )


def _tools_list_request_ids(payload):
    messages = payload if isinstance(payload, list) else [payload]
    return {
        message.get("id")
        for message in messages
        if (
            isinstance(message, dict)
            and message.get("method") == "tools/list"
            and (
                not isinstance(message.get("params"), dict)
                or not message["params"].get("cursor")
            )
        )
    }


def _initialize_request_ids(payload):
    messages = payload if isinstance(payload, list) else [payload]
    return {
        message.get("id")
        for message in messages
        if isinstance(message, dict) and message.get("method") == "initialize"
    }


def _inject_local_capabilities(payload, initialize_ids):
    responses = payload if isinstance(payload, list) else [payload]
    for response in responses:
        if not isinstance(response, dict) or response.get("id") not in initialize_ids:
            continue
        result = response.get("result")
        if not isinstance(result, dict):
            continue
        capabilities = result.setdefault("capabilities", {})
        if isinstance(capabilities, dict):
            capabilities.setdefault("tools", {"listChanged": False})
    return payload


def _inject_local_tools(payload, tools_list_ids, initialize_ids=frozenset()):
    _inject_local_capabilities(payload, initialize_ids)
    responses = payload if isinstance(payload, list) else [payload]
    for response in responses:
        if not isinstance(response, dict) or response.get("id") not in tools_list_ids:
            continue
        result = response.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
            continue
        existing_names = {
            tool.get("name") for tool in result["tools"] if isinstance(tool, dict)
        }
        result["tools"].extend(
            tool for tool in NOTEBOOK_TOOLS if tool["name"] not in existing_names
        )
    return payload


def _forward_headers(request_headers):
    headers = {
        key: value
        for key, value in request_headers
        if key.lower() not in {"authorization", "content-length", "host", "x-proxy-secret"}
    }
    headers["Authorization"] = f"Bearer {get_entra_token()}"
    return headers


def _response_headers(upstream_headers):
    return {
        key: value
        for key, value in upstream_headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }


def _rewrite_sse_events(chunks: Iterable[bytes], tools_list_ids, initialize_ids, local_responses):
    buffer = b""
    try:
        for chunk in chunks:
            buffer = (buffer + chunk).replace(b"\r\n", b"\n")
            while b"\n\n" in buffer:
                event, buffer = buffer.split(b"\n\n", 1)
                yield _rewrite_sse_event(event, tools_list_ids, initialize_ids) + b"\n\n"
        if buffer:
            yield _rewrite_sse_event(buffer, tools_list_ids, initialize_ids)
        for response in local_responses:
            yield f"event: message\ndata: {json.dumps(response)}\n\n".encode()
    finally:
        close = getattr(chunks, "close", None)
        if close:
            close()


def _rewrite_sse_event(event, tools_list_ids, initialize_ids):
    lines = event.splitlines()
    data_lines = [line[5:].lstrip() for line in lines if line.startswith(b"data:")]
    if not data_lines:
        return event
    try:
        payload = json.loads(b"\n".join(data_lines))
        rewritten = json.dumps(_inject_local_tools(payload, tools_list_ids, initialize_ids)).encode()
    except (TypeError, ValueError):
        return event
    other_lines = [line for line in lines if not line.startswith(b"data:")]
    return b"\n".join(other_lines + [b"data: " + rewritten])


def _json_response(payload, status, headers):
    headers = {key: value for key, value in headers.items() if key.lower() != "content-type"}
    headers["Content-Type"] = "application/json"
    return Response(
        json.dumps(payload),
        status=status,
        headers=headers,
    )


def _proxy_upstream(request, payload, local_responses):
    tools_list_ids = _tools_list_request_ids(payload)
    initialize_ids = _initialize_request_ids(payload)
    upstream = requests.request(
        method=request.method,
        url=TARGET_BASE_URL,
        headers=_forward_headers(request.headers),
        data=json.dumps(payload).encode() if payload is not None else request.get_data(),
        allow_redirects=False,
        stream=True,
        timeout=REQUEST_TIMEOUT,
    )
    headers = _response_headers(upstream.headers)
    content_type = upstream.headers.get("Content-Type", "").lower()

    if "application/json" in content_type:
        try:
            result = _inject_local_tools(upstream.json(), tools_list_ids, initialize_ids)
            if local_responses:
                result = result if isinstance(result, list) else [result]
                result.extend(local_responses)
            upstream.close()
            return _json_response(result, upstream.status_code, headers)
        except (TypeError, ValueError):
            pass

    if "text/event-stream" in content_type:
        def upstream_sse_chunks():
            try:
                yield from upstream.iter_content(chunk_size=8192)
            finally:
                upstream.close()

        body = _rewrite_sse_events(
            upstream_sse_chunks(),
            tools_list_ids,
            initialize_ids,
            local_responses,
        )
        return Response(
            stream_with_context(body),
            status=upstream.status_code,
            headers=headers,
            direct_passthrough=True,
        )

    if local_responses:
        upstream.close()
        return _json_response(
            _json_rpc_error(None, -32603, "Cannot combine local tool results with upstream response"),
            502,
            headers,
        )

    def stream_upstream():
        try:
            yield from upstream.iter_content(chunk_size=8192)
        finally:
            upstream.close()

    return Response(
        stream_with_context(stream_upstream()),
        status=upstream.status_code,
        headers=headers,
        direct_passthrough=True,
    )


def proxy_fabric_request(request: Request):
    """Proxy Fabric MCP traffic while aggregating proxy-owned notebook tools."""
    incoming_secret = request.args.get("secret") or request.headers.get("X-Proxy-Secret")
    if not PROXY_SECRET or incoming_secret != PROXY_SECRET:
        return jsonify(_json_rpc_error(None, -32000, "Invalid or missing proxy secret")), 401

    payload = request.get_json(silent=True)
    messages = payload if isinstance(payload, list) else [payload]
    local_responses = []
    upstream_messages = []
    handled_local_message = False

    for message in messages:
        if _is_local_tool_call(message):
            handled_local_message = True
            response = _handle_local_tool_call(message)
            if response is not None and message.get("id") is not None:
                local_responses.append(response)
        else:
            upstream_messages.append(message)

    if local_responses and not upstream_messages:
        result = local_responses if isinstance(payload, list) else local_responses[0]
        return _json_response(result, 200, {})

    if handled_local_message and not upstream_messages:
        return Response(status=202)

    upstream_payload = upstream_messages if isinstance(payload, list) else payload
    try:
        return _proxy_upstream(request, upstream_payload, local_responses)
    except requests.RequestException as exc:
        status = exc.response.status_code if exc.response is not None else None
        message = f"Upstream MCP request failed{f' with HTTP {status}' if status else ''}"
        return jsonify(_json_rpc_error(None, -32603, message)), 502
    except Exception:
        return jsonify(_json_rpc_error(None, -32603, "Internal proxy error")), 500
