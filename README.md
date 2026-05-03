# garmin_mcp_modal

A [Garmin Connect](https://connect.garmin.com) [MCP server](https://modelcontextprotocol.io/) hosted on [Modal](https://modal.com), exposing your Garmin health and fitness data as tools to LLM clients (e.g. Claude Desktop).

Built on top of [`garmin-mcp`](https://github.com/Taxuspt/garmin_mcp) and Modal's serverless infrastructure.

## Exposed tools

Activities, health & wellness, user profile, devices, gear, weight, challenges, training, and workouts — sourced live from Garmin Connect.

## Setup

### Prerequisites

- [uv](https://docs.astral.sh/uv/)
- A [Modal](https://modal.com) account (`uv run modal token new`)
- A Garmin Connect account

### 1. Install dependencies

```bash
uv sync
```

### 2. Authenticate with Garmin Connect

Run the local auth script once to generate OAuth tokens. It uses browser TLS impersonation (`curl_cffi`) to bypass Garmin's anti-bot protection:

```bash
uv run python auth.py
```

You will be prompted for your Garmin email, password, and MFA code (if enabled). Tokens are saved to `~/.garminconnect_base64`.

### 3. Upload tokens as a Modal Secret

```bash
uv run modal secret create garmin-tokens GARMINTOKENS_BASE64="$(cat ~/.garminconnect_base64)"
```

Tokens are valid for ~6 months. When they expire, re-run steps 2–3.

### 5. Create an MCP bearer token

Generate a random token, save it to an environment variable (so that you can read it and pass it to Claude later), and then upload it as a Modal Secret:

```bash
# generate and export token in your current shell
export MCP_BEARER_TOKEN="$(openssl rand -hex 32)"

# optionally verify it's set
echo "MCP_BEARER_TOKEN=${MCP_BEARER_TOKEN}"

# upload to Modal as a secret
uv run modal secret create mcp-auth MCP_BEARER_TOKEN="$MCP_BEARER_TOKEN"
# if the secret already exists, update it instead:
# uv run modal secret delete mcp-auth
# uv run modal secret create mcp-auth MCP_BEARER_TOKEN="$MCP_BEARER_TOKEN"
```

### 6. Deploy

```bash
uv run modal deploy main.py
```

For local development with hot-reloading:

```bash
uv run modal serve main.py
```

### 7. Connect your MCP client

The endpoint uses standard HTTP Bearer auth (`Authorization: Bearer <token>`), which works on any device or MCP client without local config files.

The endpoint URL is printed after deploy and follows the pattern:

```
https://<your-modal-username>--garmin-mcp-endpoint.modal.run/mcp/
```

#### Claude Desktop

Add the server to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "garmin": {
      "type": "streamable-http",
      "url": "https://<your-modal-username>--garmin-mcp-endpoint.modal.run/mcp/",
      "headers": {
        "Authorization": "Bearer <your-MCP_BEARER_TOKEN>"
      }
    }
  }
}
```

#### Other clients (Claude.ai web, mobile, etc.)

Claude.ai's "Add custom connector" UI uses OAuth. The server implements a minimal **OAuth 2.0 Client Credentials** flow, so you can authenticate directly from the UI:

1. In Claude.ai, go to **Settings → Integrations → Add custom integration**
2. Fill in the fields:
   - **Name**: `Garmin Connect` (or anything you like)
   - **Remote MCP server URL**: `https://<your-modal-username>--garmin-mcp-endpoint.modal.run/mcp/`
   - **OAuth Client ID**: `claude` (any string — it is not checked)
   - **OAuth Client Secret**: your `MCP_BEARER_TOKEN` value

Claude.ai will POST to `/oauth/token` with your `client_secret`, receive the token back, and attach it automatically to every MCP request.

### Testing

```bash
MCP_BEARER_TOKEN=<your-token> uv run modal run main.py::test_tool
```

