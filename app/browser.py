import asyncio
import logging
import os
import socket
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import WebDriverException

from app.config import settings

# Configure logging
log_file = settings.logs_dir / "browser_mcp.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(str(log_file), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("browser_mcp")

# Global async lock to ensure sequential browser access
browser_lock = asyncio.Lock()


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/133.0.0.0 Safari/537.36"
)


class BrowserManager:
    _instance: Optional["BrowserManager"] = None
    _driver: Optional[webdriver.Chrome] = None

    def __new__(cls) -> "BrowserManager":
        if cls._instance is None:
            cls._instance = super(BrowserManager, cls).__new__(cls)
        return cls._instance

    @staticmethod
    def is_port_open(host: str = "127.0.0.1", port: int = 9222, timeout: float = 1.0) -> bool:
        """Check if the remote debugging port is open."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            return sock.connect_ex((host, port)) == 0

    @staticmethod
    def check_chrome_status() -> dict:
        """Query Chrome's remote debugging HTTP endpoint for version and status."""
        url = f"http://{settings.debugger_address}/json/version"
        try:
            resp = requests.get(url, timeout=2.0)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "running": True,
                    "browser": data.get("Browser", "Unknown Chrome"),
                    "webSocketDebuggerUrl": data.get("webSocketDebuggerUrl", ""),
                }
        except Exception as e:
            logger.debug(f"Chrome endpoint check failed: {e}")
        return {"running": False, "error": f"Cannot connect to Chrome at {settings.debugger_address}"}

    @staticmethod
    def find_chrome_executable() -> Optional[str]:
        """Look for Chrome executable in standard Windows paths."""
        candidates = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ]
        for path in candidates:
            if os.path.isfile(path):
                return path
        return None

    def ensure_chrome_running(self, headless: Optional[bool] = None, max_wait_seconds: int = 8) -> bool:
        """
        Check if Chrome is running on debugging port.
        If not, attempt to launch Chrome automatically (headlessly by default).
        """
        if self.is_port_open(settings.debugger_host, settings.debugger_port):
            logger.info(f"Chrome is already running on {settings.debugger_address}.")
            return True

        chrome_exe = self.find_chrome_executable()
        if not chrome_exe:
            logger.warning("Could not find chrome.exe to auto-launch. Please run start_chrome.bat.")
            return False

        profile_dir = Path(settings.chrome_profile_dir)
        profile_dir.mkdir(parents=True, exist_ok=True)

        is_headless = settings.chrome_headless if headless is None else headless
        mode_str = "headlessly" if is_headless else "in headed mode"
        logger.info(f"Auto-launching Chrome {mode_str} on port {settings.debugger_port}...")

        cmd = [
            chrome_exe,
            f"--remote-debugging-port={settings.debugger_port}",
            f"--user-data-dir={settings.chrome_profile_dir}",
            "--disable-blink-features=AutomationControlled",
        ]

        if is_headless:
            cmd.extend([
                "--headless=new",
                "--disable-gpu",
                f"--user-agent={DEFAULT_USER_AGENT}",
                "--window-size=1920,1080",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-notifications",
                "--disable-popup-blocking",
            ])

        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            # Wait for port to open
            end_time = time.time() + max_wait_seconds
            while time.time() < end_time:
                if self.is_port_open(settings.debugger_host, settings.debugger_port):
                    logger.info(f"Chrome auto-launched successfully on port {settings.debugger_port} ({mode_str}).")
                    time.sleep(1.5)
                    return True
                time.sleep(0.5)
        except Exception as e:
            logger.error(f"Failed to auto-launch Chrome: {e}")
        return False

    def get_driver(self) -> webdriver.Chrome:
        """
        Get or initialize the Selenium Chrome driver attached to the existing Chrome session.
        """
        # Test existing driver connection
        if self._driver is not None:
            try:
                # Simple ping by accessing current_window_handle
                _ = self._driver.current_window_handle
                return self._driver
            except Exception as e:
                logger.warning(f"Existing driver connection lost ({e}), attempting to re-attach...")
                try:
                    self._driver.quit()
                except Exception:
                    pass
                self._driver = None

        # Check if Chrome is running; if not, attempt auto-launch
        if not self.is_port_open(settings.debugger_host, settings.debugger_port):
            self.ensure_chrome_running()

        # Verify Chrome is running before connecting
        status = self.check_chrome_status()
        if not status["running"]:
            raise ConnectionError(
                f"Chrome is not running on {settings.debugger_address}. "
                "Please run start_chrome.bat or launch Chrome with --remote-debugging-port=9222."
            )

        logger.info(f"Attaching Selenium to existing Chrome at {settings.debugger_address}...")
        options = Options()
        options.add_experimental_option("debuggerAddress", settings.debugger_address)
        options.add_argument("--disable-gpu")
        
        try:
            self._driver = webdriver.Chrome(options=options)
            self._driver.set_page_load_timeout(settings.page_load_timeout)

            # Apply CDP overrides to strip Headless signals and mask automation
            try:
                self._driver.execute_cdp_cmd(
                    "Network.setUserAgentOverride",
                    {"userAgent": DEFAULT_USER_AGENT}
                )
                self._driver.execute_cdp_cmd(
                    "Page.addScriptToEvaluateOnNewDocument",
                    {
                        "source": """
                            Object.defineProperty(navigator, 'webdriver', {
                                get: () => undefined
                            });
                        """
                    }
                )
            except Exception as cdp_err:
                logger.debug(f"CDP stealth injection note: {cdp_err}")

            logger.info("Successfully attached to Chrome.")
            return self._driver
        except WebDriverException as e:
            logger.error(f"Failed to attach to Chrome: {e}")
            raise ConnectionError(f"Failed to attach Selenium to Chrome at {settings.debugger_address}: {e}")

    def take_screenshot(self, name_prefix: str = "error") -> Optional[str]:
        """Capture screenshot of current browser window and save to screenshots directory."""
        if not self._driver:
            return None
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
            filename = f"{name_prefix}_{timestamp}.png"
            path = settings.screenshots_dir / filename
            self._driver.save_screenshot(str(path))
            logger.info(f"Screenshot saved to: {path}")
            return str(path)
        except Exception as e:
            logger.error(f"Failed to take screenshot: {e}")
            return None


browser_manager = BrowserManager()
