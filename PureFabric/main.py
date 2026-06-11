import json
import os

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


def _json_rpc_error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


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


def _json_response(payload, status, headers):
    headers = {key: value for key, value in headers.items() if key.lower() != "content-type"}
    headers["Content-Type"] = "application/json"
    return Response(
        json.dumps(payload),
        status=status,
        headers=headers,
    )


def _proxy_upstream(request, payload):
    upstream = requests.request(
        method=request.method,
        url=TARGET_BASE_URL,
        headers=_forward_headers(request.headers),
        data=json.dumps(payload).encode() if payload is not None else request.get_data(),
        allow_redirects=True,
        stream=True,
        timeout=REQUEST_TIMEOUT,
    )
    headers = _response_headers(upstream.headers)
    content_type = upstream.headers.get("Content-Type", "").lower()

    if "application/json" in content_type:
        try:
            result = upstream.json()
            upstream.close()
            return _json_response(result, upstream.status_code, headers)
        except (TypeError, ValueError):
            pass

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


def proxy_pure_fabric_request(request: Request):
    """Pure passthrough proxy for Fabric MCP traffic."""
    incoming_secret = request.args.get("secret")
    if not PROXY_SECRET or incoming_secret != PROXY_SECRET:
        return jsonify(_json_rpc_error(None, -32000, "Invalid or missing proxy secret")), 401

    payload = request.get_json(silent=True)

    try:
        return _proxy_upstream(request, payload)
    except requests.RequestException as exc:
        status = exc.response.status_code if exc.response is not None else None
        message = f"Upstream MCP request failed{f' with HTTP {status}' if status else ''}"
        return jsonify(_json_rpc_error(None, -32603, message)), 502
    except Exception:
        return jsonify(_json_rpc_error(None, -32603, "Internal proxy error")), 500
