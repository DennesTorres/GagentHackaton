import datetime
import json
import os

import requests
from flask import Request, Response

# ── Configuration ──────────────────────────────────────────────────────────────

PROXY_SECRET = os.environ.get("PROXY_SECRET")
ELASTIC_API_KEY = os.environ.get("ELASTIC_API_KEY")
KIBANA_URL = os.environ.get("KIBANA_URL")
ELASTICSEARCH_URL = os.environ.get("ELASTICSEARCH_URL", "").rstrip("/")
REQUEST_TIMEOUT = (
    float(os.environ.get("HTTP_CONNECT_TIMEOUT_SECONDS", "10")),
    float(os.environ.get("HTTP_READ_TIMEOUT_SECONDS", "300")),
)
SAVE_RULE_TIMEOUT = (10, 60)

HOP_BY_HOP_HEADERS = {
    "connection", "content-encoding", "content-length",
    "keep-alive", "te", "trailers", "transfer-encoding", "upgrade",
}

# ── Local tool definitions ─────────────────────────────────────────────────────

ELASTIC_TOOLS = [
    {
        "name": "save_rule",
        "description": (
            "Save a governance rule into the governance-rules index. "
            "Creates version 1 for a new rule_id, or the next version for an existing rule_id "
            "and marks all previous versions as not current. "
            "The version number is computed automatically — never pass it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "rule_id":     {"type": "string", "description": "Stable rule identifier, e.g. 'lakehouse-naming-001'"},
                "name":        {"type": "string"},
                "description": {"type": "string"},
                "nl_intent":   {"type": "string", "description": "Natural-language statement of the rule's intent. Plain text — embedding happens server-side."},
                "frl_code":    {"type": "string", "description": "The FRL source of the rule"},
                "tags":        {"type": "array", "items": {"type": "string"}},
                "created_by":  {"type": "string"},
            },
            "required": ["rule_id", "name", "nl_intent", "frl_code"],
            "additionalProperties": False,
        },
        "annotations": {"title": "Save Rule", "readOnlyHint": False, "destructiveHint": False},
    },
    {
        "name": "save_results",
        "description": (
            "Bulk-index governance check results into the governance-results index. "
            "Send all results for a single policy-check run in one call. "
            "Each item becomes one document; the doc ID is {run_id}_{rule_id}_{item_id}. "
            "run_id and run_timestamp are injected into every document automatically."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {
                    "type": "string",
                    "description": "Unique identifier for this policy-check run, e.g. a UUID.",
                },
                "results": {
                    "type": "array",
                    "description": "Array of result objects. Each must include rule_id and item_id; all other fields are stored as-is.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "rule_id":  {"type": "string"},
                            "item_id":  {"type": "string"},
                            "status":   {"type": "string", "description": "e.g. 'pass', 'fail', 'warning'"},
                        },
                        "required": ["rule_id", "item_id"],
                        "additionalProperties": True,
                    },
                },
                "run_timestamp": {
                    "type": "string",
                    "description": "ISO-8601 UTC timestamp for the run. Defaults to now if omitted.",
                },
            },
            "required": ["run_id", "results"],
            "additionalProperties": False,
        },
        "annotations": {"title": "Save Results", "readOnlyHint": False, "destructiveHint": False},
    },
]

LOCAL_TOOL_HANDLERS = {}

# ── Exceptions ─────────────────────────────────────────────────────────────────

class _ElasticToolError(Exception):
    def __init__(self, step, status, error):
        self.step = step
        self.status = status
        self.error = error


class _ElasticBulkError(Exception):
    def __init__(self, json_text):
        self.json_text = json_text

# ── Helper functions ───────────────────────────────────────────────────────────

def _es_headers():
    return {
        "Authorization": f"ApiKey {ELASTIC_API_KEY}",
        "Content-Type": "application/json",
    }


def _forward_headers(request_headers):
    missing = [name for name, val in (("ELASTIC_API_KEY", ELASTIC_API_KEY), ("KIBANA_URL", KIBANA_URL)) if not val]
    if missing:
        raise RuntimeError(f"Missing required configuration: {', '.join(missing)}")
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


def _json_response(payload, status, headers):
    headers = {key: value for key, value in headers.items() if key.lower() != "content-type"}
    headers["Content-Type"] = "application/json"
    return Response(json.dumps(payload), status=status, headers=headers)


def _tool_result(request_id, result=None, error=None):
    is_error = error is not None
    text = error if is_error else json.dumps(result)
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {"content": [{"type": "text", "text": text}], "isError": is_error},
    }


def _inject_local_tools(payload):
    responses = payload if isinstance(payload, list) else [payload]
    for response in responses:
        if not isinstance(response, dict):
            continue
        result = response.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
            continue
        if result.get("nextCursor"):
            continue
        existing = {tool.get("name") for tool in result["tools"] if isinstance(tool, dict)}
        result["tools"].extend(tool for tool in ELASTIC_TOOLS if tool["name"] not in existing)
    return payload


def _is_local_tool_call(message):
    return (
        isinstance(message, dict)
        and message.get("method") == "tools/call"
        and isinstance(message.get("params"), dict)
        and message["params"].get("name") in LOCAL_TOOL_HANDLERS
    )


def _handle_local_tool_call(message):
    params = message.get("params")
    if not isinstance(params, dict):
        err = json.dumps({"saved": False, "step": "parse", "status": None, "error": "Invalid params"})
        return _tool_result(message.get("id"), error=err)

    tool_name = params.get("name")
    handler = LOCAL_TOOL_HANDLERS.get(tool_name)
    if handler is None:
        return None

    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        err = json.dumps({"saved": False, "step": "parse", "status": None, "error": "Tool arguments must be an object"})
        return _tool_result(message.get("id"), error=err)

    try:
        return _tool_result(message.get("id"), result=handler(**arguments))
    except _ElasticToolError as exc:
        err = json.dumps({"saved": False, "step": exc.step, "status": exc.status, "error": exc.error})
        return _tool_result(message.get("id"), error=err)
    except _ElasticBulkError as exc:
        return _tool_result(message.get("id"), error=exc.json_text)
    except Exception as exc:
        err = json.dumps({"saved": False, "step": "unknown", "status": None, "error": str(exc)[:500]})
        return _tool_result(message.get("id"), error=err)

# ── Tool implementations ───────────────────────────────────────────────────────

def save_rule(rule_id, name, nl_intent, frl_code, description=None, tags=None, created_by=None, **_):
    if not ELASTICSEARCH_URL:
        raise _ElasticToolError("setup", None, "ELASTICSEARCH_URL is not configured")

    # Call 1 — find the current max version for this rule_id
    try:
        search_resp = requests.post(
            f"{ELASTICSEARCH_URL}/governance-rules/_search",
            headers=_es_headers(),
            json={
                "query": {"term": {"rule_id": rule_id}},
                "sort": [{"version": "desc"}],
                "size": 1,
                "_source": ["version"],
            },
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise _ElasticToolError("search", None, str(exc)[:500]) from exc
    if search_resp.status_code >= 400:
        raise _ElasticToolError("search", search_resp.status_code, search_resp.text[:500])

    hits = search_resp.json().get("hits", {}).get("hits", [])
    version = (hits[0]["_source"]["version"] + 1) if hits else 1

    # Call 2 — retire previous current version (only when one exists)
    if hits:
        try:
            retire_resp = requests.post(
                f"{ELASTICSEARCH_URL}/governance-rules/_update_by_query?refresh=true",
                headers=_es_headers(),
                json={
                    "query": {
                        "bool": {
                            "must": [
                                {"term": {"rule_id": rule_id}},
                                {"term": {"is_current": True}},
                            ]
                        }
                    },
                    "script": {"source": "ctx._source.is_current = false"},
                },
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise _ElasticToolError("retire", None, str(exc)[:500]) from exc
        if retire_resp.status_code >= 400:
            raise _ElasticToolError("retire", retire_resp.status_code, retire_resp.text[:500])

    # Call 3 — index the new version (60 s timeout: nl_intent is semantic_text, ELSER may be lazy-allocated)
    doc_id = f"{rule_id}_v{version}"
    created_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        index_resp = requests.put(
            f"{ELASTICSEARCH_URL}/governance-rules/_doc/{doc_id}?refresh=wait_for",
            headers=_es_headers(),
            json={
                "rule_id":     rule_id,
                "version":     version,
                "is_current":  True,
                "name":        name,
                "description": description or "",
                "nl_intent":   nl_intent,
                "frl_code":    frl_code,
                "tags":        tags or [],
                "created_at":  created_at,
                "created_by":  created_by or "frl-copilot",
            },
            timeout=SAVE_RULE_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise _ElasticToolError("index", None, str(exc)[:500]) from exc
    if index_resp.status_code >= 400:
        raise _ElasticToolError("index", index_resp.status_code, index_resp.text[:500])

    es = index_resp.json()
    return {"saved": True, "doc_id": es["_id"], "version": version, "result": es.get("result", "")}


LOCAL_TOOL_HANDLERS["save_rule"] = save_rule


def save_results(run_id, results, run_timestamp=None, **_):
    if not ELASTICSEARCH_URL:
        raise _ElasticBulkError(json.dumps({"saved": False, "indexed": 0, "errors": ["ELASTICSEARCH_URL is not configured"], "status": None}))

    if not results:
        raise _ElasticBulkError(json.dumps({"saved": False, "indexed": 0, "errors": ["results array is empty"], "status": None}))

    if run_timestamp is None:
        run_timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines = []
    for item in results:
        rule_id = item.get("rule_id", "")
        item_id = item.get("item_id", "")
        doc_id = f"{run_id}_{rule_id}_{item_id}"
        lines.append(json.dumps({"index": {"_index": "governance-results", "_id": doc_id}}))
        lines.append(json.dumps({**item, "run_id": run_id, "run_timestamp": run_timestamp}))

    bulk_body = "\n".join(lines) + "\n"

    try:
        resp = requests.post(
            f"{ELASTICSEARCH_URL}/_bulk",
            headers={
                "Authorization": f"ApiKey {ELASTIC_API_KEY}",
                "Content-Type": "application/x-ndjson",
            },
            data=bulk_body.encode("utf-8"),
            timeout=SAVE_RULE_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise _ElasticBulkError(json.dumps({"saved": False, "indexed": 0, "errors": [str(exc)[:500]], "status": None})) from exc

    if resp.status_code >= 400:
        raise _ElasticBulkError(json.dumps({"saved": False, "indexed": 0, "errors": [resp.text[:500]], "status": resp.status_code}))

    body = resp.json()
    if body.get("errors"):
        ok_count = 0
        error_msgs = []
        for item_result in body.get("items", []):
            action_result = item_result.get("index", {})
            if action_result.get("status", 0) < 400:
                ok_count += 1
            else:
                err_info = action_result.get("error", {})
                error_msgs.append(f"{action_result.get('_id', '?')}: {err_info.get('type', '?')} – {err_info.get('reason', '?')}")
        raise _ElasticBulkError(json.dumps({"saved": False, "indexed": ok_count, "errors": error_msgs[:3], "status": resp.status_code}))

    return {"saved": True, "run_id": run_id, "indexed": len(results)}


LOCAL_TOOL_HANDLERS["save_results"] = save_results

# ── Entry point ────────────────────────────────────────────────────────────────

def proxy_elastic_request(request: Request):
    incoming_secret = request.args.get("secret")
    if not PROXY_SECRET or incoming_secret != PROXY_SECRET:
        return Response("Unauthorized: Invalid or missing proxy secret", status=401)

    payload = request.get_json(silent=True)

    if _is_local_tool_call(payload):
        return _json_response(_handle_local_tool_call(payload), 200, {})

    try:
        upstream = requests.request(
            method=request.method,
            url=KIBANA_URL,
            headers=_forward_headers(request.headers),
            data=json.dumps(payload).encode() if payload is not None else request.get_data(),
            allow_redirects=True,
            timeout=REQUEST_TIMEOUT,
        )
        headers = _response_headers(upstream.headers)
        content_type = upstream.headers.get("Content-Type", "").lower()
        if "application/json" in content_type:
            try:
                return _json_response(_inject_local_tools(upstream.json()), upstream.status_code, headers)
            except (TypeError, ValueError):
                pass
        return Response(upstream.content, status=upstream.status_code, headers=headers)
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
