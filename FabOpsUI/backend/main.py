import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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


@app.get("/api/token")
def get_token():
    import google.auth
    import google.auth.transport.requests
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(google.auth.transport.requests.Request())
    return {"token": credentials.token}


# ── Static files (React SPA) ──────────────────────────────────────────────────
_dist = Path(__file__).parent / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        return FileResponse(_dist / "index.html")
