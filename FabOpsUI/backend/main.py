import asyncio
import json
import logging
import os
import uuid
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fabops")

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-process cache: thread_id → Vertex session_id
# Survives within a Cloud Run instance; UI state provides the fallback across instances
_SESSION_CACHE: dict[str, str] = {}


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _sse_error(message: str) -> str:
    return _sse({"type": "RUN_ERROR", "message": message})


async def _ensure_vertex_session(
    thread_id: str,
    sessions_url: str,
    headers: dict,
    client: httpx.AsyncClient,
) -> str:
    """Return the Vertex session_id for this thread, creating it if needed."""
    if thread_id in _SESSION_CACHE:
        return _SESSION_CACHE[thread_id]

    resp = await client.post(
        sessions_url,
        json={"userId": thread_id},
        headers=headers,
        timeout=10.0,
    )
    resp.raise_for_status()
    data = resp.json()
    name = data.get("name", "")

    # Handle LRO: if the name contains /operations/, poll until done
    if "/operations/" in name:
        parts = name.split("/")
        try:
            location = parts[parts.index("locations") + 1]
        except (ValueError, IndexError):
            location = "us-central1"
        op_url = f"https://{location}-aiplatform.googleapis.com/v1beta1/{name}"
        for _ in range(30):
            await asyncio.sleep(1)
            op_resp = await client.get(op_url, headers=headers)
            op_data = op_resp.json()
            if op_data.get("done"):
                name = op_data.get("response", {}).get("name", "")
                break

    # Session name: .../reasoningEngines/{engine}/sessions/{session_id}
    session_id = name.rsplit("/", 1)[-1]
    if session_id:
        _SESSION_CACHE[thread_id] = session_id
    return session_id


@app.get("/api/secrets")
def read_secrets():
    return {
        "tenant_id": os.environ.get("AZURE_TENANT_ID"),
        "client_id": os.environ.get("AZURE_CLIENT_ID"),
        "client_secret_set": bool(os.environ.get("AZURE_CLIENT_SECRET")),
    }


@app.get("/api/config")
def read_config():
    return {"agent_url": os.environ.get("FABOPS")}


@app.post("/api/agent")
async def agent_proxy(request: Request):
    base_url = os.environ.get("FABOPS")
    if not base_url:
        raise HTTPException(status_code=503, detail="FABOPS agent URL not configured")

    try:
        import google.auth
        import google.auth.transport.requests
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        credentials.refresh(google.auth.transport.requests.Request())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Google auth error: {exc}")

    # ── Parse incoming AG-UI RunAgentInput ────────────────────────────────────
    raw_body = await request.body()
    try:
        ag_ui = json.loads(raw_body)
    except json.JSONDecodeError:
        ag_ui = {}

    messages = ag_ui.get("messages", [])
    last_user_msg = next(
        (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"),
        "",
    )
    thread_id = ag_ui.get("threadId", str(uuid.uuid4()))
    run_id = ag_ui.get("runId", str(uuid.uuid4()))
    # The UI returns the Vertex session ID it received from STATE_SNAPSHOT
    agent_state = ag_ui.get("state") or {}

    # ── Build URLs ────────────────────────────────────────────────────────────
    engine_base = base_url.rstrip("/").split("?")[0]
    for suffix in (":streamQuery", ":query", ":stream"):
        if engine_base.endswith(suffix):
            engine_base = engine_base[: -len(suffix)]
            break
    stream_url = engine_base + ":streamQuery?alt=sse"
    sessions_url = engine_base + "/sessions"

    upstream_headers = {
        "Authorization": f"Bearer {credentials.token}",
        "Content-Type": "application/json",
    }

    # ── Stream: manage session, then translate Vertex SSE → AG-UI SSE ─────────
    async def stream():
        msg_id = str(uuid.uuid4())
        text_started = False
        unhandled_chunks: list = []

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(None)) as client:

                # Resolve Vertex session ID — from UI state, in-process cache, or create new
                vertex_session_id = agent_state.get("vertexSessionId")
                if vertex_session_id:
                    # UI returned a known session; warm the cache
                    _SESSION_CACHE[thread_id] = vertex_session_id
                else:
                    try:
                        vertex_session_id = await _ensure_vertex_session(
                            thread_id, sessions_url, upstream_headers, client
                        )
                    except Exception as exc:
                        yield _sse_error(f"Failed to create Vertex session: {exc}")
                        return

                logger.info("session resolved: vertex_session_id=%s thread_id=%s", vertex_session_id, thread_id)

                # Send the session ID to the UI so it passes it back on the next turn
                yield _sse({
                    "type": "STATE_SNAPSHOT",
                    "snapshot": {"vertexSessionId": vertex_session_id},
                })

                vertex_body = json.dumps({
                    "class_method": "stream_query",
                    "input": {
                        "message": last_user_msg,
                        "session_id": vertex_session_id,
                        "user_id": thread_id,
                    },
                }).encode()

                async with client.stream(
                    "POST", stream_url, content=vertex_body, headers=upstream_headers
                ) as response:
                    if response.status_code >= 400:
                        error_body = await response.aread()
                        yield _sse_error(
                            f"Upstream error {response.status_code}: "
                            f"{error_body.decode(errors='replace')[:500]}"
                        )
                        return

                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if not data_str or data_str == "[DONE]":
                            continue

                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        logger.info("vertex chunk keys=%s snippet=%s", list(chunk.keys()) if isinstance(chunk, dict) else type(chunk).__name__, json.dumps(chunk)[:300])

                        # Case 1: double-encoded string
                        if isinstance(chunk, str):
                            inner = chunk
                            if inner.startswith("data:"):
                                inner = inner[5:].strip()
                            try:
                                inner_event = json.loads(inner)
                                if isinstance(inner_event, dict) and "type" in inner_event:
                                    yield _sse(inner_event)
                                    if inner_event.get("type") == "RUN_FINISHED":
                                        return
                                    continue
                            except json.JSONDecodeError:
                                pass
                            continue

                        # Case 2: "output" key
                        if "output" in chunk:
                            output = chunk["output"]
                            if isinstance(output, str):
                                try:
                                    inner_event = json.loads(output)
                                    if isinstance(inner_event, dict) and "type" in inner_event:
                                        yield _sse(inner_event)
                                        if inner_event.get("type") == "RUN_FINISHED":
                                            return
                                        continue
                                except (json.JSONDecodeError, TypeError):
                                    pass
                                if not text_started:
                                    yield _sse({"type": "TEXT_MESSAGE_START", "messageId": msg_id})
                                    text_started = True
                                yield _sse({"type": "TEXT_MESSAGE_CONTENT", "messageId": msg_id, "delta": output})
                            elif isinstance(output, dict) and "type" in output:
                                yield _sse(output)
                                if output.get("type") == "RUN_FINISHED":
                                    return

                        # Case 3: tool actions
                        elif "actions" in chunk:
                            for action in chunk.get("actions", []):
                                tool_name = action.get("tool", "unknown")
                                yield _sse({
                                    "type": "TOOL_CALL_START",
                                    "toolCallId": str(uuid.uuid4()),
                                    "toolCallName": tool_name,
                                })

                        # Case 4: ADK native format
                        # {"author": "...", "content": {"parts": [{"text": "..."}], "role": "model"}}
                        elif isinstance(chunk, dict) and "content" in chunk:
                            parts = chunk.get("content", {}).get("parts", [])
                            for part in parts:
                                text = part.get("text")
                                if text:
                                    if not text_started:
                                        yield _sse({"type": "TEXT_MESSAGE_START", "messageId": msg_id})
                                        text_started = True
                                    yield _sse({"type": "TEXT_MESSAGE_CONTENT", "messageId": msg_id, "delta": text})
                                fn_call = part.get("functionCall")
                                if fn_call:
                                    yield _sse({
                                        "type": "TOOL_CALL_START",
                                        "toolCallId": str(uuid.uuid4()),
                                        "toolCallName": fn_call.get("name", "unknown"),
                                    })

                        else:
                            unhandled_chunks.append(chunk)

            if text_started:
                yield _sse({"type": "TEXT_MESSAGE_END", "messageId": msg_id})
            elif unhandled_chunks:
                sample = json.dumps(unhandled_chunks[:3], indent=2)[:800]
                yield _sse_error(f"No output rendered. Unrecognised Vertex chunks:\n{sample}")
                return
            yield _sse({"type": "RUN_FINISHED", "threadId": thread_id, "runId": run_id})

        except Exception as exc:
            yield _sse_error(f"Proxy error: {exc}")

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


# ── Static files (React SPA) ──────────────────────────────────────────────────
_dist = Path(__file__).parent / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        return FileResponse(_dist / "index.html")
