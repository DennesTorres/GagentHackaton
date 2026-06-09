import os
import requests
from flask import Request, Response, jsonify
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
    
    if request.path == '/execute-notebook':
        return execute_notebook(request)
    elif request.path == '/notebook-result':
        return get_notebook_result(request)

    # --- Requirement 1: Proxy Secret Validation ---
    incoming_secret = request.args.get("secret")
    if not PROXY_SECRET or incoming_secret != PROXY_SECRET:
        return Response("Unauthorized: Invalid or missing X-Proxy-Secret", status=401)

    try:
        # --- Requirement 2: Acquire Entra Token ---
        access_token = get_entra_token()

        # --- Requirement 3 & 4: Prepare Headers and Forward ---
        # Copy incoming headers and clean them up
        headers = {k: v for k, v in request.headers if k.lower() not in ['host', 'x-proxy-secret', 'content-length']}
        headers["Authorization"] = f"Bearer {access_token}"

        # FIX BUG 1: Use the exact TARGET_BASE_URL for MCP protocol
        url = TARGET_BASE_URL

        # Execute the request to Microsoft Fabric
        response = requests.request(
            method=request.method,
            url=url,
            headers=headers,
            data=request.get_data(),
            cookies=request.cookies,
            allow_redirects=False,
            stream=True 
        )

        # FIX BUG 2: Strip encoding and hop-by-hop headers from the response
        # Since 'requests' already decoded the content, forwarding these headers
        # will cause the client to attempt to decode plain bytes.
        excluded_headers = [
            'content-encoding', 'transfer-encoding', 'content-length', 
            'connection', 'keep-alive', 'te', 'trailers', 'upgrade'
        ]
        response_headers = {
            k: v for k, v in response.headers.items() 
            if k.lower() not in excluded_headers
        }

        # Return the response back to the client
        return Response(
            response.content,
            status=response.status_code,
            headers=response_headers
        )

    except Exception as e:
        print(f"Error: {str(e)}")
        return Response(f"Internal Server Error: {str(e)}", status=500)

def execute_notebook(request: Request):
    """Execute a notebook in Microsoft Fabric."""
    
    incoming_secret = request.headers.get("X-Proxy-Secret")
    if not PROXY_SECRET or incoming_secret != PROXY_SECRET:
        return Response("Unauthorized: Invalid or missing X-Proxy-Secret", status=401)
        
    try:
        access_token = get_entra_token()
        
        data = request.get_json()
        workspace_id = data.get("workspaceId")
        notebook_id = data.get("notebookId")
        
        if not workspace_id or not notebook_id:
            return Response("Missing workspaceId or notebookId in request body", status=400)
            
        url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/items/{notebook_id}/jobs/instances"
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        body = {
            "executionData": {
                "configuration": {
                    "jobType": "RunNotebook"
                }
            }
        }
        
        response = requests.post(url, headers=headers, json=body)
        response.raise_for_status()
        
        return jsonify(response.json())
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return Response(f"Internal Server Error: {str(e)}", status=500)

def get_notebook_result(request: Request):
    """Get the result of a notebook execution."""
    
    incoming_secret = request.headers.get("X-Proxy-Secret")
    if not PROXY_SECRET or incoming_secret != PROXY_SECRET:
        return Response("Unauthorized: Invalid or missing X-Proxy-Secret", status=401)
        
    try:
        access_token = get_entra_token()
        
        workspace_id = request.args.get("workspaceId")
        job_instance_id = request.args.get("jobInstanceId")
        
        if not workspace_id or not job_instance_id:
            return Response("Missing workspaceId or jobInstanceId in query parameters", status=400)
            
        url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/jobScheduler/jobs/{job_instance_id}"
        
        headers = {
            "Authorization": f"Bearer {access_token}"
        }
        
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        return jsonify(response.json())
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return Response(f"Internal Server Error: {str(e)}", status=500)
