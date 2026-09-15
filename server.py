import asyncio
import sys
from typing import Dict, Any, Literal

from fastmcp import FastMCP

from app.browser import browser_lock, browser_manager, logger
from app.config import settings
from app.providers import (
    GeminiBrowser,
    ChatGPTBrowser,
    ClaudeBrowser,
    DeepSeekBrowser,
    GoogleSearchBrowser,
)
from app.parsers import format_error

# Initialize FastMCP Server
mcp = FastMCP(
    name=settings.server_name,
)

# Initialize Provider Instances
gemini_provider = GeminiBrowser()
chatgpt_provider = ChatGPTBrowser()
claude_provider = ClaudeBrowser()
deepseek_provider = DeepSeekBrowser()
google_provider = GoogleSearchBrowser()


@mcp.tool()
async def health_check() -> Dict[str, Any]:
    """
    Check the health status of the MCP server, Chrome remote debugging port,
    and connectivity across all providers (Gemini, ChatGPT, Claude, DeepSeek).
    """
    chrome_status = browser_manager.check_chrome_status()

    result = {
        "server": {
            "name": settings.server_name,
            "version": settings.server_version,
            "status": "healthy",
            "headless": settings.chrome_headless,
        },
        "chrome": {
            "debugger_address": settings.debugger_address,
            "running": chrome_status["running"],
            "details": chrome_status,
        },
        "providers": {
            "gemini": {"url": settings.gemini_url, "ready": False, "auth_status": "unknown"},
            "chatgpt": {"url": settings.chatgpt_url, "ready": False, "auth_status": "unknown"},
            "claude": {"url": settings.claude_url, "ready": False, "auth_status": "unknown"},
            "deepseek": {"url": settings.deepseek_url, "ready": False, "auth_status": "unknown"},
            "google": {"url": "https://www.google.com", "ready": True, "auth_status": "not_required"},
        },
        "captcha_solver": {
            "type": "browser-use (ollama vision)",
            "enabled": settings.enable_vision_captcha_solver,
            "ollama_endpoint": settings.ollama_base_url,
            "vision_model": settings.ollama_vision_model,
        },
    }

    if chrome_status["running"]:
        async with browser_lock:
            try:
                driver = await asyncio.to_thread(browser_manager.get_driver)
                
                # Check auth states
                for name, provider in [
                    ("gemini", gemini_provider),
                    ("chatgpt", chatgpt_provider),
                    ("claude", claude_provider),
                    ("deepseek", deepseek_provider),
                ]:
                    try:
                        auth_ok = await asyncio.to_thread(provider.check_auth)
                        result["providers"][name]["ready"] = True
                        result["providers"][name]["auth_status"] = "authenticated" if auth_ok else "login_required"
                    except Exception as e:
                        result["providers"][name]["auth_status"] = f"check_failed: {e}"
            except Exception as e:
                for name in result["providers"]:
                    result["providers"][name]["auth_status"] = f"driver_error: {str(e)}"
    else:
        for name in result["providers"]:
            result["providers"][name]["auth_status"] = "chrome_not_running"

    return result


# ==============================================================================
# Google Gemini Tools
# ==============================================================================

@mcp.tool()
async def ask_gemini(prompt: str, timeout: int = 120) -> Dict[str, Any]:
    """
    Ask a question to Google Gemini in a fresh, isolated chat session.
    Automatically detects image generation requests and downloads the generated image.
    
    Args:
        prompt: The user prompt or image description.
        timeout: Maximum seconds to wait for generation (default: 120).
    """
    if not prompt or not prompt.strip():
        return format_error("gemini", "INVALID_PROMPT", "Prompt cannot be empty.")

    async with browser_lock:
        logger.info(f"Processing ask_gemini request (length: {len(prompt)} chars)...")
        return await asyncio.to_thread(gemini_provider.ask, prompt.strip(), timeout)


@mcp.tool()
async def generate_image_gemini(prompt: str, output_name: str = "gemini_image", timeout: int = 180) -> Dict[str, Any]:
    """
    Generate an image using Google Gemini, wait for completion, and download it locally.
    
    Args:
        prompt: Detailed description of the image to generate.
        output_name: Custom base filename for the saved image (default: 'gemini_image').
        timeout: Maximum seconds to wait for image generation (default: 180).
    """
    if not prompt or not prompt.strip():
        return format_error("gemini", "INVALID_PROMPT", "Prompt cannot be empty.")

    async with browser_lock:
        logger.info(f"Processing generate_image_gemini request: '{prompt}'...")
        return await asyncio.to_thread(gemini_provider.generate_image, prompt.strip(), output_name, timeout)


# ==============================================================================
# ChatGPT Tools
# ==============================================================================

@mcp.tool()
async def ask_chatgpt(prompt: str, timeout: int = 120, web_search: bool = False) -> Dict[str, Any]:
    """
    Ask a question to ChatGPT in a fresh, isolated session, with optional web search.
    
    Args:
        prompt: The prompt or question to ask ChatGPT.
        timeout: Maximum seconds to wait for generation (default: 120).
        web_search: Set to True to enable ChatGPT's live web search engine.
    """
    if not prompt or not prompt.strip():
        return format_error("chatgpt", "INVALID_PROMPT", "Prompt cannot be empty.")

    async with browser_lock:
        logger.info(f"Processing ask_chatgpt request (search={web_search}): '{prompt}'...")
        return await asyncio.to_thread(chatgpt_provider.ask, prompt.strip(), timeout, web_search)


@mcp.tool()
async def search_chatgpt(query: str, timeout: int = 120) -> Dict[str, Any]:
    """
    Search the web using ChatGPT's built-in web search and get synthesized answers with sources.
    
    Args:
        query: The search query to look up on the web.
        timeout: Maximum seconds to wait (default: 120).
    """
    if not query or not query.strip():
        return format_error("chatgpt", "INVALID_QUERY", "Search query cannot be empty.")

    async with browser_lock:
        logger.info(f"Processing search_chatgpt request: '{query}'...")
        return await asyncio.to_thread(chatgpt_provider.search, query.strip(), timeout)


@mcp.tool()
async def generate_image_chatgpt(prompt: str, output_name: str = "chatgpt_image", timeout: int = 180) -> Dict[str, Any]:
    """
    Generate an image using ChatGPT (DALL-E 3) and download it locally.
    
    Args:
        prompt: Description of the image to create.
        output_name: Custom base filename for the saved image.
        timeout: Maximum seconds to wait for generation (default: 180).
    """
    if not prompt or not prompt.strip():
        return format_error("chatgpt", "INVALID_PROMPT", "Prompt cannot be empty.")

    async with browser_lock:
        logger.info(f"Processing generate_image_chatgpt request: '{prompt}'...")
        return await asyncio.to_thread(chatgpt_provider.generate_image, prompt.strip(), output_name, timeout)


# ==============================================================================
# Claude Tools
# ==============================================================================

@mcp.tool()
async def ask_claude(prompt: str, timeout: int = 120) -> Dict[str, Any]:
    """
    Ask a question to Claude (Anthropic) in a fresh, isolated chat session.
    
    Args:
        prompt: The user prompt or question for Claude.
        timeout: Maximum seconds to wait for generation (default: 120).
    """
    if not prompt or not prompt.strip():
        return format_error("claude", "INVALID_PROMPT", "Prompt cannot be empty.")

    async with browser_lock:
        logger.info(f"Processing ask_claude request: '{prompt}'...")
        return await asyncio.to_thread(claude_provider.ask, prompt.strip(), timeout)


# ==============================================================================
# DeepSeek Tools
# ==============================================================================

@mcp.tool()
async def ask_deepseek(prompt: str, timeout: int = 150, web_search: bool = False, deepthink: bool = False) -> Dict[str, Any]:
    """
    Ask a question to DeepSeek in a fresh chat session, with optional Web Search or DeepThink reasoning.
    
    Args:
        prompt: The user prompt for DeepSeek.
        timeout: Maximum seconds to wait for generation (default: 150).
        web_search: Set to True to enable DeepSeek's Web Search toggle.
        deepthink: Set to True to enable DeepSeek's DeepThink reasoning toggle.
    """
    if not prompt or not prompt.strip():
        return format_error("deepseek", "INVALID_PROMPT", "Prompt cannot be empty.")

    async with browser_lock:
        logger.info(f"Processing ask_deepseek request (search={web_search}, think={deepthink}): '{prompt}'...")
        return await asyncio.to_thread(deepseek_provider.ask, prompt.strip(), timeout, web_search, deepthink)


@mcp.tool()
async def search_deepseek(query: str, timeout: int = 150) -> Dict[str, Any]:
    """
    Search the web using DeepSeek's Web Search capability.
    
    Args:
        query: The search query to research.
        timeout: Maximum seconds to wait (default: 150).
    """
    if not query or not query.strip():
        return format_error("deepseek", "INVALID_QUERY", "Search query cannot be empty.")

    async with browser_lock:
        logger.info(f"Processing search_deepseek request: '{query}'...")
        return await asyncio.to_thread(deepseek_provider.search, query.strip(), timeout)


# ==============================================================================
# Google Search Tools
# ==============================================================================

@mcp.tool()
async def search_google(query: str, num_results: int = 10, timeout: int = 60) -> Dict[str, Any]:
    """
    Search Google directly using Chrome and extract top organic search results
    (titles, URLs, snippets) along with AI Overviews and Knowledge Panels.
    
    Args:
        query: The search query to look up on Google.
        num_results: Maximum number of search results to return (default: 10).
        timeout: Maximum seconds to wait (default: 60).
    """
    if not query or not query.strip():
        return format_error("google", "INVALID_QUERY", "Search query cannot be empty.")

    async with browser_lock:
        logger.info(f"Processing search_google request: '{query}'...")
        return await asyncio.to_thread(google_provider.search, query.strip(), num_results, timeout)


# ==============================================================================
# Unified Web Search Tool
# ==============================================================================

@mcp.tool()
async def search_web(
    query: str,
    provider: Literal["google", "chatgpt", "deepseek", "gemini"] = "google",
    timeout: int = 120
) -> Dict[str, Any]:
    """
    Search the web using your choice of provider: direct Google Search, ChatGPT Search, DeepSeek Search, or Gemini.
    
    Args:
        query: The search query to look up on the web.
        provider: The provider to use for web search ('google', 'chatgpt', 'deepseek', or 'gemini'). Default is 'google'.
        timeout: Maximum seconds to wait (default: 120).
    """
    if not query or not query.strip():
        return format_error("router", "INVALID_QUERY", "Search query cannot be empty.")

    async with browser_lock:
        logger.info(f"Processing search_web request via {provider}: '{query}'...")
        if provider == "google":
            return await asyncio.to_thread(google_provider.search, query.strip(), 10, timeout)
        elif provider == "chatgpt":
            return await asyncio.to_thread(chatgpt_provider.search, query.strip(), timeout)
        elif provider == "deepseek":
            return await asyncio.to_thread(deepseek_provider.search, query.strip(), timeout)
        elif provider == "gemini":
            search_prompt = f"Search the web and provide detailed, up-to-date information for: {query.strip()}"
            return await asyncio.to_thread(gemini_provider.ask, search_prompt, timeout)
        else:
            return format_error("router", "UNKNOWN_PROVIDER", f"Provider '{provider}' is not supported.")


if __name__ == "__main__":
    transport = "sse"
    if "--stdio" in sys.argv:
        transport = "stdio"

    print("=" * 65)
    print(f"  {settings.server_name} (Multi-Provider: Google, Gemini, ChatGPT, Claude, DeepSeek)")
    print("=" * 65)
    print(f"  Headless:  {settings.chrome_headless}")
    print(f"  Transport: {transport.upper()}")
    if transport == "sse":
        print(f"  Endpoint:  {settings.sse_url}")
    print(f"  Chrome:    Port {settings.debugger_port} (Auto-launch enabled)")
    print("=" * 65)

    # Automatically ensure Chrome is running (headlessly by default) before serving requests
    browser_manager.ensure_chrome_running(headless=settings.chrome_headless)

    if transport == "sse":
        print("  To test tool calls, open another terminal and run:")
        print("    python test.py")
        print("=" * 65)
        mcp.run(
            transport="sse",
            host=settings.mcp_host,
            port=settings.mcp_port,
            show_banner=False,
        )
    else:
        mcp.run(transport="stdio", show_banner=False)
