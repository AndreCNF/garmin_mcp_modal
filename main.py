"""Garmin MCP server hosted on Modal."""

import modal

image = (
    modal.Image.debian_slim(python_version="3.13")
    .apt_install("git")
    # Installing garmin-mcp separately first so that we can avoid
    # dependency conflicts when installing the other libraries
    .uv_pip_install("garmin-mcp@git+https://github.com/Taxuspt/garmin_mcp.git")
    .uv_pip_install(
        "curl-cffi>=0.15.0",
        "fastapi>=0.136.1",
        "fastmcp>=2.14.0,<3",
        "mcp>=1.27.0,<2",
    )
)

with image.imports():
    import os
    import time

    from fastapi import FastAPI, Request  # ty:ignore[unresolved-import]
    from fastapi.responses import JSONResponse  # ty:ignore[unresolved-import]
    from fastmcp import Client  # ty:ignore[unresolved-import]
    from fastmcp.client.transports import StreamableHttpTransport  # ty:ignore[unresolved-import]
    from garmin_mcp import (
        activity_management,
        challenges,
        data_management,
        devices,
        gear_management,
        health_wellness,
        training,
        user_profile,
        weight_management,
        workout_templates,
        workouts,
    )
    from garminconnect import Garmin
    from mcp.server.auth.middleware.bearer_auth import AccessToken
    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.server import TransportSecuritySettings

app = modal.App(
    name="garmin_mcp",
    image=image,
    secrets=[modal.Secret.from_name("garmin-tokens"), modal.Secret.from_name("mcp-auth")],
)


@app.function()
@modal.asgi_app()
def endpoint():
    """ASGI web endpoint for the MCP server."""
    tokens_base64 = os.environ.get("GARMINTOKENS_BASE64")
    if not tokens_base64:
        raise RuntimeError(
            "GARMINTOKENS_BASE64 secret is not set. Run: modal secret create garmin-tokens GARMINTOKENS_BASE64=$(cat ~/.garminconnect_base64)"
        )

    mcp_bearer_token = os.environ.get("MCP_BEARER_TOKEN")
    if not mcp_bearer_token:
        raise RuntimeError(
            "MCP_BEARER_TOKEN secret is not set. Run: modal secret create mcp-auth MCP_BEARER_TOKEN=<your-secret>"
        )

    class StaticBearerVerifier:
        """Accepts a single static bearer token — simple cross-device auth."""

        async def verify_token(self, token: str) -> AccessToken | None:
            if token == mcp_bearer_token:
                return AccessToken(token=token, client_id="static", scopes=[])
            return None

    garmin_client = Garmin()
    garmin_client.garth.loads(tokens_base64)

    activity_management.configure(garmin_client)
    health_wellness.configure(garmin_client)
    user_profile.configure(garmin_client)
    devices.configure(garmin_client)
    gear_management.configure(garmin_client)
    weight_management.configure(garmin_client)
    challenges.configure(garmin_client)
    training.configure(garmin_client)
    workouts.configure(garmin_client)
    data_management.configure(garmin_client)

    fast_mcp_app = FastMCP(
        "Garmin Connect v1.0",
        stateless_http=True,
        token_verifier=StaticBearerVerifier(),
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    fast_mcp_app = activity_management.register_tools(fast_mcp_app)
    fast_mcp_app = health_wellness.register_tools(fast_mcp_app)
    fast_mcp_app = user_profile.register_tools(fast_mcp_app)
    fast_mcp_app = devices.register_tools(fast_mcp_app)
    fast_mcp_app = gear_management.register_tools(fast_mcp_app)
    fast_mcp_app = weight_management.register_tools(fast_mcp_app)
    fast_mcp_app = challenges.register_tools(fast_mcp_app)
    fast_mcp_app = training.register_tools(fast_mcp_app)
    fast_mcp_app = workouts.register_tools(fast_mcp_app)
    fast_mcp_app = data_management.register_tools(fast_mcp_app)
    # Skipping Garmin features that I'm not using:
    # fast_mcp_app = womens_health.register_tools(fast_mcp_app)  # noqa: ERA001
    # fast_mcp_app = nutrition.register_tools(fast_mcp_app)  # noqa: ERA001

    # Register resources (workout templates)
    fast_mcp_app = workout_templates.register_resources(fast_mcp_app)

    # Use streamable HTTP transport for stateless compatibility with Modal
    mcp_app = fast_mcp_app.streamable_http_app()

    fastapi_app = FastAPI(lifespan=mcp_app.router.lifespan_context)
    fastapi_app.mount("/", mcp_app, "mcp")

    # ── Minimal OAuth 2.0 Client Credentials flow ─────────────────────────
    # Claude.ai's "Add custom connector" UI sends client_id + client_secret
    # to /oauth/token and expects a bearer access_token back.
    # We treat client_secret == MCP_BEARER_TOKEN as the credential.

    base_url = endpoint.get_web_url()

    @fastapi_app.get("/.well-known/oauth-authorization-server")
    async def oauth_metadata():
        return JSONResponse(
            {
                "issuer": base_url,
                "token_endpoint": f"{base_url}/oauth/token",
                "grant_types_supported": ["client_credentials"],
                "token_endpoint_auth_methods_supported": ["client_secret_post"],
            }
        )

    @fastapi_app.post("/oauth/token")
    async def oauth_token(request: Request):
        form = await request.form()
        grant_type = form.get("grant_type")
        client_secret = form.get("client_secret")

        if grant_type != "client_credentials":
            return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)

        if client_secret != mcp_bearer_token:
            return JSONResponse({"error": "invalid_client"}, status_code=401)

        return JSONResponse(
            {
                "access_token": mcp_bearer_token,
                "token_type": "bearer",
                "expires_in": 3600,
                "issued_at": int(time.time()),
            }
        )

    return fastapi_app


@app.function()
async def test_tool(tool_name: str | None = None):
    """Make sure that we can run tools from the MCP server."""
    if tool_name is None:
        tool_name = "get_full_name"

    bearer_token = os.environ.get("MCP_BEARER_TOKEN")
    if not bearer_token:
        raise RuntimeError("MCP_BEARER_TOKEN must be set to test the authenticated endpoint.")

    transport = StreamableHttpTransport(
        url=f"{endpoint.get_web_url()}/mcp/",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    client = Client(transport)

    async with client:
        tools = await client.list_tools()

        for tool in tools:
            print(tool)
            if tool.name == tool_name:
                result = await client.call_tool(tool_name)
                print(result.data)
                return

    raise Exception(f"could not find tool {tool_name}")
