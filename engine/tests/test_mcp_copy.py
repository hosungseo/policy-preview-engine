"""MCP copy rules: plain Korean, one cause / one action / one free option, prompts, resources, README."""
import asyncio
import json
import re
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import Tool

from pp import field_log, mcp, mcp_copy, mcp_guide, public_rules, service
from pp.jobs import Jobs

ROOT = Path(__file__).resolve().parents[2]
SECRET = "sk-ant-copy-test-secret"

CODE = re.compile(r"`[^`]*`")
LINK = re.compile(r"(?:pp|https?)://\S+|console\.anthropic\.com")
PLACEHOLDER = re.compile(r"\{[a-z_]+\}")
# Proper names people need to recognise; everything else in Latin letters counts as jargon.
ALLOWED = re.compile(r"Anthropic API 키|Claude Code|Claude|Anthropic|AI|CSV|\d+GB")
JARGON = ["환경변수", "환경 변수", "인자", "파라미터", "매개변수", "토큰", "헤더", "스키마", "엔드포인트",
          "페이로드", "쿼리", "호출", "서버", "프로세스", "해시", "리소스", "프롬프트", "디버그", "캐시",
          "세션", "타임아웃", "폴링", "BYOK"]
MAX_SENTENCE = 110


def jargon(text: str, *, code_allowed: bool) -> list[str]:
    """Return jargon found in prose; code spans are allowed only in AI-facing text."""
    if not code_allowed and CODE.search(text):
        return ["code span in people-facing text"]
    prose = ALLOWED.sub(" ", LINK.sub(" ", PLACEHOLDER.sub(" ", CODE.sub(" ", text))))
    return re.findall(r"[A-Za-z]{2,}", prose) + [word for word in JARGON if word in prose]


def sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.?!])\s+|\n+", text) if s.strip()]


def one_sentence(text: str) -> bool:
    return len(re.findall(r"[.?!](?=\s|$)", text)) == 1 and text.rstrip().endswith((".", "?", "!"))


def people_facing() -> list[tuple[str, str]]:
    """Text a person reads directly in a client: titles, menu text, pasted-box labels, resources."""
    items = [(f"tool {k} title", c.title) for k, c in mcp_copy.TOOLS.items()]
    items += [(f"arg {k} title", c.title) for k, c in mcp_copy.ARGS.items()]
    for key, prompt in mcp_copy.PROMPTS.items():
        items += [(f"prompt {key} title", prompt.title), (f"prompt {key} description", prompt.description),
                  (f"prompt {key} next", prompt.next_step)]
        items += [(f"prompt {key} box {name}", f"{arg.title}: {arg.description}")
                  for name, (arg, _) in prompt.args.items()]
    items += [(f"resource {uri}", f"{c.title} {c.description}") for uri, c in mcp_copy.RESOURCES.items()]
    items += [("guide", mcp_copy.GUIDE_START), ("result summary", mcp_copy.result_summary_markdown()),
              ("example footer", mcp_copy.EXAMPLE_FOOTER)]
    return items


def ai_facing() -> list[tuple[str, str]]:
    """Text the AI assistant reads to choose and run tools; code words must sit in backticks."""
    items = [("instructions", mcp_copy.INSTRUCTIONS)]
    for key, tool in mcp_copy.TOOLS.items():
        items.append((f"tool {key} description", tool.description))
        items += [(f"tool {key} when {arg}", text) for arg, text in tool.when_arg]
    items += [(f"arg {k} description", c.description) for k, c in mcp_copy.ARGS.items()]
    for key, prompt in mcp_copy.PROMPTS.items():
        for i, step in enumerate(prompt.steps):
            items += [(f"prompt {key} step {i}", text) for text in (step.text, step.fallback) if text]
    items += [(name, getattr(mcp_copy, name)) for name in (
        "PROMPT_HEADER", "PROMPT_NEXT", "PASTED_POLICY", "PASTED_NOTES", "EXAMPLE_NOT_FOUND",
        "FIELD_COMPARE", "FIELD_NO_COMPARE", "COST_CAP_GIVEN", "COST_CAP_ASK")]
    items += [(f"error {code}", copy.text()) for code, copy in mcp_copy.ERRORS.items()]
    return items


@pytest.mark.parametrize("where,text", people_facing())
def test_people_facing_copy_uses_plain_korean(where, text):
    assert text.strip(), where
    assert jargon(text, code_allowed=False) == [], where
    assert all(len(s) <= MAX_SENTENCE for s in sentences(text)), where


@pytest.mark.parametrize("where,text", ai_facing())
def test_ai_facing_copy_keeps_code_words_in_backticks(where, text):
    assert text.strip(), where
    assert jargon(text, code_allowed=True) == [], where
    assert all(len(s) <= MAX_SENTENCE for s in sentences(CODE.sub("x", text))), where


@pytest.mark.parametrize("code", sorted(mcp_copy.ERRORS))
def test_errors_give_one_cause_one_action_and_a_free_option(code):
    copy = mcp_copy.ERRORS[code]
    assert one_sentence(copy.cause) and one_sentence(copy.action) and one_sentence(copy.free), code
    assert any(word in copy.free for word in ("무료", "키 없이", "돈이 들지 않")), code
    # Unrelated warnings stay out of error copy.
    assert public_rules.WARNING not in copy.text()


def test_error_placeholders_fill_and_other_braces_stay():
    text = mcp_copy.error("estimate_over_cap", high=2.48, cap=2)
    assert "최대 2.48달러" in text and "상한 2달러" in text and "{" not in text
    assert mcp_copy.fill('`{"max_cost_usd": 2}` {x}', {"x": "y"}) == '`{"max_cost_usd": 2}` y'


def test_instructions_are_three_lines_with_guide_phrases():
    lines = mcp_copy.INSTRUCTIONS.splitlines()
    assert len(lines) == 3 and all(line.strip() for line in lines)
    assert "`estimate`" in lines[2] and "`start_run`" in lines[2]
    for phrase in re.findall(r'"([^"]+)"', lines[1]):
        assert phrase in mcp_copy.GUIDE_START, phrase


def session_run(server, scenario):
    async def main():
        async with create_connected_server_and_client_session(server._mcp_server) as session:
            init = await session.initialize()
            return await scenario(session, init)
    return asyncio.run(main())


@pytest.fixture
def server():
    jobs = Jobs()
    try:
        yield mcp.create_server(jobs)
    finally:
        jobs.close()


def mentioned_tools(text: str) -> set[str]:
    return {word for word in re.findall(r"`([a-z_]+)", text) if word in mcp_copy.TOOLS}


def test_protocol_carries_instructions_titles_and_argument_copy(server):
    async def scenario(session, init):
        tools = (await session.list_tools()).tools
        return init.instructions, tools
    instructions, tools = session_run(server, scenario)
    assert instructions == mcp_copy.INSTRUCTIONS
    assert {t.name for t in tools} == {"estimate", "start_run", "get_run"}
    for tool in tools:
        copy = mcp_copy.TOOLS[tool.name]  # every registered tool needs copy, including later ones
        properties = tool.inputSchema["properties"]
        assert tool.title == copy.title and tool.description == copy.describe(properties)
        assert tool.inputSchema["additionalProperties"] is False
        for arg, schema in properties.items():
            assert schema["title"] == mcp_copy.ARGS[arg].title
            assert schema["description"] == mcp_copy.ARGS[arg].description
        assert mentioned_tools(tool.description) <= {t.name for t in tools}


def test_prepared_copy_applies_when_other_packages_register_tools(server):
    def try_example(example: str = "subway-free-ride") -> dict:
        return {}

    def check_setup() -> dict:
        return {}

    server.add_tool(try_example, name="try_example")
    server.add_tool(check_setup, name="check_setup")

    async def scenario(session, init):
        tools = {t.name: t for t in (await session.list_tools()).tools}
        prompt = await session.get_prompt("free_example", {})
        return tools, prompt
    tools, prompt = session_run(server, scenario)
    assert tools["try_example"].title == mcp_copy.TOOLS["try_example"].title
    assert tools["try_example"].inputSchema["properties"]["example"]["title"] == mcp_copy.ARGS["example"].title
    assert tools["check_setup"].description == mcp_copy.TOOLS["check_setup"].description
    text = prompt.messages[0].content.text
    assert "`try_example`" in text and "`check_setup`" in text
    # With a real free trial the hand-written summary is no longer attached.
    uris = [str(m.content.resource.uri) for m in prompt.messages[1:]]
    assert uris == ["pp://examples/subway-free-ride"]

    # A get_run with a summary view switches its description and the reading prompt.
    get_run = Tool(name="get_run", inputSchema={"type": "object", "properties": {"id": {}, "view": {}}})
    mcp_guide.dress_tools([get_run])
    assert get_run.description == mcp_copy.TOOLS["get_run"].when_arg[0][1]
    text, _ = mcp_guide.render_prompt("read_result", {"run_id": "abc"}, {"get_run", "get_run.view"})
    assert 'view="summary"' in text and 'id="abc"' in text


def test_prompts_list_boxes_and_render_with_next_step(server):
    policy = mcp_copy.EXAMPLES["subway-free-ride"].text

    async def scenario(session, init):
        listed = (await session.list_prompts()).prompts
        rendered = {
            "free_example": await session.get_prompt("free_example", {}),
            "cost_first": await session.get_prompt("cost_first", {"policy_text": policy, "max_cost_usd": "2"}),
            "read_result": await session.get_prompt("read_result", {"run_id": "abc123"}),
            "field_notes": await session.get_prompt("field_notes", {"notes": "11월 20일 경로당 방문 메모"}),
        }
        return listed, rendered
    listed, rendered = session_run(server, scenario)
    assert [p.name for p in listed] == list(mcp_copy.PROMPTS)
    available = {"estimate", "start_run", "get_run"}
    for prompt in listed:
        copy = mcp_copy.PROMPTS[prompt.name]
        assert prompt.title == copy.title and prompt.description == copy.description
        assert [(a.name, a.required) for a in prompt.arguments] == [(n, r) for n, (_, r) in copy.args.items()]
        assert all(a.description.startswith(copy.args[a.name][0].title + ":") for a in prompt.arguments)
        text = rendered[prompt.name].messages[0].content.text
        assert text.startswith(mcp_copy.fill(mcp_copy.PROMPT_HEADER, {"title": copy.title}))
        assert copy.next_step in text
        assert (mcp_copy.PROMPT_NOTICE in text) == copy.notice
        # Prompts never send the AI to a tool that is not registered yet.
        assert mentioned_tools(text) <= available, prompt.name
        assert "{" not in CODE.sub("", text.split("```")[0]), prompt.name
    free = rendered["free_example"].messages
    assert [str(m.content.resource.uri) for m in free[1:]] == ["pp://examples/subway-free-ride",
                                                            "pp://examples/result-summary"]
    assert free[1].content.resource.text == mcp_copy.example_markdown("subway-free-ride")
    cost = rendered["cost_first"].messages[0].content.text
    assert policy.strip() in cost and mcp_copy.PASTED_POLICY in cost and "2달러로 정했으니" in cost
    assert 'id="abc123"' in rendered["read_result"].messages[0].content.text
    notes = rendered["field_notes"].messages[0].content.text
    assert ", ".join(field_log.CSV_COLUMNS) in notes and mcp_copy.FIELD_NO_COMPARE in notes


def test_prompt_inputs_are_cleaned_and_examples_resolved():
    text, attach = mcp_guide.render_prompt("free_example", {"example": "농어촌 기본소득"}, set())
    assert attach[0] == "pp://examples/rural-basic-income" and mcp_copy.EXAMPLE_NOT_FOUND not in text
    text, attach = mcp_guide.render_prompt("free_example", {"example": "없는 예시"}, set())
    assert attach[0] == "pp://examples/subway-free-ride" and mcp_copy.EXAMPLE_NOT_FOUND in text
    text, _ = mcp_guide.render_prompt("cost_first", {"policy_text": "문안", "max_cost_usd": "많이"}, set())
    assert mcp_copy.COST_CAP_ASK in text
    text, _ = mcp_guide.render_prompt("read_result", {"run_id": "ab`c\nd"}, {"get_run"})
    assert 'id="abc d"' in text
    text, _ = mcp_guide.render_prompt("field_notes", {"notes": "메모", "run_id": "r1"}, {"get_run"})
    assert 'id="r1"' in text and "`hit`" in text


def test_resources_list_and_read(server):
    async def scenario(session, init):
        listed = (await session.list_resources()).resources
        bodies = {str(r.uri): (await session.read_resource(r.uri)).contents[0].text for r in listed}
        return listed, bodies
    listed, bodies = session_run(server, scenario)
    assert {str(r.uri) for r in listed} == set(mcp_copy.RESOURCES)
    for resource in listed:
        copy = mcp_copy.RESOURCES[str(resource.uri)]
        assert resource.title == copy.title and resource.mimeType == "text/markdown"
        assert bodies[str(resource.uri)] == mcp_guide.resource_text(str(resource.uri))
    assert len([u for u in bodies if u.startswith("pp://examples/") and u != "pp://examples/result-summary"]) == 3


@pytest.mark.parametrize("key", sorted(mcp_copy.EXAMPLES))
def test_example_policies_match_engine_files_and_pass_input_rules(key):
    example = mcp_copy.EXAMPLES[key]
    source = json.loads((ROOT / "engine" / "policies" / f"{key}.json").read_text())
    assert example.text == source["text"] and example.title == source["title"] and example.kind == source["kind"]
    assert public_rules.input_problem(example.text) is None
    assert service.estimate(example.text, 30)["estimated_cost_usd"]["low"] > 0  # free, no key


def test_example_result_summary_follows_output_rules():
    result = mcp_copy.EXAMPLE_RESULT
    policy = mcp_copy.EXAMPLES[result["example"]].text
    for card in result["meet_first"]:
        assert f"{card['clause']}. {card['quote']}" in policy
    # Everything except verbatim quotes must pass the same output rules as engine results.
    plain = {k: v for k, v in result.items() if k != "meet_first"}
    plain["meet_first"] = [{k: v for k, v in card.items() if k != "quote"} for card in result["meet_first"]]
    warnings = []
    assert public_rules.check_output(plain, policy, warnings) == plain and warnings == []
    markdown = mcp_copy.result_summary_markdown()
    assert public_rules.NOTICE in markdown and result["label"] in markdown


def test_mcp_layer_errors_use_copy_and_never_echo(server):
    async def scenario(session, init):
        return [await session.call_tool("estimate", {"policy_text": "도시철도 지원", SECRET: SECRET}),
                await session.call_tool("missing_tool", {"api_key": SECRET}),
                await session.call_tool("estimate", {"policy_text": "도시철도 지원", "sample": "많이"})]
    extra, unknown, invalid = session_run(server, scenario)
    for result, code in [(extra, "extra_argument"), (unknown, "unknown_tool"), (invalid, "invalid_value")]:
        assert result.isError
        assert result.structuredContent["error"] == mcp_copy.error(code)
        assert result.content[0].text.splitlines()[0] == public_rules.NOTICE
        assert SECRET not in result.model_dump_json()


def test_readme_quick_start_matches_copy():
    readme = (ROOT / "README.md").read_text()
    section = readme[readme.index("### MCP로 쓰기"):readme.index("### 결과에 함께 남는 실행 기록")]
    steps = [section.index(f"**{n}단계.") for n in (1, 2, 3)]
    assert steps == sorted(steps)
    assert "claude mcp add" in section and '"무료 예시 보여 줘"' in section and "**나**:" in section
    for prompt in mcp_copy.PROMPTS.values():
        assert prompt.title in section
    for uri in mcp_copy.RESOURCES:
        assert uri.removeprefix("pp://examples/") in section
    assert f"/mcp__{mcp_copy.SERVER_NAME}__free_example" in section
