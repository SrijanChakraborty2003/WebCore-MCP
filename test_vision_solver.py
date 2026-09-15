import asyncio
import sys
import requests
from typing import Optional

# Ensure unbuffered utf-8 console output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8")

from app.config import settings
from app.browser import browser_manager


def print_banner(title: str):
    print("\n" + "=" * 65)
    print(f"  {title}")
    print("=" * 65)


def check_ollama_endpoint(base_url: str, model_name: str) -> bool:
    """Verify if the Ollama endpoint is reachable and check available models."""
    print(f"[INFO] Checking Ollama endpoint at: {base_url}...")
    try:
        resp = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=5.0)
        if resp.status_code == 200:
            data = resp.json()
            models = [m.get("name", "") for m in data.get("models", [])]
            print(f"[SUCCESS] Connected to Ollama server.")
            print(f"[INFO] Available models in Ollama: {', '.join(models) if models else 'None loaded'}")
            
            # Check if requested model or matching prefix exists
            matched = any(model_name.lower() in m.lower() for m in models)
            if matched:
                print(f"[SUCCESS] Configured vision model '{model_name}' found in Ollama!")
            else:
                print(f"[WARNING] Model '{model_name}' not listed in Ollama tags.")
                print(f"          If this is a cloud/remote proxy, it may still work upon invocation.")
            return True
        else:
            print(f"[WARNING] Ollama server responded with HTTP {resp.status_code}.")
            return False
    except requests.exceptions.ConnectionError:
        print(f"[ERROR] Could not connect to Ollama at {base_url}.")
        print(f"        Make sure your Ollama instance is running, e.g.:")
        print(f"          ollama serve")
        print(f"        Or update OLLAMA_BASE_URL in app/config.py / .env if using a remote cloud endpoint.")
        return False
    except Exception as e:
        print(f"[ERROR] Error probing Ollama endpoint: {e}")
        return False


async def test_browser_use_cdp(
    target_url: str = "https://2captcha.com/demo/cloudflare-turnstile",
    base_url: str = settings.ollama_base_url,
    model_name: str = settings.ollama_vision_model,
):
    """Launch or attach to Chrome via CDP and test browser-use vision agent."""
    print_banner("Testing browser-use CDP Attachment & Vision Agent")

    # 1. Ensure Chrome is running
    print(f"[INFO] Ensuring Chrome is running on port {settings.debugger_port}...")
    browser_manager.ensure_chrome_running(headless=settings.chrome_headless)

    from browser_use import Agent, Browser
    from browser_use.llm.ollama.chat import ChatOllama

    cdp_url = f"http://{settings.debugger_address}"
    print(f"[INFO] Initializing ChatOllama with model '{model_name}' at '{base_url}'...")
    llm = ChatOllama(
        host=base_url,
        model=model_name,
    )

    print(f"[INFO] Attaching browser-use to Chrome CDP at {cdp_url}...")
    browser = Browser(cdp_url=cdp_url)

    task_prompt = (
        f"Navigate to {target_url}. "
        "Examine the page for the Cloudflare Turnstile or 'Verify you are human' security challenge. "
        "Click the verification checkbox to solve the challenge. "
        "After clicking the checkbox, click the 'Check' button to submit the verification. "
        "Once verified or if the page shows 'Success' or token, finish the task."
    )

    print(f"[INFO] Starting Agent with task: {task_prompt}")
    agent = Agent(
        task=task_prompt,
        llm=llm,
        browser=browser,
        use_vision=True,
        max_actions_per_step=2,
    )

    try:
        history = await agent.run(max_steps=5)
        print("\n[SUCCESS] browser-use execution completed!")
        print(f"[INFO] Final agent result: {history.final_result() if hasattr(history, 'final_result') else 'Completed'}")
    except Exception as e:
        print(f"\n[ERROR] browser-use execution encountered an error: {e}")


async def main():
    print_banner("Ollama Vision + browser-use CAPTCHA Solver Diagnostic")
    print(f"  Configured Ollama URL:   {settings.ollama_base_url}")
    print(f"  Configured Vision Model: {settings.ollama_vision_model}")
    print(f"  Chrome Debugging Port:   {settings.debugger_port}")
    print(f"  Headless Mode:           {settings.chrome_headless}")
    print("=" * 65)

    # Parse CLI overrides
    base_url = settings.ollama_base_url
    model_name = settings.ollama_vision_model
    check_only = "--check-only" in sys.argv
    test_page = "https://2captcha.com/demo/cloudflare-turnstile"

    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--endpoint" and i + 1 < len(sys.argv[1:]):
            base_url = sys.argv[1:][i + 1]
        elif arg.startswith("--endpoint="):
            base_url = arg.split("=", 1)[1]
        elif arg == "--model" and i + 1 < len(sys.argv[1:]):
            model_name = sys.argv[1:][i + 1]
        elif arg.startswith("--model="):
            model_name = arg.split("=", 1)[1]
        elif arg == "--test-page" and i + 1 < len(sys.argv[1:]):
            test_page = sys.argv[1:][i + 1]

    # Step 1: Probe Ollama
    ollama_ok = check_ollama_endpoint(base_url, model_name)

    if check_only:
        print("\n[INFO] '--check-only' specified. Exiting diagnostic.")
        return

    if not ollama_ok:
        print("\n[NOTICE] Ollama server is currently offline or unreachable.")
        print("         Please ensure your Ollama endpoint is running before executing live vision solving.")
        print("         Example: ollama run gemma4:31b-cloud (or ollama serve)")
        return

    # Step 2: Test live browser-use
    await test_browser_use_cdp(target_url=test_page, base_url=base_url, model_name=model_name)


if __name__ == "__main__":
    asyncio.run(main())
