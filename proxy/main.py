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
    """Execute a notebook and return the JSON result as a dict."""
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
    return response.json()

def get_notebook_result(workspaceId: str, jobInstanceId: str):
    """Get notebook result and return the JSON result as a dict."""
    access_token = get_entra_token()
    url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspaceId}/jobScheduler/jobs/{jobInstanceId}"
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()

def proxy_fabric_request(request: Request):
    """Main function entry point."""
    # --- Secret Validation ---
    incoming_secret = request.args.get("secret")
    if not PROXY_SECRET or incoming_secret != PROXY_SECRET:
        return jsonify({"error": {"code": -32000, "message": "Invalid or missing secret"}}), 401

    request_data = request.get_json(silent=True)
    request_id = request_data.get("id") if isinstance(request_data, dict) else None

    try:
        # --- Tool Call Interception ---
        if request_data and "tool_run" in request_data:
            tool_run = request_data["tool_run"]
            tool_name = tool_run.get("tool_name")
            args = tool_run.get("args", {})

            tool_function = None
            if tool_name == "execute_notebook":
                tool_function = execute_notebook
            elif tool_name == "get_notebook_result":
                tool_function = get_notebook_result

            if tool_function:
                result_data = tool_function(**args)
                # Per MCP protocol, tool result must be a string.
                string_result = json.dumps(result_data)
                return jsonify({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"tool_run_id": tool_run.get("tool_run_id"), "result": string_result}
                })

        # --- Default Proxying Logic ---
        access_token = get_entra_token()
        headers = {k: v for k, v in request.headers if k.lower() not in ['host', 'x-proxy-secret', 'content-length']}
        headers["Authorization"] = f"Bearer {access_token}"

        response = requests.request(
            method=request.method,
            url=TARGET_BASE_URL,
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
        response_headers = {k: v for k, v in response.headers.items() if k.lower() not in excluded_headers}

        # --- Surgical Tool Spec Injection ---
        if 'application/json' in response.headers.get('Content-Type', ''):
            try:
                mcp_response_json = response.json()
                # Only inject if the response already has a tool_specs list
                if isinstance(mcp_response_json.get('tool_specs'), list):
                    mcp_response_json['tool_specs'].extend(NOTEBOOK_TOOLS)
                return jsonify(mcp_response_json)
            except (ValueError, TypeError):
                # Not a JSON response, or not the structure we expected, so proxy as-is
                pass
        
        return Response(response.content, status=response.status_code, headers=response_headers)

    except Exception as e:
        print(f"Error: {str(e)}")
        error_payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32603, "message": f"Internal Server Error: {str(e)}"}
        }
        return jsonify(error_payload), 500
