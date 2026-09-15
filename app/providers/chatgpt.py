import base64
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple, Union, Dict, Any

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from app.config import settings
from app.browser import DEFAULT_USER_AGENT, logger
from app.captcha_solver import VisionCaptchaSolver
from app.parsers import format_text_success, format_image_success, format_error
from app.providers.base import BrowserProvider


class ChatGPTBrowser(BrowserProvider):
    provider_name: str = "chatgpt"
    base_url: str = settings.chatgpt_url

    INPUT_SELECTORS: List[Tuple[By, str]] = [
        (By.CSS_SELECTOR, "#prompt-textarea"),
        (By.CSS_SELECTOR, "div.ProseMirror#prompt-textarea"),
        (By.CSS_SELECTOR, "div.ProseMirror[contenteditable='true']"),
        (By.CSS_SELECTOR, "div[contenteditable='true'][data-placeholder*='Ask' i]"),
        (By.CSS_SELECTOR, "div[contenteditable='true']"),
        (By.CSS_SELECTOR, "textarea[placeholder*='Ask anything' i]"),
        (By.CSS_SELECTOR, "textarea.wcDTda_fallbackTextarea"),
        (By.CSS_SELECTOR, "textarea"),
    ]

    SEND_BUTTON_SELECTORS: List[Tuple[By, str]] = [
        (By.CSS_SELECTOR, "button[data-testid='send-button']"),
        (By.CSS_SELECTOR, "button[aria-label*='Send prompt' i]"),
        (By.CSS_SELECTOR, "button[aria-label*='Send message' i]"),
        (By.CSS_SELECTOR, "button[data-testid='fruitjuice-send-button']"),
    ]

    STOP_BUTTON_SELECTORS: List[Tuple[By, str]] = [
        (By.CSS_SELECTOR, "button[data-testid='stop-button']"),
        (By.CSS_SELECTOR, "button[aria-label*='Stop' i]"),
        (By.CSS_SELECTOR, ".stop-button"),
    ]

    RESPONSE_SELECTORS: List[Tuple[By, str]] = [
        (By.CSS_SELECTOR, "div[data-message-author-role='assistant'] .markdown"),
        (By.CSS_SELECTOR, "div[data-message-author-role='assistant']"),
        (By.CSS_SELECTOR, "article[data-testid*='conversation-turn'] .markdown"),
        (By.CSS_SELECTOR, ".agent-turn .markdown"),
        (By.CSS_SELECTOR, ".markdown"),
    ]

    def _focus_tab(self) -> None:
        """Switch to an existing tab for this provider if one exists."""
        try:
            for h in self.driver.window_handles:
                self.driver.switch_to.window(h)
                if "chatgpt.com" in self.driver.current_url.lower():
                    return
        except Exception:
            pass

    def _wait_for_cloudflare(self, timeout: int = 25) -> bool:
        """Handle Cloudflare or CAPTCHA challenge if encountered using VisionCaptchaSolver."""
        if VisionCaptchaSolver.is_captcha_present(self.driver):
            logger.info(f"[{self.provider_name}] Cloudflare challenge detected ('{self.driver.title}'). Activating VisionCaptchaSolver...")
            return VisionCaptchaSolver.solve_if_needed(self.driver, timeout=timeout)
        return True

    def new_chat(self) -> None:
        """Start a fresh chat session on ChatGPT."""
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
        """Check if user is logged into ChatGPT."""
        self._focus_tab()
        current_url = self.driver.current_url.lower()
        if "auth0" in current_url or "login" in current_url:
            return False
        try:
            login_buttons = self.driver.find_elements(
                By.CSS_SELECTOR, "button[data-testid='login-button'], a[href*='login']"
            )
            if login_buttons and any(b.is_displayed() for b in login_buttons):
                return False
        except Exception:
            pass
        return True

    def _dismiss_banners(self) -> None:
        """Dismiss popups, cookie notices, or onboarding dialogs."""
        try:
            self.driver.execute_script("""
                document.querySelectorAll(
                    'button[aria-label*="close" i], button[aria-label*="dismiss" i]'
                ).forEach(function(b) {
                    if (b.offsetWidth > 0) b.click();
                });
            """)
        except Exception:
            pass

    def _find_input_element(self, timeout: int = 15):
        """Find the prompt input textarea or ProseMirror editable div."""
        self._dismiss_banners()
        end_time = time.time() + timeout
        while time.time() < end_time:
            if "just a moment" in (self.driver.title or "").lower():
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
        if "just a moment" in (self.driver.title or "").lower():
            raise TimeoutException("ChatGPT is blocked by Cloudflare verification ('Just a moment...').")
        raise NoSuchElementException("Could not locate ChatGPT prompt input area.")

    def _submit_prompt(self, prompt: str, web_search: bool = False) -> None:
        """Insert prompt into ChatGPT and click send."""
        # Optional: enable Web Search toggle if requested
        if web_search:
            try:
                search_toggled = self.driver.execute_script("""
                    var btn = document.querySelector('button[data-testid="search-button"], button[aria-label*="Search" i]');
                    if (btn && btn.getAttribute('aria-pressed') !== 'true') {
                        btn.click();
                        return true;
                    }
                    return false;
                """)
                if search_toggled:
                    logger.info(f"[{self.provider_name}] Web Search toggle activated.")
                    time.sleep(0.5)
            except Exception:
                pass

        input_el = self._find_input_element()
        self.driver.execute_script("arguments[0].scrollIntoView(); arguments[0].focus();", input_el)
        time.sleep(0.2)

        # Dispatch text using execCommand for ProseMirror compatibility
        self.driver.execute_script("""
            var editor = arguments[0];
            editor.focus();
            if (editor.tagName.toLowerCase() === 'textarea') {
                editor.value = arguments[1];
                editor.dispatchEvent(new Event('input', { bubbles: true }));
                editor.dispatchEvent(new Event('change', { bubbles: true }));
            } else {
                document.execCommand('selectAll', false, null);
                document.execCommand('delete', false, null);
                document.execCommand('insertText', false, arguments[1]);
            }
        """, input_el, prompt)

        time.sleep(0.6)

        # Click send button
        clicked = False
        end_wait = time.time() + 3.0
        while time.time() < end_wait:
            try:
                clicked = self.driver.execute_script("""
                    var btn = document.querySelector('button[data-testid="send-button"], button[aria-label*="Send" i], button[data-testid="fruitjuice-send-button"]');
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
            # Fallback to pressing ENTER
            logger.info(f"[{self.provider_name}] Send button not ready, pressing Enter")
            input_el.send_keys(Keys.ENTER)

    def _is_generating(self) -> bool:
        """Check if ChatGPT is actively generating (stop button visible)."""
        try:
            return bool(self.driver.execute_script("""
                var stopBtn = document.querySelector('button[data-testid="stop-button"], button[aria-label*="Stop" i]');
                if (stopBtn && stopBtn.offsetWidth > 0) return true;
                return false;
            """))
        except Exception:
            return False

    def _try_get_response_text(self) -> Optional[str]:
        """Extract latest assistant response text."""
        try:
            text = self.driver.execute_script("""
                var candidates = document.querySelectorAll(
                    'div[data-message-author-role="assistant"] .markdown, div[data-message-author-role="assistant"], article[data-testid*="conversation-turn"] .markdown, .agent-turn .markdown'
                );
                if (candidates && candidates.length > 0) {
                    for (var i = candidates.length - 1; i >= 0; i--) {
                        var t = (candidates[i].innerText || candidates[i].textContent || '').trim();
                        if (t.length > 0) return t;
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
                    t = el.get_attribute("innerText") or el.text
                    if t and t.strip():
                        return t.strip()
            except Exception:
                continue
        return None

    def _wait_for_completion(self, timeout: int = 180) -> str:
        """Wait until ChatGPT stops streaming and text stabilizes."""
        start_time = time.time()
        end_time = start_time + timeout

        logger.info(f"[{self.provider_name}] Waiting for response...")
        last_text = ""
        stable_count = 0
        last_log_time = 0

        while time.time() < end_time:
            current_text = self._try_get_response_text()
            generating = self._is_generating()

            now = time.time()
            if now - last_log_time >= 3.0:
                last_log_time = now
                snippet = repr(current_text[:40]) if current_text else "None"
                logger.info(f"[{self.provider_name}] Polling ({round(now - start_time)}s elapsed): text={snippet}, generating={generating}")

            if current_text:
                if current_text == last_text and not generating:
                    stable_count += 1
                    if stable_count >= 2:
                        logger.info(f"[{self.provider_name}] Generation complete ({len(current_text)} chars).")
                        return current_text
                else:
                    stable_count = 0
                    last_text = current_text
            elif not generating and last_text:
                logger.info(f"[{self.provider_name}] Stream completed with existing text ({len(last_text)} chars).")
                return last_text

            time.sleep(0.8)

        if last_text:
            return last_text
        raise TimeoutException(f"ChatGPT response timed out after {timeout} seconds.")

    def ask(self, prompt: str, timeout: int = 120, web_search: bool = False) -> dict:
        """Send a prompt to ChatGPT and return text response."""
        start_time = time.time()
        try:
            self.new_chat()

            if not self.check_auth():
                return self.capture_error(
                    error_code="SESSION_EXPIRED",
                    message="Login required for ChatGPT. Please log in in the open Chrome profile.",
                    retryable=False,
                )

            search_label = " (with Web Search)" if web_search else ""
            logger.info(f"[{self.provider_name}] Submitting prompt{search_label}...")
            self._submit_prompt(prompt, web_search=web_search)

            response_text = self._wait_for_completion(timeout=timeout)
            duration = time.time() - start_time

            return format_text_success(
                provider=self.provider_name,
                content=response_text,
                duration_seconds=duration,
                extra={"web_search": web_search},
            )
        except TimeoutException as e:
            return self.capture_error(error_code="TIMEOUT", message=f"ChatGPT timed out: {e}", retryable=True)
        except Exception as e:
            logger.exception(f"[{self.provider_name}] Error: {e}")
            return self.capture_error(error_code="EXECUTION_ERROR", message=str(e), retryable=False)

    def search(self, query: str, timeout: int = 120) -> dict:
        """Search the web using ChatGPT's web search engine."""
        return self.ask(prompt=query, timeout=timeout, web_search=True)

    def generate_image(self, prompt: str, output_name: str = "chatgpt_image", timeout: int = 180) -> dict:
        """Request ChatGPT to generate an image via DALL-E 3 and download it."""
        start_time = time.time()
        try:
            self.new_chat()

            if not self.check_auth():
                return self.capture_error(
                    error_code="SESSION_EXPIRED",
                    message="Login required for ChatGPT. Please log in in the open Chrome profile.",
                    retryable=False,
                )

            full_prompt = prompt if "image" in prompt.lower() or "generate" in prompt.lower() else f"Generate an image of: {prompt}"
            logger.info(f"[{self.provider_name}] Requesting image: '{full_prompt}'...")
            self._submit_prompt(full_prompt)

            # Wait for completion of response
            self._wait_for_completion(timeout=timeout)

            # Look for generated DALL-E image
            end_time = time.time() + 20
            img_element = None
            candidate_selectors = [
                "div[data-message-author-role='assistant'] img",
                "img[src*='oaiusercontent']",
                "img[alt*='Generated' i]",
                "article img",
            ]

            while time.time() < end_time:
                for sel in candidate_selectors:
                    try:
                        imgs = self.driver.find_elements(By.CSS_SELECTOR, sel)
                        for img in imgs:
                            if img.is_displayed() and img.size.get("width", 0) > 100:
                                img_element = img
                                break
                        if img_element:
                            break
                    except Exception:
                        continue
                if img_element:
                    break
                time.sleep(1.0)

            if not img_element:
                return self.capture_error(
                    error_code="IMAGE_NOT_FOUND",
                    message="No generated image was detected in ChatGPT's response.",
                    retryable=False,
                )

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            sanitized_name = "".join(c for c in output_name if c.isalnum() or c in ("-", "_")).strip() or "image"
            target_path = settings.outputs_dir / f"{sanitized_name}_{timestamp}.png"

            # Extract via Canvas
            try:
                data_url = self.driver.execute_script("""
                    var img = arguments[0];
                    var canvas = document.createElement('canvas');
                    canvas.width = img.naturalWidth || img.width;
                    canvas.height = img.naturalHeight || img.height;
                    var ctx = canvas.getContext('2d');
                    ctx.drawImage(img, 0, 0);
                    return canvas.toDataURL('image/png');
                """, img_element)
                if data_url and "," in data_url:
                    base64_data = data_url.split(",", 1)[1]
                    with open(target_path, "wb") as f:
                        f.write(base64.b64decode(base64_data))
            except Exception:
                pass

            # Fallback to element screenshot
            if not target_path.exists() or target_path.stat().st_size < 1024:
                img_element.screenshot(str(target_path))

            duration = time.time() - start_time
            logger.info(f"[{self.provider_name}] Image saved successfully to: {target_path}")

            return format_image_success(
                provider=self.provider_name,
                file_path=str(target_path),
                mime_type="image/png",
                content="Image generated successfully via ChatGPT DALL-E.",
                extra={"duration_seconds": round(duration, 2)},
            )
        except Exception as e:
            logger.exception(f"[{self.provider_name}] Image generation error: {e}")
            return self.capture_error(error_code="IMAGE_GENERATION_FAILED", message=str(e), retryable=False)
