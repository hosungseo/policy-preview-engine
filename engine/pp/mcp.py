"""MCP stdio tools. All protocol output belongs to the SDK; keys come only from env."""
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent
from typing import Literal

from pydantic import StrictBool, StrictInt

from . import mcp_copy, mcp_guide, public_rules, service, mcp_setup, mcp_notices
from .jobs import Jobs


def tool_result(data: dict, *, error: bool = False) -> CallToolResult:
    data = public_rules.envelope(data)
    text = data["summary"]["text"] if "summary" in data else public_rules.NOTICE + "\n" + public_rules.dumps(data)
    return CallToolResult(content=[TextContent(type="text", text=text)],
                          structuredContent=data, isError=error)


def protocol_error(code):
    message = mcp_copy.error(code)
    data = mcp_setup.error_payload(service.RequestError(message))
    data.update(error=message, message=message)
    return tool_result(data, error=True)


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
                return protocol_error("unknown_tool")
            if arguments.keys() - tool.inputSchema.get("properties", {}).keys():
                # Never echo extra names or values: either may contain credentials.
                return protocol_error("extra_argument")
            return await super().call_tool(name, arguments)
        except Exception:
            # SDK validation errors must also retain notice and never echo arguments.
            return protocol_error("invalid_value" if tool else "unknown_tool")


def create_server(jobs: Jobs | None = None) -> FastMCP:
    jobs = jobs or Jobs()
    server = PublicMCP(mcp_copy.SERVER_NAME, instructions=mcp_copy.INSTRUCTIONS)
    mcp_guide.register(server)

    def guarded(call):
        try:
            data = call()
            return tool_result(data, error=data.get("status") == "failed")
        except Exception as exc:
            return tool_result(mcp_setup.error_payload(exc), error=True)

    @server.tool()
    def check_setup() -> CallToolResult:
        """무료 준비 점검: 키·합성 인물 패널·예시 자료·실행 모드를 확인합니다. 비밀값은 표시하지 않습니다."""
        return guarded(mcp_setup.check_setup)

    @server.tool()
    def try_example(example: str = "subway-free-ride") -> CallToolResult:
        """키·패널 없이 내장 정책 예시를 무료로 끝까지 체험합니다. 모의 응답이며 외부 전송과 요금은 없습니다."""
        return guarded(lambda: jobs.try_example(example))

    @server.tool()
    def find_notice(query: str = "", page: StrictInt = 1) -> CallToolResult:
        """현재 의견을 받는 입법예고를 무료로 찾습니다. 검색어를 생략하면 최근 목록이며 키가 없으면 공개 페이지를 읽습니다."""
        return guarded(lambda: mcp_notices.find_notice(query, page))

    @server.tool()
    def get_notice(seq: str, mapping_lbic_id: str = "", announce_type: str = "") -> CallToolResult:
        """고른 입법예고의 이유·주요내용 원문과 estimate에 넣을 policy_text를 무료로 가져옵니다. 분석은 자동 시작하지 않습니다."""
        return guarded(lambda: mcp_notices.get_notice(seq, mapping_lbic_id, announce_type))

    @server.tool()
    def estimate(policy_text: str, sample: StrictInt = service.DEFAULT_SAMPLE, i_confirm_public: StrictBool = False, limits: dict | None = None, seed: StrictInt = 42, conditions: dict | list[dict] | None = None) -> CallToolResult:
        """Show approximate USD and duration before a paid run. No key needed."""
        return guarded(lambda: jobs.estimate(policy_text, sample, seed, i_confirm_public=i_confirm_public, limits=limits, conditions=conditions))

    @server.tool()
    def start_run(policy_text: str | None = None, sample: StrictInt | None = None, seed: StrictInt | None = None, i_confirm_public: StrictBool | None = None, limits: dict | None = None, plan_id: str | None = None, conditions: dict | list[dict] | None = None) -> CallToolResult:
        """견적의 plan_id로 확인한 조건을 실행합니다. 조건이 바뀌면 재견적하세요. 사용자 실행 의사를 먼저 확인하세요. 기존 직접 입력도 지원합니다."""
        return guarded(lambda: jobs.start_planned(policy_text, sample, seed, i_confirm_public=i_confirm_public, limits=limits, plan_id=plan_id, conditions=conditions))

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
