"""MCP prompts, resources and tool copy that tell people what to say. Wording lives in mcp_copy.

Connection points in mcp.py: ``dress_tools`` in ``list_tools`` and ``register`` in ``create_server``.
Prompts read the live tool list, so a step that needs a tool another package adds (try_example,
check_setup, get_run's summary view, slice_results) appears once that tool is registered, with no edit here.
"""
from __future__ import annotations

import math

from mcp.server.fastmcp.prompts.base import Prompt, PromptArgument, UserMessage
from mcp.server.fastmcp.resources import TextResource
from mcp.types import EmbeddedResource, TextContent, TextResourceContents

from . import mcp_copy
from .field_log import CSV_COLUMNS


def dress_tools(tools):
    """Overlay Korean titles and descriptions onto listed tools and their argument schemas."""
    for tool in tools:
        properties = tool.inputSchema.get("properties", {})
        copy = mcp_copy.TOOLS.get(tool.name) or mcp_copy.PREPARED_TOOLS.get(tool.name)
        if copy is not None:
            tool.title = copy.title
            tool.description = copy.describe(properties)
        for arg, schema in properties.items():
            if arg in mcp_copy.ARGS:
                schema["title"] = mcp_copy.ARGS[arg].title
                schema["description"] = mcp_copy.ARGS[arg].description
    return tools


def _clean(value) -> str:
    # Prompt values are pasted by the person; keep them on one line and out of code spans.
    return " ".join(str(value or "").replace("`", "").split())[:200]


def _example_key(choice) -> tuple[str, bool]:
    choice = _clean(choice)
    if not choice:
        return mcp_copy.DEFAULT_EXAMPLE, True
    for key, ex in mcp_copy.EXAMPLES.items():
        # Accept the id, the full title, or any word of two or more letters from the title.
        if choice == key or choice in ex.title or any(len(w) >= 2 and w in ex.title for w in choice.split()):
            return key, True
    return mcp_copy.DEFAULT_EXAMPLE, False


def _cap_text(value) -> str:
    try:
        cap = float(_clean(value))
    except ValueError:
        return mcp_copy.COST_CAP_ASK
    if not math.isfinite(cap) or cap < 0:
        return mcp_copy.COST_CAP_ASK
    return mcp_copy.fill(mcp_copy.COST_CAP_GIVEN, {"max_cost_usd": f"{cap:g}"})


def _available(tools) -> set[str]:
    names = set()
    for tool in tools:
        names.add(tool.name)
        names.update(f"{tool.name}.{arg}" for arg in tool.inputSchema.get("properties", {}))
    return names


def render_prompt(key: str, arguments: dict, available: set[str]) -> tuple[str, list[str]]:
    """Return the instruction text and the resource URIs to attach in full.

    Attaching matters: some clients let only the person, not the AI, open resources.
    """
    copy = mcp_copy.PROMPTS[key]
    values, lines, pasted, attach = {}, [], [], []
    if key == "free_example":
        values["example"], found = _example_key(arguments.get("example"))
        if not found:
            lines.append(mcp_copy.EXAMPLE_NOT_FOUND)
        attach.append(f"pp://examples/{values['example']}")
        if "try_example" not in available:
            attach.append("pp://examples/result-summary")
    elif key == "cost_first":
        values["max_cost_usd"] = _cap_text(arguments.get("max_cost_usd"))
        pasted = [mcp_copy.PASTED_POLICY, "```text", str(arguments.get("policy_text") or "").strip(), "```"]
    elif key == "read_result":
        values["run_id"] = _clean(arguments.get("run_id"))
    elif key == "more_numbers":
        values["run_id"] = _clean(arguments.get("run_id"))
        # The question is the person's own words; quotes are dropped so it stays one quoted phrase.
        values["question"] = _clean(arguments.get("question")).replace('"', "'") or mcp_copy.NO_QUESTION
    elif key == "field_notes":
        run_id = _clean(arguments.get("run_id"))
        values["columns"] = ", ".join(CSV_COLUMNS)
        values["compare"] = (mcp_copy.fill(mcp_copy.FIELD_COMPARE, {"run_id": run_id}) if run_id
                             else mcp_copy.FIELD_NO_COMPARE)
        pasted = [mcp_copy.PASTED_NOTES, "```text", str(arguments.get("notes") or "").strip(), "```"]
    steps = []
    for step in copy.steps:
        text = step.text if step.needs is None or step.needs in available else step.fallback
        if text:
            steps.append(f"{len(steps) + 1}. {mcp_copy.fill(text, values)}")
    head = [mcp_copy.fill(mcp_copy.PROMPT_HEADER, {"title": copy.title}), *lines, *steps]
    if copy.notice:
        head.append(mcp_copy.PROMPT_NOTICE)
    head.append(mcp_copy.PROMPT_NEXT + "\"" + copy.next_step + "\"")
    return "\n".join(head + ([""] + pasted if pasted else [])), attach


def _prompt(server, key: str) -> Prompt:
    copy = mcp_copy.PROMPTS[key]

    async def fn(**arguments) -> list[UserMessage]:
        text, attach = render_prompt(key, arguments, _available(await server.list_tools()))
        return [UserMessage(content=TextContent(type="text", text=text)),
                *(UserMessage(content=EmbeddedResource(type="resource", resource=TextResourceContents(
                    uri=uri, mimeType="text/markdown", text=resource_text(uri)))) for uri in attach)]

    arguments = [PromptArgument(name=name, description=f"{arg.title}: {arg.description}", required=required)
                 for name, (arg, required) in copy.args.items()]
    return Prompt(name=key, title=copy.title, description=copy.description, arguments=arguments, fn=fn)


def resource_text(uri: str) -> str:
    if uri == "pp://guide/start":
        return mcp_copy.GUIDE_START
    if uri == "pp://examples/result-summary":
        return mcp_copy.result_summary_markdown()
    return mcp_copy.example_markdown(uri.removeprefix("pp://examples/"))


def register(server) -> None:
    """Add the prompts and read-only resources; nothing here spends money or reads keys."""
    for key in mcp_copy.PROMPTS:
        server.add_prompt(_prompt(server, key))
    for uri, copy in mcp_copy.RESOURCES.items():
        server.add_resource(TextResource(uri=uri, name=copy.name, title=copy.title, description=copy.description,
                                         mime_type="text/markdown", text=resource_text(uri)))
