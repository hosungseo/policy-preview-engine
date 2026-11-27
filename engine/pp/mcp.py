"""MCP stdio tools. All protocol output belongs to the SDK; keys come only from env."""
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent
from pydantic import StrictBool, StrictInt

from . import public_rules, service, mcp_setup, mcp_notices
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
        return tools

    async def call_tool(self, name, arguments):
        try:
            tool = next((tool for tool in await self.list_tools() if tool.name == name), None)
            if tool is not None and arguments.keys() - tool.inputSchema.get("properties", {}).keys():
                # Never echo extra names or values: either may contain credentials.
                return tool_result(mcp_setup.error_payload(service.RequestError(
                    "정의되지 않은 추가 인자는 사용할 수 없습니다. 키는 환경변수로 설정합니다(BYOK).")), error=True)
            return await super().call_tool(name, arguments)
        except Exception:
            # SDK validation/unknown-tool errors must also retain notice and never echo arguments.
            return tool_result(mcp_setup.error_payload(service.RequestError(
                "도구 호출 실패: 도구 이름과 입력 형식을 확인하세요.")), error=True)


def create_server(jobs: Jobs | None = None) -> FastMCP:
    jobs = jobs or Jobs()
    server = PublicMCP("policy-preview")

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
        return guarded(lambda: mcp_setup.try_example(example))

    @server.tool()
    def find_notice(query: str = "", page: StrictInt = 1) -> CallToolResult:
        """현재 의견을 받는 입법예고를 무료로 찾습니다. 검색어를 생략하면 최근 목록이며 키가 없으면 공개 페이지를 읽습니다."""
        return guarded(lambda: mcp_notices.find_notice(query, page))

    @server.tool()
    def get_notice(seq: str, mapping_lbic_id: str = "", announce_type: str = "") -> CallToolResult:
        """고른 입법예고의 이유·주요내용 원문과 estimate에 넣을 policy_text를 무료로 가져옵니다. 분석은 자동 시작하지 않습니다."""
        return guarded(lambda: mcp_notices.get_notice(seq, mapping_lbic_id, announce_type))

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
