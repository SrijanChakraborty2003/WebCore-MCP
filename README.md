# Browser-Based Multi-Provider MCP Server (Chrome + Selenium + FastMCP)

A local FastMCP server that controls an authenticated Google Chrome browser via remote debugging (`127.0.0.1:9222`). It provides seamless Model Context Protocol (MCP) tools for **Google Search**, **Google Gemini**, **ChatGPT (with Web Search & DALL-E 3)**, **Claude**, and **DeepSeek (with Web Search & DeepThink)** without requiring paid API keys for each provider.

---

## 🧠 How It Works

```
   ┌─────────────────────────────────────────────────────────┐
   │            MCP Client / AI Agent / test.py              │
   └────────────────────────────┬────────────────────────────┘
                                │ (SSE on :8000 or stdio)
   ┌────────────────────────────▼────────────────────────────┐
   │              FastMCP Server (server.py)                 │
   │  - 11 Exposed Tools                                     │
   │  - Async Concurrency Lock (Sequential Tab Safety)       │
   └────────────────────────────┬────────────────────────────┘
                                │ Selenium WebDriver + CDP
   ┌────────────────────────────▼────────────────────────────┐
   │         Google Chrome (Headless Auto-Launch)            │
   │  - Remote Debugging: 127.0.0.1:9222                     │
   │  - Persistent Profile: C:\mcp-browser-profile           │
   │  - Stealth Flags (No 'HeadlessChrome' User-Agent)       │
   │  - Auto-CAPTCHA Solver Extension (NopeCHA)              │
   └──────┬──────────────┬──────────────┬─────────────┬──────┤
          │              │              │             │      │
          ▼              ▼              ▼             ▼      ▼
     Google Search  Gemini Web     ChatGPT Web   Claude Web  DeepSeek Web
```

1. **Auto-Launched Headless Browser**: When you start `server.py`, it automatically launches Chrome in the background with `--headless=new`, a realistic desktop User-Agent, and `--disable-blink-features=AutomationControlled`. You don't need to manually start Chrome!
2. **Session & Cookie Persistence**: Chrome uses a dedicated, persistent user profile directory (`C:\mcp-browser-profile`). Once you log into your accounts, you stay logged in indefinitely.
3. **No Context Contamination**: Each request opens a clean chat session (`new_chat()`) to prevent credit bleed and context cross-talk.
4. **Cloudflare & Anti-Bot Defense**: Chrome DevTools Protocol (CDP) overrides mask `navigator.webdriver`. The installed **NopeCHA** extension automatically handles Cloudflare Turnstile challenges in the background.
5. **Direct Image Pipeline**: Image generation requests (Gemini Imagen diffusion or ChatGPT DALL-E 3) track render progress and extract full-resolution PNGs directly into `data/outputs/`.

---

## 🛠️ First-Time Setup (One-Time Only)

Before running the server headlessly, you need to log into your accounts once in a visible browser window and install the CAPTCHA-solving extension.

### Step 1: Install Python Dependencies
Open your terminal (in your Anaconda or virtual environment):
```cmd
pip install -r requirements.txt
```

### Step 2: Open Chrome in Headed Mode
Run the provided batch file:
```cmd
start_chrome.bat
```
*(This launches Chrome with the persistent profile at `C:\mcp-browser-profile` and opens port `9222`).*

### Step 3: Log In to All 4 Services
In the Chrome browser window that just opened, navigate to and log in to each service:
- **Google Gemini**: [https://gemini.google.com/app](https://gemini.google.com/app)
- **ChatGPT**: [https://chatgpt.com/](https://chatgpt.com/)
- **Claude**: [https://claude.ai/](https://claude.ai/)
- **DeepSeek**: [https://chat.deepseek.com/](https://chat.deepseek.com/)

Make sure you can see the main chat interface on each website and that "Remember Me" / persistent login is enabled.

### Step 4: Install and Configure NopeCHA (Auto-CAPTCHA Solver)
To solve Cloudflare Turnstile and security challenges automatically:
1. In the same Chrome window, visit the Chrome Web Store:
   [NopeCHA: CAPTCHA Solver Extension](https://chromewebstore.google.com/detail/nopecha-captcha-solver/dknlfmjaanfblgfdefebhijalfmhmmjjo)
2. Click **Add to Chrome**.
3. Once installed, click the NopeCHA puzzle icon in your browser toolbar:
   - Add your NopeCHA API key (free tiers are available at [nopecha.com](https://nopecha.com)).
   - Ensure Cloudflare Turnstile / challenge auto-solving is toggled **ON**.
4. *(Optional)*: You can also install [Buster: Captcha Solver for Humans](https://chromewebstore.google.com/detail/buster-captcha-solver-for/mpbjkejclgfgadiemmefgebjfooflfhl) as an extra fallback.

### Step 5: Close the Chrome Window
Close the Chrome window completely. All your logins, cookies, and installed extensions are now permanently saved in `C:\mcp-browser-profile`.

---

## 🚀 Running the MCP Server

### Option A: Server-Sent Events (SSE) Mode (Default)
Run:
```cmd
python server.py
```
- Chrome is automatically launched **headlessly** on port `9222`.
- FastMCP exposes the SSE server at **`http://127.0.0.1:8000/sse`**.

### Option B: Stdio Mode (For Desktop AI Clients)
To integrate directly with Claude Desktop, Cursor, or Antigravity IDE:
```cmd
python server.py --stdio
```

#### Claude Desktop Configuration (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "browser-agent": {
      "command": "python",
      "args": ["C:\\Users\\CT_USER\\Desktop\\BrowserApi\\server.py", "--stdio"]
    }
  }
}
```

---

## 🧪 Testing with `test.py`

You can test any provider, web search, or image generation directly from the command line using `test.py`:

### 1. Check Server & Provider Health
Verify that Chrome is running and all 4 providers are authenticated:
```cmd
python test.py
```

### 2. Chat with Any Provider
```cmd
# Google Gemini
python test.py --provider=gemini "What is the speed of light?"

# OpenAI ChatGPT
python test.py --provider=chatgpt "Explain quantum computing in simple terms."

# Anthropic Claude
python test.py --provider=claude "Write a haiku about the moon."

# DeepSeek
python test.py --provider=deepseek "Write a Python binary search function."
```

### 3. Live Web Search (Google, ChatGPT & DeepSeek)
Search the live web with synthesized responses and source citations:
```cmd
# Direct Google Search (ultra-fast, extracted organic results + AI Overview):
python test.py --google "Latest stock market trend and AI news"

# Search via search_web (defaults to Google Search):
python test.py --search "NVIDIA stock performance today"

# Search via ChatGPT Web Search:
python test.py --provider=chatgpt --search "What is today's date and current market trend?"

# Search via DeepSeek Web Search:
python test.py --provider=deepseek --search "Artificial intelligence breakthroughs"
```

### 4. Image Generation (Gemini & ChatGPT)
Images are generated, downloaded, and saved to `data/outputs/` as full-resolution PNG files:
```cmd
# Generate image via Google Gemini Imagen diffusion:
python test.py --image "A futuristic cyberpunk sports car speeding through a glowing neon city"

# Generate image via ChatGPT DALL-E 3:
python test.py --provider=chatgpt --image "A vintage steam locomotive crossing a bridge in a snowstorm"
```

---

## 🧰 Available MCP Tools Reference

| Tool Name | Parameters | Description |
| :--- | :--- | :--- |
| `health_check()` | None | Checks server status, Chrome port 9222, and login status across Gemini, ChatGPT, Claude, DeepSeek, and Google. |
| `search_google` | `query: str`, `num_results: int = 10`, `timeout: int = 60` | Direct Google Web Search; extracts organic results (titles, links, snippets) and AI Overviews. |
| `search_web` | `query: str`, `provider: str = "google"`, `timeout: int = 120` | Unified web search router (`provider`: `'google'` [default], `'chatgpt'`, `'deepseek'`, or `'gemini'`). |
| `ask_gemini` | `prompt: str`, `timeout: int = 120` | Starts a new chat session with Google Gemini. Automatically detects image requests. |
| `generate_image_gemini` | `prompt: str`, `output_name: str = ""`, `timeout: int = 180` | Generates an image using Gemini Imagen diffusion and downloads high-res PNG to `data/outputs/`. |
| `ask_chatgpt` | `prompt: str`, `timeout: int = 120`, `web_search: bool = False` | Queries ChatGPT (`gpt-5-6`) in an isolated session with optional web search toggle. |
| `search_chatgpt` | `query: str`, `timeout: int = 120` | Searches the web using ChatGPT's built-in search engine; returns synthesized answer with citations. |
| `generate_image_chatgpt` | `prompt: str`, `output_name: str = ""`, `timeout: int = 180` | Generates an image via ChatGPT DALL-E 3 and saves it to `data/outputs/`. |
| `ask_claude` | `prompt: str`, `timeout: int = 120` | Queries Claude (Anthropic) in a fresh session with TipTap/ProseMirror automation. |
| `ask_deepseek` | `prompt: str`, `timeout: int = 120`, `web_search: bool = False`, `deepthink: bool = False` | Queries DeepSeek with optional Web Search or DeepThink reasoning mode. |
| `search_deepseek` | `query: str`, `timeout: int = 120` | Searches the web using DeepSeek Search with source synthesis. |

---

## 📁 Directory Structure

```text
BrowserApi/
├── app/
│   ├── __init__.py
│   ├── config.py                 # Configuration (ports, URLs, timeouts, headless flag)
│   ├── browser.py                # Headless Chrome auto-launcher, Selenium manager, CDP stealth hooks
│   ├── parsers.py                # Structured response schemas (text, image, error)
│   └── providers/
│       ├── __init__.py
│       ├── base.py               # Abstract BrowserProvider base class
│       ├── google.py             # Direct Google Search automation & AI Overview scraper
│       ├── gemini.py             # Google Gemini automation (Quill execCommand & Imagen extraction)
│       ├── chatgpt.py            # ChatGPT automation (TipTap contenteditable, Search, DALL-E 3)
│       ├── claude.py             # Claude automation (ProseMirror input & Cloudflare handling)
│       └── deepseek.py           # DeepSeek automation (Native DOM prototype, Search, DeepThink)
├── data/
│   ├── outputs/                  # Downloaded generated images (.png)
│   ├── screenshots/              # Error & diagnostic screenshots (.png)
│   └── logs/                     # Execution logs (browser_mcp.log)
├── server.py                     # FastMCP Server (SSE on port 8000, or --stdio)
├── test.py                       # Test client for all 11 tools and 5 providers
├── start_chrome.bat              # Batch script to launch Chrome in visible mode for initial setup
├── requirements.txt              # Project dependencies
├── .gitignore
└── README.md
```

---

## 🔧 Troubleshooting & Tips

- **Session Expired / Logged Out**:
  If a service logs you out, simply run `start_chrome.bat`, log in again in the Chrome window, close it, and restart `python server.py`.
- **Cloudflare Challenges**:
  The server masks automation flags (`--disable-blink-features=AutomationControlled` and custom desktop User-Agent). If Cloudflare presents a challenge, the server auto-clicks the "Verify you are human" button and allows the installed NopeCHA extension to solve it.
- **Port 9222 Already in Use**:
  If a previous Chrome instance is lingering on port 9222:
  ```cmd
  taskkill /F /IM chrome.exe
  ```
- **Custom Timeouts**:
  Complex reasoning (DeepThink) or diffusion image generation can take up to 60-90 seconds. You can pass custom timeouts in tool calls:
  `ask_deepseek(prompt="...", deepthink=True, timeout=180)`.
