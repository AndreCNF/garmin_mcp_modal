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
modal secret create garmin-tokens GARMINTOKENS_BASE64="$(cat ~/.garminconnect_base64)"
```

Tokens are valid for ~6 months. When they expire, re-run steps 2–3.

### 4. Deploy

```bash
uv run modal deploy main.py
```

For local development with hot-reloading:

```bash
uv run modal serve main.py
```

### 5. Connect your MCP client

The endpoint is protected by [Modal Proxy Auth](https://modal.com/docs/guide/proxy-auth). Create a Proxy Auth Token at [modal.com/settings/proxy-auth-tokens](https://modal.com/settings/proxy-auth-tokens), then add the deployed endpoint to your MCP client with the `Modal-Key` and `Modal-Secret` headers.

The endpoint URL is printed after deploy and follows the pattern:

```
https://<your-modal-username>--garmin-mcp-endpoint.modal.run/mcp/
```

Select **Streamable HTTP** as the transport type.

### Testing

Set your Modal API credentials and run:

```bash
MODAL_TOKEN_ID=<token-id> MODAL_TOKEN_SECRET=<token-secret> uv run modal run main.py::test_tool
```

