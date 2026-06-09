# GagentHackaton Fabric MCP Proxy

This repository contains an HTTP proxy for the Microsoft Fabric Core MCP server.
The proxy preserves upstream MCP behavior and adds two proxy-owned tools:

- `execute_notebook`: starts a Fabric notebook execution.
- `get_notebook_result`: gets the current state of a notebook job instance.

## Behavior

- `initialize` responses advertise the `tools` capability.
- `tools/list` responses contain the upstream Fabric tools plus the two local tools.
- `tools/call` requests for local tools are executed by the proxy.
- Other MCP traffic is forwarded to `https://api.fabric.microsoft.com/v1/mcp/core`.
- JSON, Server-Sent Events, MCP session headers, status codes, and batch messages are preserved.

## Configuration

The function reads these environment variables:

- `PROXY_SECRET`
- `AZURE_TENANT_ID`
- `AZURE_CLIENT_ID`
- `AZURE_CLIENT_SECRET`
- `HTTP_CONNECT_TIMEOUT_SECONDS` (optional, default `10`)
- `HTTP_READ_TIMEOUT_SECONDS` (optional, default `300`)

Clients must provide the proxy secret as either the `secret` query parameter or
the `X-Proxy-Secret` header.

## Local Verification

```powershell
python -m pip install -r proxy\requirements.txt
python -m unittest proxy.test_main -v
python -m py_compile proxy\main.py proxy\test_main.py
```
