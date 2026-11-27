"""MCP stdio tools. All protocol output belongs to the SDK; keys come only from env."""
import json
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent
from typing import Literal

from pydantic import StrictBool, StrictInt

from . import mcp_copy, mcp_guide, public_rules, safety_gate, service, mcp_setup, mcp_notices
from .jobs import Jobs
from .condition_schema import Conditions


def tool_result(data: dict, *, error: bool = False, context: str = "") -> CallToolResult:
    # Optional output gate (PP_SAFETY_GATE) before any text reaches the assistant; off by default.
    data = safety_gate.apply(public_rules.envelope(data))
    if "summary" in data:
        text = data["summary"]["text"]
    else:
        result = data.get('result', {})
        reaction = data.get('status') == 'completed' and bool(result)
        prefix = (result.get('trial_notice') if result.get('mode') == 'mock' else public_rules.NOTICE) if reaction else context
        # Keep the full safety notice in result files, but do not repeat it on lookups,
        # estimates, setup checks, save confirmations or input errors.
        visible = data if reaction else {k: v for k, v in data.items() if k != 'notice'}
        text = (prefix + '\n' if prefix else '') + json.dumps(visible, ensure_ascii=False)
    content = [TextContent(type="text", text=text)]
    if data.get('status') == 'completed' and (data.get('mode') == 'mock' or data.get('result', {}).get('mode') == 'mock'):
        data['assistant_guidance'] = '답변 맨 위 첫 줄에 다음 문장을 그대로 전달하세요: ' + mcp_setup.TRIAL_NOTICE
        content.append(TextContent(type="text", text=data['assistant_guidance']))
    return CallToolResult(content=content,
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
            if name in {'estimate', 'start_run'} and arguments.get('conditions') is not None:
                try:
                    service.normalize_conditions(arguments['conditions'])
                except service.RequestError as exc:
                    return tool_result(mcp_setup.error_payload(exc), error=True)
            return await super().call_tool(name, arguments)
        except Exception:
            # SDK validation errors must also retain notice and never echo arguments.
            return protocol_error("invalid_value" if tool else "unknown_tool")


def create_server(jobs: Jobs | None = None) -> FastMCP:
    safety_gate.mode()  # an invalid PP_SAFETY_GATE stops startup instead of failing every tool call
    jobs = jobs or Jobs()
    server = PublicMCP(mcp_copy.SERVER_NAME, instructions=mcp_copy.INSTRUCTIONS)
    mcp_guide.register(server)

    def guarded(call, context=""):
        try:
            data = call()
            return tool_result(data, error=data.get("status") == "failed", context=context)
        except Exception as exc:
            return tool_result(mcp_setup.error_payload(exc), error=True)

    @server.tool()
    def check_setup() -> CallToolResult:
        """무료 준비 점검: 키·합성 인물 패널·예시 자료·실행 모드를 확인합니다. 비밀값은 표시하지 않습니다."""
        return guarded(mcp_setup.check_setup, "설정 확인이며 분석 결과가 아닙니다.")

    @server.tool()
    def try_example(example: str = "subway-free-ride") -> CallToolResult:
        """키·패널 없이 공개 예시의 보관 결과를 읽습니다. 새 분석이 아니며 외부 전송과 요금은 없습니다."""
        return guarded(lambda: jobs.try_example(example))

    @server.tool()
    def find_notice(query: str = "", page: StrictInt = 1) -> CallToolResult:
        """현재 의견을 받는 입법예고를 무료로 찾습니다. 검색어를 생략하면 최근 목록이며 키가 없으면 공개 페이지를 읽습니다."""
        return guarded(lambda: mcp_notices.find_notice(query, page), "입법예고 조회이며 분석 결과가 아닙니다.")

    @server.tool()
    def get_notice(seq: str, mapping_lbic_id: str = "", announce_type: str = "") -> CallToolResult:
        """고른 입법예고의 이유·주요내용 원문과 estimate에 넣을 policy_text를 무료로 가져옵니다. 분석은 자동 시작하지 않습니다."""
        return guarded(lambda: mcp_notices.get_notice(seq, mapping_lbic_id, announce_type), "입법예고 원문 조회이며 분석 결과가 아닙니다.")

    @server.tool()
    def estimate(policy_text: str, sample: StrictInt = service.DEFAULT_SAMPLE, i_confirm_public: StrictBool = False, limits: dict | None = None, seed: StrictInt = 42, conditions: Conditions = None) -> CallToolResult:
        """Show approximate USD and duration before a paid run. No key needed."""
        return guarded(lambda: jobs.estimate(policy_text, sample, seed, i_confirm_public=i_confirm_public, limits=limits, conditions=conditions), "비용·시간 견적이며 분석 결과가 아닙니다.")

    @server.tool()
    def start_run(policy_text: str | None = None, sample: StrictInt | None = None, seed: StrictInt | None = None, i_confirm_public: StrictBool | None = None, limits: dict | None = None, plan_id: str | None = None, conditions: Conditions = None) -> CallToolResult:
        """견적의 plan_id로 실행합니다. 유료 실행은 비용 동의를 받고, 요청한 0원 체험은 바로 실행합니다. 조건이 바뀌면 재견적하세요."""
        return guarded(lambda: jobs.start_planned(policy_text, sample, seed, i_confirm_public=i_confirm_public, limits=limits, plan_id=plan_id, conditions=conditions))

    @server.tool()
    def get_run(id: str, view: Literal["summary", "full"] = "summary") -> CallToolResult:
        """단계·진행 정도·예상 남은 시간과 완료 시 한 장 요약을 봅니다. 전체 기록은 view=full. 재시작 전 save_review로 저장하세요."""
        return guarded(lambda: jobs.get(id, view=view))

    @server.tool()
    def save_review(id: str, path: str | None = None) -> CallToolResult:
        """완료된 결과를 고지·출처와 함께 새 JSON 파일로 저장합니다. 기본은 홈 아래 결과 폴더, 상대 경로도 홈 기준이며 기존 파일은 덮어쓰지 않습니다."""
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
