import os
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from google.cloud import secretmanager
from pydantic import BaseModel

GCP_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "")

SECRET_IDS = {
    "tenant_id": "AZURE_TENANT_ID",
    "client_id": "AZURE_CLIENT_ID",
    "client_secret": "AZURE_CLIENT_SECRET",
}

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _client() -> secretmanager.SecretManagerServiceClient:
    return secretmanager.SecretManagerServiceClient()


def _get_secret(secret_id: str) -> Optional[str]:
    if not GCP_PROJECT:
        return None
    try:
        name = f"projects/{GCP_PROJECT}/secrets/{secret_id}/versions/latest"
        resp = _client().access_secret_version(request={"name": name})
        return resp.payload.data.decode("utf-8")
    except Exception:
        return None


def _set_secret(secret_id: str, value: str) -> None:
    if not GCP_PROJECT:
        raise HTTPException(status_code=500, detail="GOOGLE_CLOUD_PROJECT not configured")
    client = _client()
    parent = f"projects/{GCP_PROJECT}"
    secret_path = f"{parent}/secrets/{secret_id}"
    try:
        client.get_secret(request={"name": secret_path})
    except Exception:
        client.create_secret(request={
            "parent": parent,
            "secret_id": secret_id,
            "secret": {"replication": {"automatic": {}}},
        })
    client.add_secret_version(request={
        "parent": secret_path,
        "payload": {"data": value.encode("utf-8")},
    })


@app.get("/api/secrets")
def read_secrets():
    return {
        "tenant_id": _get_secret(SECRET_IDS["tenant_id"]),
        "client_id": _get_secret(SECRET_IDS["client_id"]),
        "client_secret_set": _get_secret(SECRET_IDS["client_secret"]) is not None,
    }


class SecretsPayload(BaseModel):
    tenant_id: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None


@app.post("/api/secrets")
def write_secrets(payload: SecretsPayload):
    if payload.tenant_id is not None:
        _set_secret(SECRET_IDS["tenant_id"], payload.tenant_id)
    if payload.client_id is not None:
        _set_secret(SECRET_IDS["client_id"], payload.client_id)
    if payload.client_secret is not None:
        _set_secret(SECRET_IDS["client_secret"], payload.client_secret)
    return {"status": "ok"}
