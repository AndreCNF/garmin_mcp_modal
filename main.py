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

    from fastapi import FastAPI  # ty:ignore[unresolved-import]
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
    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.server import TransportSecuritySettings

app = modal.App(name="garmin_mcp", image=image, secrets=[modal.Secret.from_name("garmin-tokens")])


@app.function()
@modal.asgi_app(requires_proxy_auth=True)
def endpoint():
    """ASGI web endpoint for the MCP server."""
    tokens_base64 = os.environ.get("GARMINTOKENS_BASE64")
    if not tokens_base64:
        raise RuntimeError(
            "GARMINTOKENS_BASE64 secret is not set. Run: modal secret create garmin-tokens GARMINTOKENS_BASE64=$(cat ~/.garminconnect_base64)"
        )

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

    return fastapi_app


@app.function()
async def test_tool(tool_name: str | None = None):
    """Make sure that we can run tools from the MCP server."""
    if tool_name is None:
        tool_name = "get_full_name"

    token_id = os.environ.get("MODAL_TOKEN_ID")
    token_secret = os.environ.get("MODAL_TOKEN_SECRET")
    if not token_id or not token_secret:
        raise RuntimeError("MODAL_TOKEN_ID and MODAL_TOKEN_SECRET must be set to test the authenticated endpoint.")

    transport = StreamableHttpTransport(
        url=f"{endpoint.get_web_url()}/mcp/",
        headers={"Modal-Key": token_id, "Modal-Secret": token_secret},
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
