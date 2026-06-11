import os
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.background import BackgroundTasks
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
async def agent_proxy(request: Request, background_tasks: BackgroundTasks):
    agent_url = os.environ.get("FABOPS")
    if not agent_url:
        raise HTTPException(status_code=503, detail="FABOPS agent URL not configured")

    import google.auth
    import google.auth.transport.requests
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(google.auth.transport.requests.Request())

    body = await request.body()
    headers = {
        "Authorization": f"Bearer {credentials.token}",
        "Content-Type": request.headers.get("content-type", "application/json"),
        "Accept": request.headers.get("accept", "*/*"),
    }

    client = httpx.AsyncClient(timeout=httpx.Timeout(None))
    upstream = await client.send(
        client.build_request("POST", agent_url, content=body, headers=headers),
        stream=True,
    )
    background_tasks.add_task(upstream.aclose)
    background_tasks.add_task(client.aclose)

    return StreamingResponse(
        upstream.aiter_bytes(),
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "text/event-stream"),
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


# ── Static files (React SPA) ──────────────────────────────────────────────────
_dist = Path(__file__).parent / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        return FileResponse(_dist / "index.html")
