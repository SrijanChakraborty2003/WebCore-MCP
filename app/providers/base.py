import time
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait

from app.browser import browser_manager, logger
from app.config import settings
from app.parsers import format_error


class BrowserProvider(ABC):
    """
    Abstract base class for browser-based AI model providers (Gemini, ChatGPT, Claude).
    """
    provider_name: str = "base"
    base_url: str = ""

    def __init__(self):
        self.browser_manager = browser_manager

    @property
    def driver(self) -> webdriver.Chrome:
        """Access the current Selenium Chrome driver instance."""
        return self.browser_manager.get_driver()

    @abstractmethod
    def new_chat(self) -> None:
        """Navigate to a clean chat session to prevent history and credit bleeding."""
        pass

    @abstractmethod
    def ask(self, prompt: str, timeout: int = 120) -> dict:
        """Send a prompt to the provider and return the structured response."""
        pass

    def generate_image(self, prompt: str, output_name: str = "image", timeout: int = 180) -> dict:
        """Default image generation method for providers that support it."""
        return format_error(
            provider=self.provider_name,
            error_code="FEATURE_NOT_SUPPORTED",
            message=f"Image generation is not supported for provider '{self.provider_name}'.",
            retryable=False,
        )

    def check_auth(self) -> bool:
        """Check if user appears to be authenticated on the provider's site."""
        return True

    def wait_for_element(self, by, value: str, timeout: int = 20):
        """Wait until an element is present and return it."""
        from selenium.webdriver.support import expected_conditions as EC
        return WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located((by, value))
        )

    def wait_for_clickable(self, by, value: str, timeout: int = 20):
        """Wait until an element is clickable and return it."""
        from selenium.webdriver.support import expected_conditions as EC
        return WebDriverWait(self.driver, timeout).until(
            EC.element_to_be_clickable((by, value))
        )

    def capture_error(self, error_code: str, message: str, retryable: bool = False) -> dict:
        """Capture screenshot and return a standardized error dictionary."""
        screenshot = self.browser_manager.take_screenshot(name_prefix=f"{self.provider_name}_err")
        return format_error(
            provider=self.provider_name,
            error_code=error_code,
            message=message,
            retryable=retryable,
            screenshot_path=screenshot,
        )
