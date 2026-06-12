import json
import logging
import os
import re
import uuid
from pathlib import Path

import vertexai
from vertexai.agent_engines import AgentEngine
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fabops")

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-process cache: thread_id → Vertex session_id
_SESSION_CACHE: dict[str, str] = {}


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _sse_error(message: str) -> str:
    return _sse({"type": "RUN_ERROR", "message": message})


def _get_agent() -> AgentEngine:
    """Return an AgentEngine for the configured FABOPS resource."""
    raw = os.environ.get("FABOPS", "")
    # Strip method suffix and query string to get the resource path
    # e.g. https://europe-west1-aiplatform.googleapis.com/v1beta1/projects/P/locations/L/reasoningEngines/ID:streamQuery
    url = raw.rstrip("/").split("?")[0]
    for suffix in (":streamQuery", ":query", ":stream"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
            break

    # Extract project and location from the URL to initialise vertexai
    m = re.search(r"/projects/([^/]+)/locations/([^/]+)/reasoningEngines/([^/]+)", url)
    if not m:
        raise ValueError(f"Cannot parse project/location from FABOPS URL: {url}")
    project, location, engine_id = m.group(1), m.group(2), m.group(3)
    vertexai.init(project=project, location=location)

    resource_name = f"projects/{project}/locations/{location}/reasoningEngines/{engine_id}"
    return AgentEngine(resource_name)


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
    if not os.environ.get("FABOPS"):
        raise HTTPException(status_code=503, detail="FABOPS agent URL not configured")

    try:
        agent = _get_agent()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agent config error: {exc}")

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
    agent_state = ag_ui.get("state") or {}

    async def stream():
        msg_id = str(uuid.uuid4())
        text_started = False
        unhandled: list = []

        try:
            # ── Resolve Vertex session ────────────────────────────────────────
            vertex_session_id = agent_state.get("vertexSessionId")
            if vertex_session_id:
                _SESSION_CACHE[thread_id] = vertex_session_id
            elif thread_id in _SESSION_CACHE:
                vertex_session_id = _SESSION_CACHE[thread_id]
            else:
                # Create a new session via the SDK
                try:
                    session = agent.create_session(user_id=thread_id)
                    name = session.get("name", "") if isinstance(session, dict) else getattr(session, "name", "")
                    vertex_session_id = name.rsplit("/", 1)[-1]
                    _SESSION_CACHE[thread_id] = vertex_session_id
                    logger.info("created session %s for thread %s", vertex_session_id, thread_id)
                except Exception as exc:
                    yield _sse_error(f"Failed to create session: {exc}")
                    return

            # Inform UI of session ID so it returns it on the next turn
            yield _sse({
                "type": "STATE_SNAPSHOT",
                "snapshot": {"vertexSessionId": vertex_session_id},
            })

            # ── Stream via SDK ────────────────────────────────────────────────
            logger.info("stream_query session=%s thread=%s msg=%s", vertex_session_id, thread_id, last_user_msg[:80])

            async for event in agent.async_stream_query(
                message=last_user_msg,
                user_id=thread_id,
                session_id=vertex_session_id,
            ):
                logger.info("event keys=%s snippet=%s",
                            list(event.keys()) if isinstance(event, dict) else type(event).__name__,
                            json.dumps(event)[:300] if isinstance(event, dict) else str(event)[:300])

                if not isinstance(event, dict):
                    unhandled.append(event)
                    continue

                handled = False

                # Plain text output (some SDK versions use this key)
                if "output" in event:
                    handled = True
                    output = event["output"]
                    if isinstance(output, str) and output:
                        if not text_started:
                            yield _sse({"type": "TEXT_MESSAGE_START", "messageId": msg_id})
                            text_started = True
                        yield _sse({"type": "TEXT_MESSAGE_CONTENT", "messageId": msg_id, "delta": output})

                # ADK native event format — checked independently because every ADK Event
                # also carries an "actions" key (EventActions), which would shadow this
                # branch if we used elif.
                if "content" in event:
                    handled = True
                    content = event["content"]
                    if isinstance(content, str):
                        if content:
                            if not text_started:
                                yield _sse({"type": "TEXT_MESSAGE_START", "messageId": msg_id})
                                text_started = True
                            yield _sse({"type": "TEXT_MESSAGE_CONTENT", "messageId": msg_id, "delta": content})
                    elif isinstance(content, dict):
                        parts = content.get("parts", [])
                        for part in parts:
                            if not isinstance(part, dict):
                                continue
                            text = part.get("text")
                            if text and not part.get("thought"):
                                if not text_started:
                                    yield _sse({"type": "TEXT_MESSAGE_START", "messageId": msg_id})
                                    text_started = True
                                yield _sse({"type": "TEXT_MESSAGE_CONTENT", "messageId": msg_id, "delta": text})
                            fn_call = part.get("functionCall")
                            if fn_call and isinstance(fn_call, dict):
                                yield _sse({
                                    "type": "TOOL_CALL_START",
                                    "toolCallId": str(uuid.uuid4()),
                                    "toolCallName": fn_call.get("name", "unknown"),
                                })

                if not handled:
                    unhandled.append(event)

            # ── End of stream ─────────────────────────────────────────────────
            if text_started:
                yield _sse({"type": "TEXT_MESSAGE_END", "messageId": msg_id})
            elif unhandled:
                sample = json.dumps(unhandled[:3], indent=2, default=str)[:800]
                yield _sse_error(f"No output rendered. Unrecognised events:\n{sample}")
                return

            yield _sse({"type": "RUN_FINISHED", "threadId": thread_id, "runId": run_id})

        except Exception as exc:
            logger.exception("stream error")
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
