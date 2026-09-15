import time
from typing import Optional, List, Tuple

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from app.browser import logger, DEFAULT_USER_AGENT
from app.config import settings
from app.captcha_solver import VisionCaptchaSolver
from app.parsers import format_text_success, format_error
from app.providers.base import BrowserProvider


class ClaudeBrowser(BrowserProvider):
    provider_name: str = "claude"
    base_url: str = settings.claude_url

    INPUT_SELECTORS: List[Tuple[By, str]] = [
        (By.CSS_SELECTOR, "div.tiptap.ProseMirror[contenteditable='true']"),
        (By.CSS_SELECTOR, "div[aria-label*='Write your prompt' i]"),
        (By.CSS_SELECTOR, "fieldset div[contenteditable='true']"),
        (By.CSS_SELECTOR, "div[contenteditable='true']"),
        (By.CSS_SELECTOR, "p[data-placeholder*='How can I help' i]"),
    ]

    SEND_BUTTON_SELECTORS: List[Tuple[By, str]] = [
        (By.CSS_SELECTOR, "button[data-testid='chat-input-send']"),
        (By.CSS_SELECTOR, "button[aria-label*='Send message' i]"),
        (By.CSS_SELECTOR, "button[aria-label*='Send' i]"),
    ]

    STOP_BUTTON_SELECTORS: List[Tuple[By, str]] = [
        (By.CSS_SELECTOR, "button[aria-label*='Stop' i]"),
        (By.CSS_SELECTOR, "button[data-testid='stop-button']"),
        (By.CSS_SELECTOR, "[data-is-streaming='true']"),
    ]

    RESPONSE_SELECTORS: List[Tuple[By, str]] = [
        (By.CSS_SELECTOR, "div.font-claude-response"),
        (By.CSS_SELECTOR, "div.font-claude-response .standard-markdown"),
        (By.CSS_SELECTOR, "div.font-claude-message"),
        (By.CSS_SELECTOR, "div.standard-markdown"),
        (By.CSS_SELECTOR, "div[data-test-render-count]"),
        (By.CSS_SELECTOR, ".font-claude-message .markdown"),
    ]

    def _focus_tab(self) -> None:
        """Switch to an existing tab for this provider if one exists."""
        try:
            for h in self.driver.window_handles:
                self.driver.switch_to.window(h)
                if "claude.ai" in self.driver.current_url.lower():
                    return
        except Exception:
            pass

    def _is_captcha_active(self) -> bool:
        """Check if Cloudflare Turnstile or security challenge is active and visible."""
        try:
            return bool(self.driver.execute_script("""
                var el = document.querySelector('iframe[src*="cloudflare"], div.cf-turnstile, [id*="cf-turnstile"], #challenge-stage');
                if (el && el.offsetWidth > 0 && el.offsetHeight > 0) return true;

                var text = ((document.body ? document.body.innerText : '') || '').toLowerCase();
                var hasEditor = !!document.querySelector('div[contenteditable="true"]');
                var isChallenge = !hasEditor && (
                    text.includes("verifying you are human") ||
                    text.includes("verify you are human") ||
                    text.includes("security verification") ||
                    text.includes("just a moment...") ||
                    text.includes("performance and security by cloudflare")
                );
                return isChallenge;
            """))
        except Exception:
            return False

    def _wait_for_cloudflare(self, timeout: int = 25) -> bool:
        """Handle Cloudflare 'Just a moment...' or 'Verifying you are human' challenge with VisionCaptchaSolver."""
        if self._is_captcha_active():
            logger.info(f"[{self.provider_name}] Cloudflare challenge detected ('{self.driver.title}'). Activating VisionCaptchaSolver...")
            return VisionCaptchaSolver.solve_if_needed(self.driver, timeout=timeout)
        return True

    def new_chat(self) -> None:
        """Start a fresh chat on Claude."""
        logger.info(f"[{self.provider_name}] Navigating to new chat at {self.base_url}...")
        self._focus_tab()
        try:
            self.driver.execute_cdp_cmd(
                "Network.setUserAgentOverride",
                {"userAgent": DEFAULT_USER_AGENT}
            )
        except Exception:
            pass
        self.driver.get(self.base_url)
        self._wait_for_cloudflare(timeout=20)
        time.sleep(2.0)
        self._dismiss_banners()

    def check_auth(self) -> bool:
        """Check if user is authenticated on Claude."""
        if self._is_captcha_active():
            return False
        current_url = self.driver.current_url.lower()
        if "login" in current_url or "signup" in current_url:
            return False
        try:
            login_buttons = self.driver.find_elements(
                By.XPATH, "//button[contains(text(), 'Log in') or contains(text(), 'Sign in')]"
            )
            if login_buttons and any(b.is_displayed() for b in login_buttons):
                return False
        except Exception:
            pass
        return True

    def _dismiss_banners(self) -> None:
        """Dismiss popups or announcement modals."""
        try:
            self.driver.execute_script("""
                document.querySelectorAll(
                    'button[aria-label*="close" i], button[aria-label*="dismiss" i], button:has-text("Acknowledge"), button:has-text("Got it")'
                ).forEach(function(b) {
                    if (b.offsetWidth > 0) b.click();
                });
            """)
        except Exception:
            pass

    def _find_input_element(self, timeout: int = 15):
        """Locate the Claude prompt input div."""
        self._dismiss_banners()
        end_time = time.time() + timeout
        while time.time() < end_time:
            if self._is_captcha_active():
                self._wait_for_cloudflare(timeout=5)
            for by, sel in self.INPUT_SELECTORS:
                try:
                    elements = self.driver.find_elements(by, sel)
                    for el in elements:
                        if el.is_displayed():
                            return el
                except Exception:
                    continue
            time.sleep(0.5)
        if self._is_captcha_active():
            raise TimeoutException("Claude is blocked by Cloudflare verification ('Verifying you are human').")
        raise NoSuchElementException("Could not locate Claude prompt input area.")

    def _submit_prompt(self, prompt: str) -> None:
        """Insert prompt into Claude ProseMirror editor and click send."""
        input_el = self._find_input_element()
        self.driver.execute_script("arguments[0].scrollIntoView(); arguments[0].focus();", input_el)
        time.sleep(0.2)

        # Dispatch text insertion via execCommand
        self.driver.execute_script("""
            var editor = arguments[0];
            editor.focus();
            document.execCommand('selectAll', false, null);
            document.execCommand('delete', false, null);
            document.execCommand('insertText', false, arguments[1]);
        """, input_el, prompt)

        time.sleep(0.6)

        clicked = False
        end_wait = time.time() + 3.0
        while time.time() < end_wait:
            try:
                clicked = self.driver.execute_script("""
                    var btn = document.querySelector('button[data-testid="chat-input-send"], button[aria-label*="Send message" i], button[aria-label*="Send" i]');
                    if (btn && btn.offsetWidth > 0 && !btn.disabled) {
                        btn.click();
                        return true;
                    }
                    return false;
                """)
                if clicked:
                    logger.info(f"[{self.provider_name}] Clicked send button")
                    break
            except Exception:
                pass
            time.sleep(0.3)

        if not clicked:
            logger.info(f"[{self.provider_name}] Send button not ready, sending Enter key")
            input_el.send_keys(Keys.ENTER)

    def _is_generating(self) -> bool:
        """Check if Claude is actively generating a response."""
        for by, sel in self.STOP_BUTTON_SELECTORS:
            try:
                elements = self.driver.find_elements(by, sel)
                if any(el.is_displayed() for el in elements):
                    return True
            except Exception:
                continue
        return False

    def _try_get_response_text(self) -> Optional[str]:
        """Extract latest Claude response text."""
        try:
            text = self.driver.execute_script("""
                var candidates = document.querySelectorAll(
                    'div.font-claude-response, div.standard-markdown, div.font-claude-message, [data-is-streaming="true"], div[data-test-render-count]'
                );
                if (candidates && candidates.length > 0) {
                    var last = candidates[candidates.length - 1];
                    return (last.innerText || last.textContent || '').trim();
                }
                return null;
            """)
            if text and len(text.strip()) > 0:
                return text.strip()
        except Exception:
            pass

        for by, sel in self.RESPONSE_SELECTORS:
            try:
                elements = self.driver.find_elements(by, sel)
                if elements:
                    t = elements[-1].get_attribute("innerText") or elements[-1].text
                    if t and t.strip():
                        return t.strip()
            except Exception:
                continue
        return None

    def _wait_for_completion(self, timeout: int = 120) -> str:
        """Wait until Claude finishes generating and text stabilizes."""
        start_time = time.time()
        end_time = start_time + timeout

        logger.info(f"[{self.provider_name}] Waiting for response...")
        last_text = ""
        stable_count = 0

        while time.time() < end_time:
            current_text = self._try_get_response_text()
            if current_text:
                if current_text == last_text and not self._is_generating():
                    stable_count += 1
                    if stable_count >= 2:
                        logger.info(f"[{self.provider_name}] Generation complete ({len(current_text)} chars).")
                        return current_text
                else:
                    stable_count = 0
                    last_text = current_text
            time.sleep(0.8)

        if last_text:
            return last_text
        raise TimeoutException(f"Claude response timed out after {timeout} seconds.")

    def ask(self, prompt: str, timeout: int = 120) -> dict:
        """Send a prompt to Claude in a fresh chat session and return the text response."""
        start_time = time.time()
        try:
            self.new_chat()

            if not self.check_auth():
                if self._is_captcha_active():
                    return self.capture_error(
                        error_code="CAPTCHA_REQUIRED",
                        message="Cloudflare Turnstile verification active on Claude. Please allow your auto-solve extension to resolve it or solve it once via start_chrome.bat.",
                        retryable=False,
                    )
                return self.capture_error(
                    error_code="SESSION_EXPIRED",
                    message="Login required for Claude. Please log in in the open Chrome profile.",
                    retryable=False,
                )

            logger.info(f"[{self.provider_name}] Submitting prompt...")
            self._submit_prompt(prompt)

            response_text = self._wait_for_completion(timeout=timeout)
            duration = time.time() - start_time

            return format_text_success(
                provider=self.provider_name,
                content=response_text,
                duration_seconds=duration,
            )
        except TimeoutException as e:
            return self.capture_error(error_code="TIMEOUT", message=f"Claude timed out: {e}", retryable=True)
        except Exception as e:
            logger.exception(f"[{self.provider_name}] Error: {e}")
            return self.capture_error(error_code="EXECUTION_ERROR", message=str(e), retryable=False)
