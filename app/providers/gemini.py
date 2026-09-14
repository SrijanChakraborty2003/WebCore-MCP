import base64
import os
import time
from datetime import datetime
from pathlib import Path
import re
from typing import Optional, List, Tuple, Union, Dict, Any

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException,
    WebDriverException,
)

from app.browser import logger
from app.config import settings
from app.parsers import format_text_success, format_image_success, format_error
from app.providers.base import BrowserProvider


class GeminiBrowser(BrowserProvider):
    provider_name: str = "gemini"
    base_url: str = settings.gemini_url

    # Candidate selectors for prompt input
    INPUT_SELECTORS: List[Tuple[By, str]] = [
        (By.CSS_SELECTOR, "rich-textarea div[contenteditable='true']"),
        (By.CSS_SELECTOR, "div[contenteditable='true']"),
        (By.CSS_SELECTOR, ".ql-editor"),
        (By.CSS_SELECTOR, "textarea[aria-label*='prompt' i]"),
        (By.CSS_SELECTOR, "rich-textarea textarea"),
    ]

    # Candidate selectors for send button
    SEND_BUTTON_SELECTORS: List[Tuple[By, str]] = [
        (By.CSS_SELECTOR, "button[aria-label*='Send message' i]"),
        (By.CSS_SELECTOR, "button[aria-label*='Send' i]"),
        (By.CSS_SELECTOR, "button.send-button"),
        (By.CSS_SELECTOR, ".send-button-container button"),
        (By.CSS_SELECTOR, "button[data-test-id='send-button']"),
    ]

    # Candidate selectors for stop / generating indicator
    STOP_BUTTON_SELECTORS: List[Tuple[By, str]] = [
        (By.CSS_SELECTOR, "button[aria-label*='Stop response' i]"),
        (By.CSS_SELECTOR, "button[aria-label*='Stop' i]"),
        (By.CSS_SELECTOR, "mat-icon[fonticon='stop']"),
        (By.CSS_SELECTOR, ".stop-button"),
    ]

    RESPONSE_SELECTORS: List[Tuple[By, str]] = [
        (By.CSS_SELECTOR, "model-response-content"),
        (By.CSS_SELECTOR, "message-content"),
        (By.CSS_SELECTOR, "structured-content-container.model-response-text"),
        (By.CSS_SELECTOR, ".model-response-text"),
        (By.CSS_SELECTOR, "div.markdown.md-content"),
        (By.CSS_SELECTOR, "model-response"),
    ]

    def _try_get_response_text(self) -> Optional[str]:
        """Try extracting the current response text via JS and CSS selectors."""
        try:
            text = self.driver.execute_script("""
                var candidates = document.querySelectorAll(
                    '.response-content, model-response-content, message-content, structured-content-container.model-response-text, .model-response-text, div.markdown.md-content'
                );
                if (candidates && candidates.length > 0) {
                    var last = candidates[candidates.length - 1];
                    var t = last.innerText || last.textContent || '';
                    return t.trim();
                }
                return null;
            """)
            if text and len(text.strip()) > 0:
                import re
                cleaned = re.sub(r'^Gemini said\s*', '', text.strip()).strip()
                if cleaned:
                    return cleaned
        except Exception:
            pass

        for by, sel in self.RESPONSE_SELECTORS:
            try:
                elements = self.driver.find_elements(by, sel)
                if elements:
                    latest = elements[-1]
                    t = latest.get_attribute("innerText") or latest.text
                    if t and t.strip():
                        import re
                        cleaned = re.sub(r'^Gemini said\s*', '', t.strip()).strip()
                        if cleaned:
                            return cleaned
            except Exception:
                continue
        return None

    def _sanitize_prompt_for_filename(self, prompt: str) -> str:
        """Generate a clean slug for filenames from a prompt."""
        cleaned = re.sub(
            r'^(generate|create|draw|make|show me)\s+(an?\s+)?(image|picture|photo|illustration)\s+(of\s+)?',
            '',
            prompt,
            flags=re.IGNORECASE
        )
        cleaned = re.sub(r'[^a-zA-Z0-9_\-\s]', '', cleaned).strip()
        words = cleaned.split()[:4]
        name = "_".join(words).lower()
        return name or "image"

    def _is_generating_image_in_dom(self) -> bool:
        """Check if Gemini DOM currently indicates an image generation is in progress."""
        try:
            return bool(self.driver.execute_script("""
                // Active shimmer or loading overlay without done-generating
                var activeShimmer = document.querySelector(
                    '.shimmer-overlay:not(.done-generating), [data-test-id="image-loading-overlay"]:not(.done-generating)'
                );
                if (activeShimmer && activeShimmer.offsetWidth > 0) return true;

                // Host loading overlay without done-generating child
                var loadingHost = document.querySelector('image-loading-overlay');
                if (loadingHost && !loadingHost.querySelector('.done-generating')) return true;

                // Generated image containers where image hasn't rendered yet
                var genContainers = document.querySelectorAll('generated-image, single-image');
                for (var i = 0; i < genContainers.length; i++) {
                    var c = genContainers[i];
                    var done = c.querySelector('.done-generating');
                    var img = c.querySelector('img');
                    if (!done || !img || !img.complete || (img.naturalWidth || img.width) < 50) {
                        return true;
                    }
                }
                return false;
            """))
        except Exception:
            return False

    def _is_image_ready_in_dom(self) -> bool:
        """Check if a generated image has fully rendered in the DOM."""
        try:
            return bool(self.driver.execute_script("""
                var img = document.querySelector(
                    'generated-image img, single-image img, .image-container img, img.image.loaded'
                );
                if (!img) return false;
                var w = img.naturalWidth || img.width || 0;
                var h = img.naturalHeight || img.height || 0;
                return img.complete && w > 100 && h > 100;
            """))
        except Exception:
            return False

    def _wait_for_image_completion(
        self,
        timeout: int = 180,
        output_name: str = "image",
        start_time: Optional[float] = None
    ) -> dict:
        """
        Wait until the image finishes generating and rendering, logging progress periodically,
        and extract the image to disk.
        """
        t0 = start_time or time.time()
        end_time = t0 + timeout
        last_log = 0.0

        logger.info(f"[{self.provider_name}] Image generation in progress. Waiting for render...")

        while time.time() < end_time:
            now = time.time()
            elapsed = int(now - t0)

            # Check if image is ready and rendered
            if self._is_image_ready_in_dom():
                time.sleep(0.5)
                logger.info(f"[{self.provider_name}] Image generation finished in {elapsed}s! Extracting...")
                return self._extract_and_save_image(output_name=output_name, start_time=t0)

            # Periodic status logging every 3 seconds to keep user informed
            if now - last_log >= 3.0:
                logger.info(f"[{self.provider_name}] Image is being generated... ({elapsed}s elapsed)")
                last_log = now

            # Check for refusal or error messages if no shimmer is active
            if elapsed > 10 and not self._is_generating_image_in_dom():
                current_text = self._try_get_response_text() or ""
                refusal_cues = ["i cannot", "i can't", "unable to generate", "unable to create", "safety guideline", "policy"]
                if any(cue in current_text.lower() for cue in refusal_cues):
                    logger.warning(f"[{self.provider_name}] Image generation refused: {current_text}")
                    return format_error(
                        provider=self.provider_name,
                        error_code="IMAGE_GENERATION_REFUSED",
                        message=current_text,
                        retryable=False,
                    )

            time.sleep(1.0)

        raise TimeoutException(f"Gemini image generation timed out after {timeout} seconds.")

    def _extract_and_save_image(self, output_name: str = "image", start_time: Optional[float] = None) -> dict:
        """
        Extract the generated image from the DOM via HTML5 Canvas (or element screenshot fallback)
        and save to settings.outputs_dir.
        """
        t0 = start_time or time.time()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        sanitized_name = "".join(c for c in output_name if c.isalnum() or c in ("-", "_")).strip() or "image"
        target_path = settings.outputs_dir / f"{sanitized_name}_{timestamp}.png"

        # 1. Primary: Extract high-resolution base64 via Canvas in browser
        try:
            data_url = self.driver.execute_script("""
                var img = document.querySelector(
                    'generated-image img, single-image img, .image-container img, img.image.loaded'
                );
                if (!img) return null;
                var canvas = document.createElement('canvas');
                canvas.width = img.naturalWidth || img.width;
                canvas.height = img.naturalHeight || img.height;
                var ctx = canvas.getContext('2d');
                ctx.drawImage(img, 0, 0);
                return canvas.toDataURL('image/png');
            """)
            if data_url and "," in data_url:
                base64_data = data_url.split(",", 1)[1]
                with open(target_path, "wb") as f:
                    f.write(base64.b64decode(base64_data))
        except Exception as e:
            logger.warning(f"[{self.provider_name}] Canvas extraction failed ({e}), attempting fallback...")

        # 2. Fallback: Selenium element screenshot
        if not target_path.exists() or target_path.stat().st_size < 1024:
            try:
                candidate_img_selectors = [
                    "generated-image img",
                    "single-image img",
                    ".image-container img",
                    "img.image.loaded",
                    "img[alt*='Generated' i]",
                ]
                for sel in candidate_img_selectors:
                    imgs = self.driver.find_elements(By.CSS_SELECTOR, sel)
                    for img in imgs:
                        if img.is_displayed() and img.size.get("width", 0) > 100:
                            img.screenshot(str(target_path))
                            break
                    if target_path.exists() and target_path.stat().st_size > 1024:
                        break
            except Exception as e:
                logger.error(f"[{self.provider_name}] Element screenshot fallback failed: {e}")

        if not target_path.exists() or target_path.stat().st_size < 1024:
            return self.capture_error(
                error_code="IMAGE_SAVE_FAILED",
                message="Failed to extract or save the generated image.",
                retryable=False,
            )

        duration = time.time() - t0
        logger.info(f"[{self.provider_name}] Image saved successfully ({target_path.stat().st_size} bytes) to: {target_path}")

        return format_image_success(
            provider=self.provider_name,
            file_path=str(target_path),
            mime_type="image/png",
            content="Image generated successfully.",
            extra={
                "duration_seconds": round(duration, 2),
                "file_size_bytes": target_path.stat().st_size,
            },
        )

    def _wait_for_completion(self, timeout: int = 120, prompt: str = "") -> Union[dict, str]:
        """
        Wait until Gemini finishes generating by polling until text stabilizes
        or an image generation pipeline is detected.
        Returns the completed response text or image response dictionary.
        """
        start_time = time.time()
        end_time = start_time + timeout

        logger.info(f"[{self.provider_name}] Waiting for response...")
        last_text = ""
        stable_count = 0

        # Cues in Gemini text that explicitly signal an image is being generated
        image_text_cues = [
            "creating your image",
            "generating your image",
            "working on that image",
            "working on your image",
            "creating an image",
            "generating an image",
            "i'm creating your image",
            "i am creating your image",
            "i'm generating your image",
            "drawing your image",
        ]

        while time.time() < end_time:
            current_text = self._try_get_response_text()

            # 1. Check if Gemini stated it is creating/generating an image
            if current_text:
                lower_text = current_text.lower()
                if any(cue in lower_text for cue in image_text_cues):
                    logger.info(f"[{self.provider_name}] Image generation acknowledged by Gemini: '{current_text}'")
                    output_name = self._sanitize_prompt_for_filename(prompt)
                    return self._wait_for_image_completion(
                        timeout=timeout,
                        output_name=output_name,
                        start_time=start_time,
                    )

            # 2. Check if DOM shows active image generation
            if self._is_generating_image_in_dom():
                logger.info(f"[{self.provider_name}] Active image generation detected in DOM.")
                output_name = self._sanitize_prompt_for_filename(prompt)
                return self._wait_for_image_completion(
                    timeout=timeout,
                    output_name=output_name,
                    start_time=start_time,
                )

            # 3. Check for standard text stream stabilization
            if current_text:
                if current_text == last_text and not self._is_generating():
                    stable_count += 1
                    # When text hasn't changed for ~1.6s and stop button is gone
                    if stable_count >= 2:
                        # Double-check if an image overlay appeared right at the end
                        if self._is_generating_image_in_dom():
                            output_name = self._sanitize_prompt_for_filename(prompt)
                            return self._wait_for_image_completion(
                                timeout=timeout,
                                output_name=output_name,
                                start_time=start_time,
                            )
                        logger.info(f"[{self.provider_name}] Generation complete ({len(current_text)} chars).")
                        return current_text
                else:
                    stable_count = 0
                    last_text = current_text

            time.sleep(0.8)

        if self._is_image_ready_in_dom():
            output_name = self._sanitize_prompt_for_filename(prompt)
            return self._extract_and_save_image(output_name=output_name, start_time=start_time)

        if last_text:
            return last_text
        raise TimeoutException(f"Gemini response timed out after {timeout} seconds.")

    def _extract_response_text(self) -> str:
        """Extract text from the latest response container."""
        text = self._try_get_response_text()
        if text:
            return text
        raise ValueError("Failed to locate response text in Gemini page.")

    def ask(self, prompt: str, timeout: int = 120) -> dict:
        """
        Send a prompt to Gemini in a fresh chat session and return the response.
        Automatically handles text responses and seamlessly detects & downloads generated images.
        """
        start_time = time.time()
        try:
            self.new_chat()

            if not self.check_auth():
                return self.capture_error(
                    error_code="SESSION_EXPIRED",
                    message="Login required for Gemini. Please log in to Google in the open Chrome browser.",
                    retryable=False,
                )

            logger.info(f"[{self.provider_name}] Submitting prompt...")
            self._submit_prompt(prompt)

            response = self._wait_for_completion(timeout=timeout, prompt=prompt)

            # If an image was generated, response is already a formatted dict
            if isinstance(response, dict):
                return response

            duration = time.time() - start_time

            return format_text_success(
                provider=self.provider_name,
                content=response,
                duration_seconds=duration,
            )
        except TimeoutException as e:
            logger.error(f"[{self.provider_name}] Timeout: {e}")
            return self.capture_error(
                error_code="TIMEOUT",
                message=f"Gemini did not complete response within {timeout}s.",
                retryable=True,
            )
        except ConnectionError as e:
            logger.error(f"[{self.provider_name}] Connection error: {e}")
            return format_error(
                provider=self.provider_name,
                error_code="BROWSER_NOT_RUNNING",
                message=str(e),
                retryable=False,
            )
        except Exception as e:
            logger.exception(f"[{self.provider_name}] Unexpected error: {e}")
            return self.capture_error(
                error_code="EXECUTION_ERROR",
                message=str(e),
                retryable=False,
            )

    def _focus_tab(self) -> None:
        """Switch to an existing tab for this provider if one exists."""
        try:
            for h in self.driver.window_handles:
                self.driver.switch_to.window(h)
                if "gemini.google.com" in self.driver.current_url.lower():
                    return
        except Exception:
            pass

    def check_auth(self) -> bool:
        """Check if user is logged in to Gemini."""
        self._focus_tab()
        current_url = self.driver.current_url.lower()
        if "accounts.google.com" in current_url:
            return False
        # Check for prominent sign in button
        try:
            sign_in_elements = self.driver.find_elements(
                By.XPATH, "//a[contains(@href, 'accounts.google.com') and (contains(text(), 'Sign in') or contains(text(), 'Sign In'))]"
            )
            if sign_in_elements and any(el.is_displayed() for el in sign_in_elements):
                return False
        except Exception:
            pass
        return True

    def new_chat(self) -> None:
        """
        Start a fresh chat on Gemini to prevent conversational history interference.
        Navigates to the base Gemini URL.
        """
        logger.info(f"[{self.provider_name}] Starting new chat at {self.base_url}...")
        self._focus_tab()
        self.driver.get(self.base_url)
        # Short wait to let the single page app initialize
        time.sleep(1.5)

    def _find_input_element(self, timeout: int = 15):
        """Find the Gemini prompt input element using candidate selectors."""
        # Dismiss any popup banners if present
        try:
            self.driver.execute_script("""
                document.querySelectorAll(
                    'button[aria-label*="close" i], button[aria-label*="dismiss" i], .close-button'
                ).forEach(function(b) { if (b.offsetWidth > 0) b.click(); });
            """)
        except Exception:
            pass

        end_time = time.time() + timeout
        while time.time() < end_time:
            for by, sel in self.INPUT_SELECTORS:
                try:
                    elements = self.driver.find_elements(by, sel)
                    for el in elements:
                        if el.is_displayed() and el.is_enabled():
                            return el
                except Exception:
                    continue
            time.sleep(0.5)
        raise NoSuchElementException("Could not locate Gemini prompt input area.")

    def _submit_prompt(self, prompt: str) -> None:
        """Type prompt into Gemini Quill input area and click send."""
        input_el = self._find_input_element()
        self.driver.execute_script("arguments[0].scrollIntoView(); arguments[0].focus(); arguments[0].click();", input_el)
        time.sleep(0.3)

        # Focus editor and insert text via execCommand to trigger Quill's text-change handler
        self.driver.execute_script("""
            var editor = arguments[0];
            editor.focus();
            document.execCommand('selectAll', false, null);
            document.execCommand('delete', false, null);
            document.execCommand('insertText', false, arguments[1]);
        """, input_el, prompt)

        time.sleep(0.6)

        # Wait up to 3.5s for the send button to finish animating and become clickable
        clicked = False
        end_wait = time.time() + 3.5
        while time.time() < end_wait:
            try:
                clicked = self.driver.execute_script("""
                    var btn = document.querySelector(
                        'button[aria-label*="Send message" i], button[aria-label*="Send" i], div[data-test-id="send-button-container"] button, .send-button button, [data-node-type="send_button"] button'
                    );
                    if (btn && btn.offsetWidth > 0 && !btn.disabled && btn.getAttribute('aria-disabled') !== 'true') {
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
            # Fallback: Dispatch Enter keydown/keyup events and send_keys
            logger.info(f"[{self.provider_name}] Send button not clicked, sending ENTER key")
            try:
                self.driver.execute_script("""
                    var el = arguments[0];
                    el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true }));
                    el.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true }));
                """, input_el)
            except Exception:
                pass
            input_el.send_keys(Keys.ENTER)

    def _is_generating(self) -> bool:
        """Check if Gemini is actively generating a response."""
        for by, sel in self.STOP_BUTTON_SELECTORS:
            try:
                elements = self.driver.find_elements(by, sel)
                for el in elements:
                    if el.is_displayed():
                        return True
            except Exception:
                continue
        return False

    def generate_image(self, prompt: str, output_name: str = "image", timeout: int = 180) -> dict:
        """
        Request Gemini to generate an image, wait for generation with periodic status,
        and download/save the full image locally.
        """
        start_time = time.time()
        try:
            self.new_chat()

            if not self.check_auth():
                return self.capture_error(
                    error_code="SESSION_EXPIRED",
                    message="Login required for Gemini. Please log in to Google in the open Chrome browser.",
                    retryable=False,
                )

            # Ensure prompt specifies image generation
            full_prompt = prompt if any(k in prompt.lower() for k in ("image", "generate", "draw", "photo", "picture", "illustration")) else f"Generate an image of: {prompt}"
            logger.info(f"[{self.provider_name}] Requesting image: '{full_prompt}'...")
            self._submit_prompt(full_prompt)

            # Use sanitize slug if output_name is default
            if output_name == "image":
                output_name = self._sanitize_prompt_for_filename(prompt)

            return self._wait_for_image_completion(
                timeout=timeout,
                output_name=output_name,
                start_time=start_time,
            )

        except TimeoutException as e:
            return self.capture_error(
                error_code="TIMEOUT",
                message=f"Gemini image generation timed out: {e}",
                retryable=True,
            )
        except ConnectionError as e:
            return format_error(
                provider=self.provider_name,
                error_code="BROWSER_NOT_RUNNING",
                message=str(e),
                retryable=False,
            )
        except Exception as e:
            logger.exception(f"[{self.provider_name}] Error generating image: {e}")
            return self.capture_error(
                error_code="IMAGE_GENERATION_FAILED",
                message=str(e),
                retryable=False,
            )
