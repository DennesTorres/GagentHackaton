import os
import json
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

# Tool specifications for the custom notebook tools
NOTEBOOK_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "execute_notebook",
            "description": "Executes a Microsoft Fabric notebook.",
            "parameters": {
                "type": "object",
                "properties": {
                    "workspaceId": {"type": "string", "description": "The ID of the workspace."},
                    "notebookId": {"type": "string", "description": "The ID of the notebook."},
                },
                "required": ["workspaceId", "notebookId"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_notebook_result",
            "description": "Gets the result of a notebook execution.",
            "parameters": {
                "type": "object",
                "properties": {
                    "workspaceId": {"type": "string", "description": "The ID of the workspace."},
                    "jobInstanceId": {"type": "string", "description": "The ID of the job instance."},
                },
                "required": ["workspaceId", "jobInstanceId"],
            },
        },
    },
]

def get_entra_token():
    """Acquires an OAuth 2.0 token using client credentials flow."""
    authority = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}"
    app = ConfidentialClientApplication(
        AZURE_CLIENT_ID,
        authority=authority,
        client_credential=AZURE_CLIENT_SECRET,
    )
    result = app.acquire_token_for_client(scopes=SCOPE)
    if "access_token" in result:
        return result["access_token"]
    else:
        raise Exception(f"Could not acquire token: {result.get('error_description')}")

def execute_notebook(workspaceId: str, notebookId: str):
    """Execute a notebook in Microsoft Fabric."""
    try:
        access_token = get_entra_token()
        url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspaceId}/items/{notebookId}/jobs/instances"
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

def get_notebook_result(workspaceId: str, jobInstanceId: str):
    """Get the result of a notebook execution."""
    try:
        access_token = get_entra_token()
        url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspaceId}/jobScheduler/jobs/{jobInstanceId}"
        headers = {
            "Authorization": f"Bearer {access_token}"
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return jsonify(response.json())
    except Exception as e:
        print(f"Error: {str(e)}")
        return Response(f"Internal Server Error: {str(e)}", status=500)

def proxy_fabric_request(request: Request):
    """Main function entry point."""

    # --- Secret Validation ---
    incoming_secret = request.args.get("secret")
    if not PROXY_SECRET or incoming_secret != PROXY_SECRET:
        return jsonify({"error": "Unauthorized", "error_description": "Invalid or missing secret"}), 401

    # --- Tool Call Interception ---
    data = request.get_json(silent=True)
    if data and "tool_run" in data:
        tool_run = data["tool_run"]
        tool_name = tool_run.get("tool_name")
        args = tool_run.get("args", {})

        if tool_name == "execute_notebook":
            return execute_notebook(**args)
        elif tool_name == "get_notebook_result":
            return get_notebook_result(**args)

    # If not a tool call, proceed with proxying
    try:
        access_token = get_entra_token()

        headers = {k: v for k, v in request.headers if k.lower() not in ['host', 'x-proxy-secret', 'content-length']}
        headers["Authorization"] = f"Bearer {access_token}"

        url = TARGET_BASE_URL

        response = requests.request(
            method=request.method,
            url=url,
            headers=headers,
            data=request.get_data(),
            cookies=request.cookies,
            allow_redirects=False,
            stream=True
        )

        excluded_headers = [
            'content-encoding', 'transfer-encoding', 'content-length',
            'connection', 'keep-alive', 'te', 'trailers', 'upgrade'
        ]
        response_headers = {
            k: v for k, v in response.headers.items()
            if k.lower() not in excluded_headers
        }

        # --- Tool Spec Injection ---
        if 'application/json' in response.headers.get('Content-Type', ''):
            try:
                mcp_response_json = response.json()
                if 'tool_specs' not in mcp_response_json:
                    mcp_response_json['tool_specs'] = []
                mcp_response_json['tool_specs'].extend(NOTEBOOK_TOOLS)
                return jsonify(mcp_response_json)
            except (ValueError, TypeError):
                return Response(response.content, status=response.status_code, headers=response_headers)

        return Response(response.content, status=response.status_code, headers=response_headers)

    except Exception as e:
        print(f"Error: {str(e)}")
        return Response(f"Internal Server Error: {str(e)}", status=500)
