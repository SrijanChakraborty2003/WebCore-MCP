import asyncio
import json
import sys
from typing import Any

# Ensure immediate unbuffered console output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8")

from fastmcp import Client
from app.config import settings


def print_banner(title: str):
    print("\n" + "=" * 65)
    print(f"  {title}")
    print("=" * 65)


def print_result(title: str, data: Any):
    print(f"\n--- [{title}] ---")
    if isinstance(data, (dict, list)):
        print(json.dumps(data, indent=2, ensure_ascii=False))
    elif hasattr(data, "model_dump"):
        print(json.dumps(data.model_dump(), indent=2, ensure_ascii=False))
    else:
        print(data)


async def main():
    print_banner("Testing Browser-Based MCP Server via Tool Calls")

    # Check if server is running on port 8000 via fast socket check
    import socket
    def is_port_open(host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            return False

    target_url = settings.sse_url
    is_server_up = is_port_open(settings.mcp_host, settings.mcp_port)

    if is_server_up:
        print(f"[INFO] Connecting to running MCP server at {target_url}...")
        client_target = target_url
    else:
        print(f"[INFO] Server not running on {target_url}.")
        print("[INFO] Executing tools via direct in-process MCP client from server.py...")
        from server import mcp
        client_target = mcp

    async with Client(client_target) as client:
        # 1. List Available Tools
        print_banner("1. Listing Available Tools")
        tools = await client.list_tools()
        for t in tools:
            desc = t.description.splitlines()[0] if t.description else ""
            print(f"  - Tool: {t.name:<25} {desc}")

        # 2. Call health_check
        print_banner("2. Calling tool: health_check")
        health_res = await client.call_tool("health_check", {})
        print_result("health_check result", health_res.data)

        # Parse CLI options
        provider = None
        skip_next = False
        prompt_parts = []
        for i, arg in enumerate(sys.argv[1:]):
            if skip_next:
                skip_next = False
                continue
            if arg == "--provider" and i + 1 < len(sys.argv[1:]):
                provider = sys.argv[1:][i + 1].lower()
                skip_next = True
            elif arg.startswith("--provider="):
                provider = arg.split("=", 1)[1].lower()
            elif arg in ("--chatgpt", "-gpt"):
                provider = "chatgpt"
            elif arg in ("--claude", "-c"):
                provider = "claude"
            elif arg in ("--deepseek", "-d"):
                provider = "deepseek"
            elif arg in ("--google", "-google"):
                provider = "google"
            elif arg in ("--gemini", "-g"):
                provider = "gemini"
            elif not arg.startswith("-"):
                prompt_parts.append(arg)

        # 3. Handle Direct Google Search
        if "--google" in sys.argv:
            idx = sys.argv.index("--google")
            query_parts = sys.argv[idx + 1:]
            query = " ".join(query_parts) if query_parts else "Latest stock market trend and AI news"
            print_banner(f"3. Google Search via search_google")
            print(f"  Query: \"{query}\"")
            search_res = await client.call_tool("search_google", {"query": query, "num_results": 10})
            print_result("search_google result", search_res.data)

        # 4. Handle Web Search
        elif "--search" in sys.argv:
            idx = sys.argv.index("--search")
            query_parts = sys.argv[idx + 1:]
            query = " ".join(query_parts) if query_parts else "Latest advancements in artificial intelligence"
            search_provider = provider if provider in ("google", "chatgpt", "deepseek", "gemini") else "google"
            print_banner(f"3. Web Search via search_web ({search_provider})")
            print(f"  Query: \"{query}\"")
            search_res = await client.call_tool("search_web", {"query": query, "provider": search_provider})
            print_result("search_web result", search_res.data)

        # 5. Handle Image Generation
        elif "--image" in sys.argv:
            idx = sys.argv.index("--image")
            img_args = sys.argv[idx + 1:]
            img_prompt = " ".join(img_args) if img_args else "A sleek modern supersonic passenger airplane flying above clouds"
            img_provider = provider if provider in ("gemini", "chatgpt") else "gemini"
            tool_name = f"generate_image_{img_provider}"
            print_banner(f"3. Image Generation via {tool_name}")
            print(f"  Prompt: \"{img_prompt}\"")
            img_res = await client.call_tool(tool_name, {"prompt": img_prompt, "timeout": 180})
            print_result(f"{tool_name} result", img_res.data)
            if isinstance(img_res.data, dict) and img_res.data.get("file_path"):
                print(f"\n  [SUCCESS] Generated image saved to: {img_res.data['file_path']}")

        # 6. Default Chat Tool Call
        else:
            prompt = " ".join(prompt_parts) if prompt_parts else "Reply with ONLY the word SUCCESS."
            chat_provider = provider or "gemini"
            tool_name = f"ask_{chat_provider}"
            print_banner(f"3. Calling tool: {tool_name}")
            print(f"  Prompt: \"{prompt}\"")
            ask_res = await client.call_tool(tool_name, {"prompt": prompt, "timeout": 120})
            print_result(f"{tool_name} result", ask_res.data)
            if isinstance(ask_res.data, dict) and ask_res.data.get("type") == "image":
                print(f"\n  [SUCCESS] Image detected & saved to: {ask_res.data.get('file_path')}")

    print_banner("All Tool Calls Complete!")
    import os
    os._exit(0)


if __name__ == "__main__":
    asyncio.run(main())
