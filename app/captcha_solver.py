import asyncio
import logging
import time
from typing import Optional

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from app.config import settings

logger = logging.getLogger("browser_mcp")


class VisionCaptchaSolver:
    """
    Autonomous CAPTCHA and Cloudflare challenge solver using browser-use
    powered by an Ollama Vision model (e.g. gemma4:31b-cloud).
    
    Only activates on-demand when a CAPTCHA or security challenge is detected,
    keeping regular DOM automation free, lightweight, and ultra-fast.
    """

    @staticmethod
    def is_captcha_present(driver: WebDriver) -> bool:
        """Check whether the active page is showing a CAPTCHA or security challenge."""
        try:
            # 1. Check title & page text for Cloudflare / Turnstile signatures
            title = (driver.title or "").lower()
            if any(kw in title for kw in ["just a moment", "attention required", "security check", "cloudflare"]):
                return True

            # 2. Check for Cloudflare Turnstile iframes and containers
            turnstile_selectors = [
                "#cf-turnstile",
                ".cf-turnstile",
                "iframe[src*='challenges.cloudflare.com']",
                "iframe[src*='turnstile']",
                "div#challenge-running",
                "div#challenge-stage",
                "div#turnstile-wrapper",
            ]
            for selector in turnstile_selectors:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                for el in elements:
                    if el.is_displayed() and el.size.get("height", 0) > 0:
                        return True

            # 3. Check for Google reCAPTCHA or hCaptcha
            recaptcha_selectors = [
                "iframe[src*='google.com/recaptcha']",
                "iframe[title*='reCAPTCHA']",
                "iframe[src*='hcaptcha.com']",
                "div.g-recaptcha",
                "div.h-captcha",
            ]
            for selector in recaptcha_selectors:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                for el in elements:
                    if el.is_displayed() and el.size.get("height", 0) > 0:
                        return True

            # 4. Check for 'Verify you are human' visible text
            page_text = driver.execute_script("return document.body ? document.body.innerText.toLowerCase() : '';")
            if "verify you are human" in page_text or "checking if the site connection is secure" in page_text:
                return True

        except Exception as e:
            logger.debug(f"Error checking for CAPTCHA: {e}")

        return False

    @staticmethod
    async def solve_with_browser_use(
        cdp_url: Optional[str] = None,
        max_steps: int = 5,
        timeout: int = 60,
    ) -> bool:
        """
        Connect browser-use to the running Chrome instance over CDP
        and use the Ollama Vision model to autonomously solve the challenge.
        """
        cdp_endpoint = cdp_url or f"http://{settings.debugger_address}"
        logger.info(
            f"[VisionCaptchaSolver] Connecting browser-use to Chrome via CDP ({cdp_endpoint}) "
            f"using Ollama vision model '{settings.ollama_vision_model}' at {settings.ollama_base_url}..."
        )

        try:
            from browser_use import Agent, Browser
            from browser_use.llm.ollama.chat import ChatOllama
        except ImportError as e:
            logger.error(f"[VisionCaptchaSolver] Missing dependency for browser-use: {e}")
            return False

        try:
            # Initialize Ollama Vision LLM
            llm = ChatOllama(
                host=settings.ollama_base_url,
                model=settings.ollama_vision_model,
            )

            # Connect browser-use to existing Chrome session over CDP
            browser = Browser(cdp_url=cdp_endpoint)

            task_prompt = (
                "You are a CAPTCHA and security challenge solver. "
                "Examine the current browser tab. "
                "Locate the 'Verify you are human' checkbox, Cloudflare Turnstile challenge, "
                "or security verification puzzle. "
                "Click the verification checkbox or solve the puzzle. "
                "Once the challenge is passed and the main application content is visible, complete the task immediately."
            )

            agent = Agent(
                task=task_prompt,
                llm=llm,
                browser=browser,
                use_vision=True,
                max_actions_per_step=2,
            )

            logger.info("[VisionCaptchaSolver] Running browser-use autonomous solving agent...")
            await asyncio.wait_for(agent.run(max_steps=max_steps), timeout=timeout)
            logger.info("[VisionCaptchaSolver] browser-use agent finished task.")
            return True

        except asyncio.TimeoutError:
            logger.warning(f"[VisionCaptchaSolver] Solving timed out after {timeout}s.")
            return False
        except Exception as e:
            err_str = str(e)
            if "Connection refused" in err_str or "Failed to connect" in err_str or "11434" in err_str:
                logger.warning(
                    f"[VisionCaptchaSolver] Could not reach Ollama at {settings.ollama_base_url}. "
                    f"Ensure Ollama is running (`ollama serve`). Error: {e}"
                )
            else:
                logger.error(f"[VisionCaptchaSolver] browser-use failed: {e}")
            return False

    @classmethod
    def solve_if_needed(cls, driver: WebDriver, timeout: int = 45) -> bool:
        """
        Synchronous helper called by provider modules.
        If a challenge is detected:
          1. Attempts quick direct DOM click on Turnstile / Cloudflare buttons.
          2. If still present and enable_vision_captcha_solver is True, triggers browser-use with Ollama Vision.
          3. Waits for challenge clearance.
        """
        if not cls.is_captcha_present(driver):
            return True

        logger.warning("[VisionCaptchaSolver] Security challenge / CAPTCHA detected on page!")

        # Step 1: Quick direct click attempt on Cloudflare Turnstile if accessible
        try:
            clicked = driver.execute_script("""
                // Try Turnstile iframe shadow DOM or container
                var cf = document.querySelector('#cf-turnstile, .cf-turnstile');
                if (cf) {
                    var iframes = cf.querySelectorAll('iframe');
                    for (var i = 0; i < iframes.length; i++) {
                        var rect = iframes[i].getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0) {
                            iframes[i].click();
                            return true;
                        }
                    }
                }
                // Try any verify button
                var btns = Array.from(document.querySelectorAll('button, input[type="button"], input[type="submit"]'));
                var verifyBtn = btns.find(b => b.innerText && b.innerText.toLowerCase().includes('verify'));
                if (verifyBtn) {
                    verifyBtn.click();
                    return true;
                }
                return false;
            """)
            if clicked:
                logger.info("[VisionCaptchaSolver] Dispatched quick DOM click to verification element.")
                time.sleep(3.0)
                if not cls.is_captcha_present(driver):
                    logger.info("[VisionCaptchaSolver] Challenge resolved via fast DOM click.")
                    return True
        except Exception as e:
            logger.debug(f"[VisionCaptchaSolver] Fast click attempt skipped: {e}")

        # Step 2: Escalate to browser-use with Ollama Vision model
        if settings.enable_vision_captcha_solver:
            logger.info(
                f"[VisionCaptchaSolver] Escalating to browser-use with Ollama Vision ({settings.ollama_vision_model})..."
            )
            try:
                # Run async solver within existing or new event loop
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # If called from an async thread where loop is already running
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor() as executor:
                            future = executor.submit(
                                lambda: asyncio.run(cls.solve_with_browser_use(timeout=timeout))
                            )
                            future.result(timeout=timeout + 5)
                    else:
                        loop.run_until_complete(cls.solve_with_browser_use(timeout=timeout))
                except RuntimeError:
                    asyncio.run(cls.solve_with_browser_use(timeout=timeout))

            except Exception as e:
                logger.error(f"[VisionCaptchaSolver] Vision solving escalation error: {e}")

        # Step 3: Wait for page to clear
        start = time.time()
        while time.time() - start < 10:
            if not cls.is_captcha_present(driver):
                logger.info("[VisionCaptchaSolver] Security challenge cleared successfully.")
                time.sleep(1.0)
                return True
            time.sleep(1.0)

        logger.warning("[VisionCaptchaSolver] Security challenge could not be fully cleared.")
        return False
