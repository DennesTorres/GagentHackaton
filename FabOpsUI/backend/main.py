import json
import os
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


def _sse_error(message: str) -> str:
    return f"data: {json.dumps({'type': 'RUN_ERROR', 'message': message})}\n\n"


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
    agent_url = os.environ.get("FABOPS")
    if not agent_url:
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

    # Vertex AI Agent Engine expects {"input": <ag-ui payload>}
    raw_body = await request.body()
    try:
        vertex_body = json.dumps({"input": json.loads(raw_body)}).encode()
    except json.JSONDecodeError:
        vertex_body = raw_body

    upstream_headers = {
        "Authorization": f"Bearer {credentials.token}",
        "Content-Type": "application/json",
    }

    async def stream():
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(None)) as client:
                async with client.stream(
                    "POST", agent_url, content=vertex_body, headers=upstream_headers
                ) as response:
                    if response.status_code >= 400:
                        error_body = await response.aread()
                        yield _sse_error(
                            f"Upstream error {response.status_code}: "
                            f"{error_body.decode(errors='replace')[:500]}"
                        )
                        return
                    async for chunk in response.aiter_bytes():
                        yield chunk
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
