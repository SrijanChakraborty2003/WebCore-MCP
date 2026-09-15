# Browser-Based Multi-Provider MCP Server

> A production-grade, local Model Context Protocol (MCP) server that connects AI clients (Claude Desktop, Cursor, Antigravity IDE, etc.) directly to live web instances of **Google Search**, **Google Gemini**, **ChatGPT**, **Claude**, and **DeepSeek** via an automated Chrome instance. **No paid API keys required.**

---

## 📑 Table of Contents
1. [Project Overview](#-project-overview)
2. [High-Level Architecture](#-high-level-architecture)
3. [End-to-End Execution Flow](#-end-to-end-execution-flow)
4. [Autonomous Vision CAPTCHA Solver](#-autonomous-vision-captcha-solver)
5. [Provider Implementation Matrix](#-provider-implementation-matrix)
6. [First-Time Setup Guide](#-first-time-setup-guide)
7. [Running the MCP Server](#-running-the-mcp-server)
8. [MCP Client Configuration](#-mcp-client-configuration)
9. [Available MCP Tools Reference](#-available-mcp-tools-reference)
10. [CLI Testing Suite](#-cli-testing-suite)
11. [Project Directory Structure](#-project-directory-structure)
12. [Troubleshooting & FAQ](#-troubleshooting--faq)

---

## 🌟 Project Overview

API subscriptions for multiple AI providers (OpenAI, Anthropic, Google Cloud, DeepSeek) are expensive and carry strict rate limits. Meanwhile, individual users typically already have web subscriptions (or free accounts) on these platforms.

This project bridges that gap by running a **FastMCP server** that drives an authenticated Google Chrome browser over the **Chrome DevTools Protocol (CDP)** and **Selenium WebDriver**:
- **Zero API Costs**: Uses your existing browser sessions and cookies stored in a persistent profile.
- **Unified Interface**: Exposes 11 standard MCP tools covering conversational chat, real-time web search (with AI overviews and citations), and live image generation.
- **Autonomous CAPTCHA Bypassing**: Integrates a two-tier challenge solver powered by `browser-use` and local/cloud **Ollama Vision (`gemma4:31b-cloud`)** to solve Cloudflare Turnstile verification challenges automatically without paid third-party solver extensions.
- **Strict Tab & Session Isolation**: Emulates fresh chats on every query, preventing context contamination and history pollution.

---

## 🏗️ High-Level Architecture

```
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │                       AI Clients & MCP Consumers                            │
 │          (Claude Desktop, Cursor, Antigravity IDE, CLI / test.py)           │
 └──────────────────────────────────────┬──────────────────────────────────────┘
                                        │ (SSE on :8000 or stdio)
 ┌──────────────────────────────────────▼──────────────────────────────────────┐
 │                      FastMCP Server (server.py)                             │
 │  - 11 Registered Tools                                                      │
 │  - Asynchronous Reentrancy Lock (`browser_lock`)                            │
 │  - Error Normalization & Structured JSON Output Formatting                  │
 └──────────────────────────────────────┬──────────────────────────────────────┘
                                        │ Python WebDriver + CDP
 ┌──────────────────────────────────────▼──────────────────────────────────────┐
 │               Browser Manager & Infrastructure (app/browser.py)             │
 │  - Chrome Auto-Launch on Port 9222 (Headless or Headed)                     │
 │  - Persistent Profile: C:\mcp-browser-profile                               │
 │  - Prototype Stealth Injections (Overrides `navigator.webdriver`)           │
 │  - SSL Intercept Bypass (`--ignore-certificate-errors`)                     │
 └──────────────────────────────────────┬──────────────────────────────────────┘
                                        │
           ┌────────────────────────────┼────────────────────────────┐
           ▼                            ▼                            ▼
 ┌───────────────────┐        ┌───────────────────┐        ┌───────────────────┐
 │ Provider Engines  │        │ Direct Web Search │        │  CAPTCHA Defense  │
 │ (app/providers/)  │        │ (google.py)       │        │ (captcha_solver)  │
 ├───────────────────┤        ├───────────────────┤        ├───────────────────┤
 │ • gemini.py       │        │ • Organic Scraper │        │ • Fast DOM Click  │
 │ • chatgpt.py      │        │ • AI Overview     │        │ • browser-use +   │
 │ • claude.py       │        │ • Query Citations │        │   Ollama Vision   │
 │ • deepseek.py     │        │                   │        │   (gemma4:31b)    │
 └───────────────────┘        └───────────────────┘        └───────────────────┘
```

---

## 🔄 End-to-End Execution Flow

Every request dispatched to the server follows a strict, deterministic sequence:

```
[1. Request Arrives]  -->  MCP Tool invoked (e.g. ask_chatgpt, ask_claude)
         │
[2. Concurrency Lock] -->  Acquire `browser_lock` (ensures single-tab execution safety)
         │
[3. Browser Health]   -->  Ensure Chrome is alive on 127.0.0.1:9222; auto-start if down
         │
[4. Tab Isolation]    -->  Provider activates or opens its designated tab (e.g. chatgpt.com)
         │
[5. Anti-Bot Gate]    -->  `VisionCaptchaSolver.is_captcha_present()` runs:
         │                 ├── Not Present: Continue instantly (< 1ms latency)
         │                 └── Present:
         │                      ├── Tier 1: Instant JavaScript DOM click (1-2s)
         │                      └── Tier 2: Escalate to browser-use + Ollama Vision
         │
[6. DOM Input]        -->  Inject prompt using provider-specific rich-text strategy:
         │                 • Gemini: Quill `document.execCommand('insertText')`
         │                 • ChatGPT: TipTap contenteditable innerHTML dispatch
         │                 • Claude: ProseMirror event synthesizer
         │                 • DeepSeek: Native JavaScript HTMLTextAreaElement prototype
         │
[7. Generation Wait]  -->  Poll generation indicator (stop button, pulse animation, or shimmer)
         │
[8. Extraction]       -->  Extract sanitized Markdown text, search citations, or full-res PNG
         │
[9. Return & Release] -->  Format standardized JSON envelope, release `browser_lock`
```

---

## 🛡️ Autonomous Vision CAPTCHA Solver

Security verification challenges (such as Cloudflare Turnstile's *"Verify you are human"*) can block automated browsers. Instead of relying on paid, third-party browser extensions (NopeCHA, Buster, 2Captcha), this server incorporates an **autonomous vision solver**:

```
                  Challenge Detected on Page
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
       [Tier 1: Fast DOM]            [Challenge Persists?]
   Direct click on Turnstile iframe           │ Yes
   or verify button via JavaScript            ▼
              │                     [Tier 2: Vision Escalation]
          Cleared?               Attach browser-use via CDP
         /        \              Snapshot DOM & Viewport
      Yes          No            Pass screenshot to Ollama (gemma4:31b)
      │             │                         │
   Resume       Escalate                      ▼
                           Model spots checkbox -> outputs click action
                                              │
                                              ▼
                           Action Schema Normalizer:
                           {"click": 35} -> {"click": {"index": 35}}
                                              │
                                              ▼
                           browser-use clicks checkbox -> Verifies "Success"
                                              │
                                              ▼
                           Challenge Cleared -> Control returns to Provider
```

### Why Normalization Matters
Local and lightweight vision models (like `gemma4:31b-cloud`) often output shorthand actions (e.g., `{"click": 35}`) rather than the deeply nested Pydantic schemas required by `browser-use`. The integration in `browser_use.llm.ollama.chat` includes an automatic action schema normalizer (`_normalize_ollama_actions`) that translates shorthand instructions into valid action models on the fly.

---

## 🧩 Provider Implementation Matrix

| Provider | Base URL | Input Automation Strategy | Streaming & Completion Detection | Special Capabilities |
|---|---|---|---|---|
| **Google Gemini** | `gemini.google.com/app` | Quill editor via `execCommand('insertText')` | Monitors `.stop-button` and `mat-icon[fonticon='stop']` | Imagen diffusion image generation, high-res HTML5 Canvas extraction |
| **ChatGPT** | `chatgpt.com` | TipTap contenteditable composer with synthetic input events | Detects stop button presence (avoids false-positive dormant pulse classes) | Native Web Search (`search_chatgpt`), DALL-E 3 image generation |
| **Claude** | `claude.ai/new` | ProseMirror input area with session isolation | Observes streaming cursor and response container mutations | Strict `/new` chat isolation, Claude Sonnet formatting |
| **DeepSeek** | `chat.deepseek.com` | Native `HTMLTextAreaElement.prototype` value setter | Detects completion of reasoning blocks and stop button clearance | DeepThink reasoning mode, DeepSeek Web Search |
| **Google Search** | `google.com` | Direct URL navigation (`/search?q=...`) | Fast page load and DOM readiness detection | Scrapes organic search results (clean URLs, snippets) + Google AI Overviews |

---

## 🛠️ First-Time Setup Guide

### 1. Install System Prerequisites
- **Python 3.10+** (Anaconda or standard virtualenv)
- **Google Chrome** installed in standard Windows location
- **Ollama** installed and running (for autonomous CAPTCHA solving):
  ```cmd
  ollama serve
  ollama pull gemma4:31b-cloud
  ```

### 2. Install Python Dependencies
```cmd
cd BrowserApi
pip install -r requirements.txt
playwright install chromium
```

### 3. One-Time Login (Profile Initialization)
To allow Chrome to save your session cookies permanently:
1. Run the helper script:
   ```cmd
   start_chrome.bat
   ```
2. A visible Chrome window will open using the profile directory at `C:\mcp-browser-profile`.
3. Log in to each provider:
   - [Gemini](https://gemini.google.com/app)
   - [ChatGPT](https://chatgpt.com/)
   - [Claude](https://claude.ai/)
   - [DeepSeek](https://chat.deepseek.com/)
4. Once you are logged in and can see the chat interface on each, close the Chrome window.

---

## 🚀 Running the MCP Server

### Mode 1: Server-Sent Events (SSE) — Default
Runs a persistent HTTP/SSE server accessible by network or multi-client setups:
```cmd
python server.py
```
- Starts the SSE server on **`http://127.0.0.1:8000/sse`**.
- Automatically launches Chrome in the background on port `9222`.

### Mode 2: Standard I/O (Stdio) — For AI Desktop Clients
Runs directly via process stdin/stdout:
```cmd
python server.py --stdio
```

---

## 💻 MCP Client Configuration

### Claude Desktop (`claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "browser-agent": {
      "command": "python",
      "args": [
        "C:\\Users\\CT_USER\\Desktop\\BrowserApi\\server.py",
        "--stdio"
      ]
    }
  }
}
```

### Cursor / Antigravity IDE
Add the server under **MCP Settings**:
- **Name**: `browser-agent`
- **Transport**: `stdio`
- **Command**: `python C:\Users\CT_USER\Desktop\BrowserApi\server.py --stdio`

*(Alternatively, connect via SSE to `http://127.0.0.1:8000/sse`)*

---

## 🧰 Available MCP Tools Reference

| Tool | Parameters | Description |
|---|---|---|
| **`health_check`** | *None* | Returns the real-time health of the server, Chrome port `9222`, login status for all 4 providers, and Ollama status. |
| **`search_google`** | `query: str`<br>`num_results: int = 10`<br>`timeout: int = 60` | Direct Google Search; returns organic search results (titles, links, snippets) and Google AI Overview synthesis. |
| **`search_web`** | `query: str`<br>`provider: str = "google"`<br>`timeout: int = 120` | Unified web search router. Options for `provider`: `'google'`, `'chatgpt'`, `'deepseek'`, `'gemini'`. |
| **`ask_gemini`** | `prompt: str`<br>`timeout: int = 120` | Queries Google Gemini in a clean session. Automatically detects image generation requests. |
| **`generate_image_gemini`** | `prompt: str`<br>`output_name: str = ""` | Generates an image using Gemini Imagen diffusion and downloads high-res PNG to `data/outputs/`. |
| **`ask_chatgpt`** | `prompt: str`<br>`timeout: int = 120`<br>`web_search: bool = False` | Queries ChatGPT Free / Plus in an isolated session with optional web search synthesis. |
| **`search_chatgpt`** | `query: str`<br>`timeout: int = 120` | Searches the web using ChatGPT's built-in search engine; returns answer with citations. |
| **`generate_image_chatgpt`** | `prompt: str`<br>`output_name: str = ""` | Generates an image via ChatGPT DALL-E 3 and saves it to `data/outputs/`. |
| **`ask_claude`** | `prompt: str`<br>`timeout: int = 120` | Queries Anthropic Claude in a fresh `/new` chat session. |
| **`ask_deepseek`** | `prompt: str`<br>`timeout: int = 120`<br>`web_search: bool = False`<br>`deepthink: bool = False` | Queries DeepSeek with optional live Web Search or DeepThink reasoning mode. |
| **`search_deepseek`** | `query: str`<br>`timeout: int = 120` | Searches the live web using DeepSeek's search pipeline. |

---

## 🧪 CLI Testing Suite

The project includes test and diagnostic scripts:

### 1. Provider & Search Tests (`test.py`)
```cmd
# Health check across all providers
python test.py

# Chat with individual providers
python test.py --provider=gemini "Explain quantum entanglement in 2 sentences"
python test.py --provider=chatgpt "Summarize the history of space flight"
python test.py --provider=claude "Write a haiku about autumn"
python test.py --provider=deepseek "Write an async queue in Python"

# Web search tests
python test.py --search "Latest Mars rover discoveries"
python test.py --provider=deepseek --search "Quantum computing breakthroughs"

# Image generation tests
python test.py --image "A photorealistic red fox in a snowy forest"
python test.py --provider=chatgpt --image "A futuristic cyberpunk city at dusk"
```

### 2. Autonomous CAPTCHA Solver Diagnostic (`test_vision_solver.py`)
```cmd
# Verify Ollama endpoint connectivity and model tags
python test_vision_solver.py --check-only

# Run live end-to-end CAPTCHA test against Cloudflare Turnstile demo
python test_vision_solver.py
```

---

## 📁 Project Directory Structure

```text
BrowserApi/
├── app/
│   ├── __init__.py
│   ├── browser.py               # Chrome lifecycle manager, Selenium attachment, CDP stealth
│   ├── captcha_solver.py        # 2-Tier Vision CAPTCHA solver (Fast DOM + browser-use Ollama)
│   ├── config.py                # Environment variables, timeouts, ports, model names
│   ├── parsers.py               # Standardized JSON response envelope helpers
│   └── providers/
│       ├── __init__.py          # Provider factory and registry
│       ├── base.py              # Base abstract BrowserProvider class
│       ├── chatgpt.py           # ChatGPT automation (TipTap, Search, DALL-E 3)
│       ├── claude.py            # Claude automation (ProseMirror, Turnstile defense)
│       ├── deepseek.py          # DeepSeek automation (DOM prototype, DeepThink, Search)
│       ├── gemini.py            # Google Gemini automation (Quill, Imagen diffusion)
│       └── google.py            # Direct Google Search & AI Overview scraper
├── data/
│   ├── logs/                    # Runtime application logs (browser_mcp.log)
│   ├── outputs/                 # Generated full-resolution images (.png)
│   └── screenshots/             # Diagnostic screenshots (ignored in git)
├── server.py                    # Main FastMCP server (exposes 11 tools via SSE / stdio)
├── start_chrome.bat             # Helper script to launch Chrome headed for one-time login
├── test.py                      # Multi-provider CLI verification client
├── test_vision_solver.py        # Standalone vision CAPTCHA solver test script
├── requirements.txt             # Python dependencies
├── .gitignore                   # Ignores temp caches, profiles, logs, and generated images
└── README.md                    # Comprehensive documentation and flow definition
```

---

## 🔧 Troubleshooting & FAQ

#### Q: How does Chrome stay logged in?
Chrome uses the persistent directory `C:\mcp-browser-profile`. All cookies, localStorage, and authentication tokens persist across reboots.

#### Q: A provider logged me out. What do I do?
1. Close any running `python server.py`.
2. Run `start_chrome.bat`.
3. Log in again in the Chrome window that opens.
4. Close Chrome and restart `python server.py`.

#### Q: Can I run Chrome in visible (headed) mode for debugging?
Yes. In [app/config.py](file:///c:/Users/CT_USER/Desktop/BrowserApi/app/config.py), set:
```python
chrome_headless: bool = False
```
Chrome will run in a visible window so you can watch actions occur in real time.

#### Q: Does CAPTCHA solving slow down normal requests?
No. `is_captcha_present()` runs lightweight DOM checks that execute in under a millisecond. The vision agent is only activated on-demand when a challenge is verified to be blocking the page.
