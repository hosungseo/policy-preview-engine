"""MCP stdio tools. All protocol output belongs to the SDK; keys come only from env."""
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent
from pydantic import StrictBool, StrictInt

from . import mcp_copy, mcp_guide, public_rules, service
from .jobs import Jobs


def tool_result(data: dict, *, error: bool = False) -> CallToolResult:
    data = public_rules.envelope(data)
    return CallToolResult(content=[TextContent(type="text", text=public_rules.NOTICE + "\n" + public_rules.dumps(data))],
                          structuredContent=data, isError=error)


class PublicMCP(FastMCP):
    async def list_tools(self):
        tools = await super().list_tools()
        for tool in tools:
            tool.inputSchema = {**tool.inputSchema, "additionalProperties": False}
        return mcp_guide.dress_tools(tools)

    async def call_tool(self, name, arguments):
        tool = None
        try:
            tool = next((tool for tool in await self.list_tools() if tool.name == name), None)
            if tool is None:
                return tool_result({"error": mcp_copy.error("unknown_tool")}, error=True)
            if arguments.keys() - tool.inputSchema.get("properties", {}).keys():
                # Never echo extra names or values: either may contain credentials.
                return tool_result({"error": mcp_copy.error("extra_argument")}, error=True)
            return await super().call_tool(name, arguments)
        except Exception:
            # SDK validation errors must also retain notice and never echo arguments.
            return tool_result({"error": mcp_copy.error("invalid_value" if tool else "unknown_tool")}, error=True)


def create_server(jobs: Jobs | None = None) -> FastMCP:
    jobs = jobs or Jobs()
    server = PublicMCP(mcp_copy.SERVER_NAME, instructions=mcp_copy.INSTRUCTIONS)
    mcp_guide.register(server)

    def guarded(call):
        try:
            return tool_result(call())
        except (service.RequestError, KeyError) as exc:
            return tool_result({"error": str(exc), "warnings": [public_rules.WARNING]}, error=True)

    @server.tool()
    def estimate(policy_text: str, sample: StrictInt = service.DEFAULT_SAMPLE, i_confirm_public: StrictBool = False, limits: dict | None = None) -> CallToolResult:
        """Show approximate USD and duration before a paid run. No key needed."""
        return guarded(lambda: service.estimate(policy_text, sample, i_confirm_public=i_confirm_public, limits=limits))

    @server.tool()
    def start_run(policy_text: str, sample: StrictInt = service.DEFAULT_SAMPLE, seed: StrictInt = 42, i_confirm_public: StrictBool = False, limits: dict | None = None) -> CallToolResult:
        """Start a paid run with environment BYOK; estimate first, then poll get_run(id)."""
        return guarded(lambda: jobs.start(policy_text, sample, seed, i_confirm_public=i_confirm_public, limits=limits))

    @server.tool()
    def get_run(id: str) -> CallToolResult:
        """Return queued/running/completed/failed and result. IDs are lost on process restart."""
        return guarded(lambda: jobs.get(id))

    return server


def main():
    jobs = Jobs()
    try:
        create_server(jobs).run(transport="stdio")
    finally:
        jobs.close()


if __name__ == "__main__":
    main()
