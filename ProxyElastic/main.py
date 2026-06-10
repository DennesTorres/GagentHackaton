import os

import requests
from flask import Request, Response

PROXY_SECRET = os.environ.get("PROXY_SECRET")
ELASTIC_API_KEY = os.environ.get("ELASTIC_API_KEY")

TARGET_URL = "https://my-elasticsearch-project-fb39e4.kb.europe-west1.gcp.elastic.cloud/api/agent_builder/mcp"
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


def _forward_headers(request_headers):
    if not ELASTIC_API_KEY:
        raise RuntimeError("Missing required configuration: ELASTIC_API_KEY")
    headers = {
        key: value
        for key, value in request_headers
        if key.lower() not in {"authorization", "content-length", "host", "x-proxy-secret"}
    }
    headers["Authorization"] = f"ApiKey {ELASTIC_API_KEY}"
    return headers


def _response_headers(upstream_headers):
    return {
        key: value
        for key, value in upstream_headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }


def proxy_elastic_request(request: Request):
    """Proxy Elastic MCP traffic."""
    incoming_secret = request.args.get("secret")
    if not PROXY_SECRET or incoming_secret != PROXY_SECRET:
        return Response("Unauthorized: Invalid or missing proxy secret", status=401)

    try:
        upstream = requests.request(
            method=request.method,
            url=TARGET_URL,
            headers=_forward_headers(request.headers),
            data=request.get_data(),
            allow_redirects=True,
            timeout=REQUEST_TIMEOUT,
        )
        return Response(
            upstream.content,
            status=upstream.status_code,
            headers=_response_headers(upstream.headers),
        )
    except RuntimeError as exc:
        return Response(str(exc), status=500)
    except requests.RequestException as exc:
        status = exc.response.status_code if exc.response is not None else None
        return Response(
            f"Upstream request failed{f' with HTTP {status}' if status else ''}",
            status=502,
        )
    except Exception as exc:
        return Response(f"Internal Server Error: {str(exc)}", status=500)
