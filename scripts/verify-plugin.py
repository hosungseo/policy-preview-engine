#!/usr/bin/env python3
"""Exercise an installed bundle through the official MCP Python client.

Prepare that bundle once with `sh <bundle>/scripts/plugin-mcp.sh --prepare`.
Run this script with an interpreter that has mcp installed, under an OS network
deny policy when checking offline operation. No model credentials are forwarded.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def verify(root: Path, harness: str) -> dict:
    manifest = {"claude": ".mcp.json", "codex": "mcp.json", "antigravity": "mcp.json"}[harness]
    server = json.loads((root / manifest).read_text())["mcpServers"]["policy-preview"]
    args = [arg.replace("${CLAUDE_PLUGIN_ROOT}", str(root)).replace("${PLUGIN_ROOT}", str(root))
            for arg in server["args"]]
    # Use clean HOME/cache values supplied by the caller, never the caller's keys.
    env = {key: value for key, value in os.environ.items() if key in {
        "PATH", "HOME", "TMPDIR", "LANG", "XDG_CACHE_HOME", "PP_PLUGIN_CACHE_DIR",
    }}
    env["PP_DATA_DIR"] = str(Path(env["HOME"]) / "no-panel")
    params = StdioServerParameters(command=server["command"], args=args, env=env)
    assert (root / "skills/policy-preview/SKILL.md").is_file()
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = sorted(tool.name for tool in (await session.list_tools()).tools)
            assert {"check_setup", "try_example", "slice_results"} <= set(tools)
            setup = await session.call_tool("check_setup", {})
            assert not setup.isError, setup
            assert setup.structuredContent["keys"]["anthropic_present"] is False
            example = await session.call_tool("try_example", {"example": "subway-free-ride"})
            assert not example.isError, example
            assert example.structuredContent["status"] == "completed"
            run_id = example.structuredContent["id"]
            assert "숫자로 먼저 보기" in example.content[0].text
            sliced = await session.call_tool("slice_results", {"id": run_id, "filters": {"age_band": "60대"}})
            assert not sliced.isError, sliced
            assert sliced.structuredContent["model_calls"] == 0
            assert sliced.structuredContent["cost_usd"] == 0
            assert "60대" in sliced.content[0].text
            return {"harness": harness, "bundle": str(root), "tools": tools,
                    "api_key_present": False, "example": "completed",
                    "numeric_card": True, "slice": "60대", "model_calls": 0, "cost_usd": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--harness", choices=("claude", "codex", "antigravity"), required=True)
    options = parser.parse_args()
    print(json.dumps(asyncio.run(verify(options.bundle.resolve(), options.harness)), ensure_ascii=False, indent=2))
