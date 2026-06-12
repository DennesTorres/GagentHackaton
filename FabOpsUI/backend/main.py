import json
import os
import uuid
from pathlib import Path

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


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _sse_error(message: str) -> str:
    return _sse({"type": "RUN_ERROR", "message": message})


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

    # ── Build Vertex AI Agent Engine request ──────────────────────────────────
    # POST .../reasoningEngines/{id}:streamQuery?alt=sse
    stream_url = base_url.rstrip("/")
    if not stream_url.endswith(":streamQuery"):
        stream_url += ":streamQuery"
    if "?" not in stream_url:
        stream_url += "?alt=sse"
    elif "alt=" not in stream_url:
        stream_url += "&alt=sse"

    vertex_body = json.dumps({
        "class_method": "stream_query",
        "input": {
            "message": last_user_msg,
            "session_id": thread_id,
            # also pass full history in case the agent uses it
            "messages": messages,
        },
    }).encode()

    upstream_headers = {
        "Authorization": f"Bearer {credentials.token}",
        "Content-Type": "application/json",
    }

    # ── Stream: translate Vertex AI SSE → AG-UI SSE ───────────────────────────
    async def stream():
        msg_id = str(uuid.uuid4())
        text_started = False

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(None)) as client:
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

                        # ── Try to parse the SSE data payload ─────────────
                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        # Case 1: chunk is a JSON string — Vertex double-encoded
                        # an inner SSE line (e.g. the agent emitted AG-UI events)
                        if isinstance(chunk, str):
                            inner = chunk
                            # Strip leading "data: " if present
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

                        # Case 2: chunk is a dict with an "output" key
                        if "output" in chunk:
                            output = chunk["output"]
                            if isinstance(output, str):
                                # Could be a JSON-encoded AG-UI event
                                try:
                                    inner_event = json.loads(output)
                                    if isinstance(inner_event, dict) and "type" in inner_event:
                                        yield _sse(inner_event)
                                        if inner_event.get("type") == "RUN_FINISHED":
                                            return
                                        continue
                                except (json.JSONDecodeError, TypeError):
                                    pass
                                # Plain text — emit as text message
                                if not text_started:
                                    yield _sse({"type": "TEXT_MESSAGE_START", "messageId": msg_id})
                                    text_started = True
                                yield _sse({"type": "TEXT_MESSAGE_CONTENT", "messageId": msg_id, "delta": output})
                            elif isinstance(output, dict) and "type" in output:
                                # Already an AG-UI event dict
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

            # Finish the text message and signal run completion
            if text_started:
                yield _sse({"type": "TEXT_MESSAGE_END", "messageId": msg_id})
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
