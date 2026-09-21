#!/usr/bin/env python3
"""Exercise all eight tools through the official MCP SDK over real stdio.

Install the repository first with ``python -m pip install -e '.[integration]'``.
Run ``python scripts/check_mcp_sdk.py --output benchmarks/results/mcp-interop.json``.
The client and server use the same Python environment. Fixtures are temporary,
and the optional JSON result contains no local filesystem paths or source text.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys
import tempfile

import contextproof
from contextproof.evidence import render_bundle

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except ImportError as exc:
    raise SystemExit("Install the integration extra: python -m pip install -e '.[integration]'") from exc


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TOOLS = {
    f"contextproof_{name}" for name in (
        "index", "search", "bundle", "verify", "repair", "capture", "check", "refresh"
    )
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


async def check() -> dict:
    work = ROOT / "work"
    work.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mcp-sdk-", dir=work) as temporary:
        source = Path(temporary)
        (source / "policy.py").write_text("def tax_rate():\n    return 0.10\n", encoding="utf-8")
        (source / "checkout.py").write_text(
            "from policy import tax_rate\n\ndef invoice_total(amount):\n"
            "    return amount * (1 + tax_rate())\n", encoding="utf-8",
        )
        parameters = StdioServerParameters(
            command=sys.executable, args=["-m", "contextproof", "serve", str(source)],
        )
        async with stdio_client(parameters) as streams:
            async with ClientSession(*streams) as session:
                initialized = await session.initialize()
                listing = await session.list_tools()
                names = sorted(tool.name for tool in listing.tools)
                require(set(names) == EXPECTED_TOOLS and len(names) == 8,
                        "server did not expose the expected eight tools")
                called: set[str] = set()

                async def call(name: str, arguments: dict):
                    result = await session.call_tool(name, arguments)
                    require(not result.is_error, f"tool failed: {name}")
                    require(bool(result.content) and result.content[0].type == "text",
                            f"tool did not return JSON text: {name}")
                    called.add(name)
                    return json.loads(result.content[0].text)

                index = await call("contextproof_index", {})
                hits = await call("contextproof_search", {
                    "query": "invoice_total", "method": "bm25",
                })
                bundle = await call("contextproof_bundle", {
                    "query": "invoice_total", "method": "bm25", "budget": 6000,
                })
                verified = await call("contextproof_verify", {"bundle": bundle})
                require(verified["valid"], "initial source bundle was not valid")
                repaired = await call("contextproof_repair", {"bundle": bundle})
                require(bool(repaired["entries"]), "repair discarded unchanged source")
                context = await call("contextproof_capture", {
                    "query": "invoice_total", "budget": 6000,
                })
                initial = await call("contextproof_check", {"context": context})
                require(initial["can_reuse"] and initial["snapshot_consistent"],
                        "initial captured context was not reusable")

                (source / "policy.py").write_text(
                    "def tax_rate():\n    return 0.12\n", encoding="utf-8",
                )
                stale = await call("contextproof_check", {"context": context})
                require(stale["source"]["valid"], "fixture unexpectedly changed caller text")
                require(stale["dependencies"]["status"] == "changed",
                        "dependency edit was not detected")
                require(not stale["can_reuse"] and stale["recommendation"] == "retrieve",
                        "stale dependency context was not rejected")
                refreshed = await call("contextproof_refresh", {"context": context})
                current = await call("contextproof_check", {"context": refreshed})
                require(current["can_reuse"] and current["recommendation"] == "reuse"
                        and current["snapshot_consistent"], "refreshed context was not reusable")
                rendered_bytes = len(render_bundle(refreshed["bundle"]).encode("utf-8"))
                require(rendered_bytes == refreshed["bundle"]["consumed"] <= 6000,
                        "refreshed rendered context violated its budget")
                require(called == EXPECTED_TOOLS, "not all eight tools were called")

                package_root = Path(contextproof.__file__).resolve().parent
                return {
                    "schema_version": 1,
                    "client": "official Python MCP SDK",
                    "client_version": importlib.metadata.version("mcp"),
                    "environment": {"python": platform.python_version(),
                                    "system": platform.system(), "machine": platform.machine()},
                    "server": initialized.server_info.model_dump(exclude_none=True),
                    "protocol_version": initialized.protocol_version,
                    "listed_tools": names, "called_tools": sorted(called),
                    "all_eight_tools_called": called == EXPECTED_TOOLS,
                    "index_snapshot_available": bool(index["snapshot_id"]),
                    "search_hit_count": len(hits),
                    "initial_recommendation": initial["recommendation"],
                    "after_helper_edit": {
                        "source_valid": stale["source"]["valid"],
                        "dependency_status": stale["dependencies"]["status"],
                        "can_reuse": stale["can_reuse"],
                        "recommendation": stale["recommendation"],
                    },
                    "after_refresh": {
                        "can_reuse": current["can_reuse"],
                        "snapshot_consistent": current["snapshot_consistent"],
                        "recommendation": current["recommendation"],
                        "rendered_context_bytes": rendered_bytes, "budget_bytes": 6000,
                    },
                    "implementation_sha256": {
                        f"src/contextproof/{name}": hashlib.sha256(
                            (package_root / name).read_bytes()).hexdigest()
                        for name in ("mcp.py", "session.py", "dependencies.py", "evidence.py", "index.py")
                    },
                    "checker_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    "scope": "Real stdio SDK interoperability on one controlled dependency-edit fixture; "
                             "not a general client compatibility or task-success benchmark.",
                }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="optional JSON result file")
    args = parser.parse_args()
    report = asyncio.run(check())
    output = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
