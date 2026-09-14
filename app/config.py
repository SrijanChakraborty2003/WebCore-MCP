import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
OUTPUTS_DIR = DATA_DIR / "outputs"
SCREENSHOTS_DIR = DATA_DIR / "screenshots"
LOGS_DIR = DATA_DIR / "logs"

# Ensure directories exist
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server Settings
    server_name: str = "Browser-Agent-Server"
    server_version: str = "0.1.0"
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8000
    mcp_transport: str = "sse"

    # Browser Remote Debugging Settings
    debugger_host: str = "127.0.0.1"
    debugger_port: int = 9222
    chrome_profile_dir: str = "C:\\mcp-browser-profile"
    chrome_headless: bool = True

    @property
    def debugger_address(self) -> str:
        return f"{self.debugger_host}:{self.debugger_port}"

    @property
    def sse_url(self) -> str:
        return f"http://{self.mcp_host}:{self.mcp_port}/sse"

    # Provider URLs
    gemini_url: str = "https://gemini.google.com/app"
    chatgpt_url: str = "https://chatgpt.com/"
    claude_url: str = "https://claude.ai/new"
    deepseek_url: str = "https://chat.deepseek.com/"

    # Timeouts (in seconds)
    default_timeout: int = 120
    page_load_timeout: int = 30
    element_timeout: int = 20

    # Paths
    base_dir: Path = BASE_DIR
    data_dir: Path = DATA_DIR
    outputs_dir: Path = OUTPUTS_DIR
    screenshots_dir: Path = SCREENSHOTS_DIR
    logs_dir: Path = LOGS_DIR


settings = Settings()
