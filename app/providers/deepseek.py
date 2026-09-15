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


class DeepSeekBrowser(BrowserProvider):
    provider_name: str = "deepseek"
    base_url: str = settings.deepseek_url

    INPUT_SELECTORS: List[Tuple[By, str]] = [
        (By.CSS_SELECTOR, "textarea[placeholder*='Message DeepSeek' i]"),
        (By.CSS_SELECTOR, "textarea.ds-scroll-area"),
        (By.CSS_SELECTOR, "textarea[placeholder*='Ask anything' i]"),
        (By.CSS_SELECTOR, "textarea"),
    ]

    SEND_BUTTON_SELECTORS: List[Tuple[By, str]] = [
        (By.CSS_SELECTOR, "div.ds-icon-button[aria-label*='Send' i]"),
        (By.CSS_SELECTOR, "button[aria-label*='Send' i]"),
        (By.CSS_SELECTOR, "div[role='button'][aria-label*='Send' i]"),
        (By.CSS_SELECTOR, ".ds-send-btn"),
    ]

    STOP_BUTTON_SELECTORS: List[Tuple[By, str]] = [
        (By.CSS_SELECTOR, "div.ds-icon-button[aria-label*='Stop' i]"),
        (By.CSS_SELECTOR, "button[aria-label*='Stop' i]"),
        (By.CSS_SELECTOR, ".ds-stop-btn"),
    ]

    RESPONSE_SELECTORS: List[Tuple[By, str]] = [
        (By.CSS_SELECTOR, "div.ds-assistant-message-main-content"),
        (By.CSS_SELECTOR, "div.ds-markdown:not(.ds-markdown-cite)"),
        (By.CSS_SELECTOR, "div.ds-message"),
        (By.CSS_SELECTOR, "div._9986c0c"),
        (By.CSS_SELECTOR, "div.d00ed9c9"),
        (By.CSS_SELECTOR, "div._1aa2651"),
    ]

    def _focus_tab(self) -> None:
        """Switch to an existing tab for this provider if one exists."""
        try:
            for h in self.driver.window_handles:
                self.driver.switch_to.window(h)
                if "deepseek.com" in self.driver.current_url.lower():
                    return
        except Exception:
            pass

    def _is_captcha_active(self) -> bool:
        """Check if Cloudflare Turnstile or security verification challenge is active and visible."""
        try:
            return bool(self.driver.execute_script("""
                var el = document.querySelector('iframe[src*="cloudflare"], div.cf-turnstile, [id*="cf-turnstile"], #challenge-stage');
                if (el && el.offsetWidth > 0 && el.offsetHeight > 0) return true;

                var text = (document.body ? document.body.innerText : '') || '';
                var hasTextarea = !!document.querySelector('textarea');
                var isChallengeText = !hasTextarea && (
                    text.includes("security verification") ||
                    text.includes("Verify you are human") ||
                    text.includes("One more step before you proceed")
                );
                return isChallengeText;
            """))
        except Exception:
            return False

    def new_chat(self) -> None:
        """Start a fresh chat on DeepSeek."""
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
        time.sleep(2.5)

        # Handle security challenge if active
        if self._is_captcha_active():
            logger.info(f"[{self.provider_name}] Verification challenge detected. Activating VisionCaptchaSolver...")
            VisionCaptchaSolver.solve_if_needed(self.driver, timeout=30)

        self._dismiss_banners()

    def check_auth(self) -> bool:
        """Check if user is authenticated on DeepSeek."""
        if self._is_captcha_active():
            return False
        current_url = self.driver.current_url.lower()
        if "login" in current_url or "sign_in" in current_url:
            return False
        try:
            login_buttons = self.driver.find_elements(
                By.XPATH, "//button[contains(text(), 'Log In') or contains(text(), 'Sign In') or contains(text(), 'Sign up')]"
            )
            if login_buttons and any(b.is_displayed() for b in login_buttons):
                return False
        except Exception:
            pass
        return True

    def _dismiss_banners(self) -> None:
        """Dismiss popup banners if present."""
        try:
            self.driver.execute_script("""
                document.querySelectorAll(
                    'button[aria-label*="close" i], button[aria-label*="dismiss" i], .ds-modal-close'
                ).forEach(function(b) {
                    if (b.offsetWidth > 0) b.click();
                });
            """)
        except Exception:
            pass

    def _find_input_element(self, timeout: int = 15):
        """Locate the DeepSeek prompt textarea."""
        self._dismiss_banners()
        end_time = time.time() + timeout
        while time.time() < end_time:
            for by, sel in self.INPUT_SELECTORS:
                try:
                    elements = self.driver.find_elements(by, sel)
                    for el in elements:
                        if el.is_displayed():
                            return el
                except Exception:
                    continue
            time.sleep(0.5)
        raise NoSuchElementException("Could not locate DeepSeek prompt input area.")

    def _set_toggles(self, web_search: bool = False, deepthink: bool = False) -> None:
        """Set DeepSeek Search and DeepThink toggle states."""
        try:
            self.driver.execute_script("""
                var searchNeeded = arguments[0];
                var thinkNeeded = arguments[1];

                var btns = document.querySelectorAll('button, div[role="button"], .ds-hero-toggle-btn, .ds-toggle-button');
                btns.forEach(function(b) {
                    var txt = (b.innerText || '').trim().toLowerCase();
                    var isSelected = b.className.includes('selected') || b.className.includes('ds-toggle-button--selected') || b.getAttribute('aria-pressed') === 'true';

                    if (txt.includes('search') || txt.includes('smart search')) {
                        if (searchNeeded && !isSelected) b.click();
                        else if (!searchNeeded && isSelected) b.click();
                    }
                    if (txt.includes('deepthink') || txt.includes('deep thinking')) {
                        if (thinkNeeded && !isSelected) b.click();
                        else if (!thinkNeeded && isSelected) b.click();
                    }
                });
            """, web_search, deepthink)
            time.sleep(0.3)
        except Exception as e:
            logger.debug(f"[{self.provider_name}] Toggle set error: {e}")

    def _submit_prompt(self, prompt: str, web_search: bool = False, deepthink: bool = False) -> None:
        """Insert prompt into DeepSeek input and send."""
        self._set_toggles(web_search=web_search, deepthink=deepthink)

        input_el = self._find_input_element()
        self.driver.execute_script("arguments[0].scrollIntoView(); arguments[0].focus();", input_el)
        time.sleep(0.2)

        # Set value using React prototype descriptor to ensure state updates
        self.driver.execute_script("""
            var el = arguments[0];
            el.focus();
            try {
                var setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
                setter.call(el, arguments[1]);
            } catch(e) {
                el.value = arguments[1];
            }
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        """, input_el, prompt)

        time.sleep(0.6)

        # Click send button
        clicked = False
        end_wait = time.time() + 4.0
        while time.time() < end_wait:
            try:
                clicked = self.driver.execute_script("""
                    var sendBtn = document.querySelector(
                        'div[role="button"].ds-button--circle, div.ds-icon-button[aria-label*="Send" i], button[aria-label*="Send" i], div[role="button"][aria-label*="Send" i], button.ds-send-btn'
                    );
                    if (sendBtn && !sendBtn.className.includes('disabled') && !sendBtn.className.includes('ds-button--disabled') && !sendBtn.disabled && sendBtn.getAttribute('aria-disabled') !== 'true') {
                        sendBtn.click();
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
        """Check if DeepSeek is generating."""
        try:
            return bool(self.driver.execute_script("""
                var stopBtn = document.querySelector('div.ds-icon-button[aria-label*="Stop" i], button[aria-label*="Stop" i], .ds-stop-btn');
                if (stopBtn && stopBtn.offsetWidth > 0) return true;
                var circleBtn = document.querySelector('div[role="button"].ds-button--circle');
                if (circleBtn && (circleBtn.className.includes('stop') || (circleBtn.getAttribute('aria-label') || '').toLowerCase().includes('stop'))) return true;
                return false;
            """))
        except Exception:
            return False

    def _try_get_response_text(self) -> Optional[str]:
        """Extract latest DeepSeek response text, avoiding citation badges."""
        try:
            text = self.driver.execute_script("""
                var candidates = document.querySelectorAll(
                    'div.ds-assistant-message-main-content, div.ds-markdown, div.ds-message, div._9986c0c, div.d00ed9c9'
                );
                for (var i = candidates.length - 1; i >= 0; i--) {
                    var el = candidates[i];
                    if (el.className.includes('cite') || el.className.includes('badge') || el.tagName === 'SPAN' || el.tagName === 'A') {
                        continue;
                    }
                    var t = (el.innerText || el.textContent || '').trim();
                    if (t.length > 0 && !t.startsWith('-\\n') && !t.startsWith('-10') && !t.startsWith('- 10')) {
                        return t;
                    }
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
                for el in reversed(elements):
                    cls = el.get_attribute("class") or ""
                    if "cite" in cls or "badge" in cls or el.tag_name in ("span", "a"):
                        continue
                    t = (el.get_attribute("innerText") or el.text or "").strip()
                    if t and not t.startswith("-\n") and not t.startswith("-10"):
                        return t
            except Exception:
                continue
        return None

    def _wait_for_completion(self, timeout: int = 150) -> str:
        """Wait until DeepSeek finishes generating."""
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
            time.sleep(1.0)

        if last_text:
            return last_text
        raise TimeoutException(f"DeepSeek response timed out after {timeout} seconds.")

    def ask(self, prompt: str, timeout: int = 150, web_search: bool = False, deepthink: bool = False) -> dict:
        """Send a prompt to DeepSeek and return text response."""
        start_time = time.time()
        try:
            self.new_chat()

            if not self.check_auth():
                if self._is_captcha_active():
                    return self.capture_error(
                        error_code="CAPTCHA_REQUIRED",
                        message="Verification challenge active on DeepSeek. Please allow your auto-solve extension to resolve it or solve it once via start_chrome.bat.",
                        retryable=False,
                    )
                return self.capture_error(
                    error_code="SESSION_EXPIRED",
                    message="Login required for DeepSeek. Please log in in the open Chrome profile.",
                    retryable=False,
                )

            tags = []
            if web_search:
                tags.append("Web Search")
            if deepthink:
                tags.append("DeepThink")
            tag_str = f" ({', '.join(tags)})" if tags else ""

            logger.info(f"[{self.provider_name}] Submitting prompt{tag_str}...")
            self._submit_prompt(prompt, web_search=web_search, deepthink=deepthink)

            response_text = self._wait_for_completion(timeout=timeout)
            duration = time.time() - start_time

            return format_text_success(
                provider=self.provider_name,
                content=response_text,
                duration_seconds=duration,
                extra={"web_search": web_search, "deepthink": deepthink},
            )
        except TimeoutException as e:
            return self.capture_error(error_code="TIMEOUT", message=f"DeepSeek timed out: {e}", retryable=True)
        except Exception as e:
            logger.exception(f"[{self.provider_name}] Error: {e}")
            return self.capture_error(error_code="EXECUTION_ERROR", message=str(e), retryable=False)

    def search(self, query: str, timeout: int = 150) -> dict:
        """Search the web using DeepSeek Search."""
        return self.ask(prompt=query, timeout=timeout, web_search=True)
