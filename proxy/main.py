
import os
import requests
from flask import Request, Response
from msal import ConfidentialClientApplication

# 1. Load configuration from environment variables
PROXY_SECRET = os.environ.get("PROXY_SECRET")
AZURE_TENANT_ID = os.environ.get("AZURE_TENANT_ID")
AZURE_CLIENT_ID = os.environ.get("AZURE_CLIENT_ID")
AZURE_CLIENT_SECRET = os.environ.get("AZURE_CLIENT_SECRET")

# Microsoft Fabric API Scope
SCOPE = ["https://api.fabric.microsoft.com/.default"]
TARGET_BASE_URL = "https://api.fabric.microsoft.com/v1/mcp/core"

def get_entra_token():
    """Acquires an OAuth 2.0 token using client credentials flow."""
    authority = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}"
    app = ConfidentialClientApplication(
        AZURE_CLIENT_ID,
        authority=authority,
        client_credential=AZURE_CLIENT_SECRET,
    )
    # Check cache first, then acquire new token
    result = app.acquire_token_for_client(scopes=SCOPE)
    
    if "access_token" in result:
        return result["access_token"]
    else:
        raise Exception(f"Could not acquire token: {result.get('error_description')}")

def proxy_fabric_request(request: Request):
    """Main function entry point."""
    
    # --- Requirement 1: Proxy Secret Validation ---
    incoming_secret = request.headers.get("X-Proxy-Secret")
    if not PROXY_SECRET or incoming_secret != PROXY_SECRET:
        return Response("Unauthorized: Invalid or missing X-Proxy-Secret", status=401)

    try:
        # --- Requirement 2: Acquire Entra Token ---
        access_token = get_entra_token()

        # --- Requirement 3 & 4: Prepare Headers and Forward ---
        # Copy incoming headers and clean them up
        headers = {k: v for k, v in request.headers if k.lower() not in ['host', 'x-proxy-secret', 'content-length']}
        headers["Authorization"] = f"Bearer {access_token}"

        # Construct destination URL (appending any sub-paths if present)
        # Note: If you only want to hit the base endpoint, use TARGET_BASE_URL
        path = request.full_path if request.path != "/" else ""
        url = f"{TARGET_BASE_URL}{path}"

        # Execute the request to Microsoft Fabric
        response = requests.request(
            method=request.method,
            url=url,
            headers=headers,
            data=request.get_data(),
            cookies=request.cookies,
            allow_redirects=False,
            stream=True # Stream response for efficiency
        )

        # Return the full response back to the client
        return Response(
            response.content,
            status=response.status_code,
            headers=dict(response.headers)
        )

    except Exception as e:
        print(f"Error: {str(e)}")
        return Response(f"Internal Server Error: {str(e)}", status=500)
