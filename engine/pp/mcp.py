"""MCP stdio tools. All protocol output belongs to the SDK; keys come only from env."""
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent
from typing import Literal

from pydantic import StrictBool, StrictInt

from . import public_rules, service
from .jobs import Jobs


def tool_result(data: dict, *, error: bool = False) -> CallToolResult:
    data = public_rules.envelope(data)
    text = data["summary"]["text"] if "summary" in data else public_rules.NOTICE + "\n" + public_rules.dumps(data)
    return CallToolResult(content=[TextContent(type="text", text=text)],
                          structuredContent=data, isError=error)


class PublicMCP(FastMCP):
    async def list_tools(self):
        tools = await super().list_tools()
        for tool in tools:
            tool.inputSchema = {**tool.inputSchema, "additionalProperties": False}
        return tools

    async def call_tool(self, name, arguments):
        try:
            tool = next((tool for tool in await self.list_tools() if tool.name == name), None)
            if tool is not None and arguments.keys() - tool.inputSchema.get("properties", {}).keys():
                # Never echo extra names or values: either may contain credentials.
                return tool_result({"error": "정의되지 않은 추가 인자는 사용할 수 없습니다. "
                                   "키는 환경변수로 설정합니다(BYOK)."}, error=True)
            return await super().call_tool(name, arguments)
        except Exception:
            # SDK validation/unknown-tool errors must also retain notice and never echo arguments.
            return tool_result({"error": "도구 호출 실패: 도구 이름과 입력 형식을 확인하세요."}, error=True)


def create_server(jobs: Jobs | None = None) -> FastMCP:
    jobs = jobs or Jobs()
    server = PublicMCP("policy-preview")

    def guarded(call):
        try:
            return tool_result(call())
        except (service.RequestError, KeyError) as exc:
            return tool_result({"error": str(exc), "warnings": [public_rules.WARNING]}, error=True)

    @server.tool()
    def estimate(policy_text: str, sample: StrictInt = service.DEFAULT_SAMPLE, i_confirm_public: StrictBool = False, limits: dict | None = None, seed: StrictInt = 42) -> CallToolResult:
        """Show approximate USD and duration before a paid run. No key needed."""
        return guarded(lambda: jobs.estimate(policy_text, sample, seed, i_confirm_public=i_confirm_public, limits=limits))

    @server.tool()
    def start_run(policy_text: str | None = None, sample: StrictInt | None = None, seed: StrictInt | None = None, i_confirm_public: StrictBool | None = None, limits: dict | None = None, plan_id: str | None = None) -> CallToolResult:
        """견적의 plan_id로 확인한 조건을 실행합니다. 조건이 바뀌면 재견적하세요. 사용자 실행 의사를 먼저 확인하세요. 기존 직접 입력도 지원합니다."""
        return guarded(lambda: jobs.start_planned(policy_text, sample, seed, i_confirm_public=i_confirm_public, limits=limits, plan_id=plan_id))

    @server.tool()
    def get_run(id: str, view: Literal["summary", "full"] = "summary") -> CallToolResult:
        """단계·진행 정도·예상 남은 시간과 완료 시 한 장 요약을 봅니다. 전체 기록은 view=full. 재시작 전 save_review로 저장하세요."""
        return guarded(lambda: jobs.get(id, view=view))

    @server.tool()
    def save_review(id: str, path: str) -> CallToolResult:
        """완료된 전체 결과를 고지·출처와 함께 서버 컴퓨터의 새 JSON 파일로 저장합니다. 기존 파일은 덮어쓰지 않습니다. 서버 재시작 전에 저장하세요."""
        return guarded(lambda: jobs.save_review(id, path))

    return server


def main():
    jobs = Jobs()
    try:
        create_server(jobs).run(transport="stdio")
    finally:
        jobs.close()


if __name__ == "__main__":
    main()
