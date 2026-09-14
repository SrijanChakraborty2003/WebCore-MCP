import time
import urllib.parse
from typing import Optional, List, Dict, Any

from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from app.browser import logger, DEFAULT_USER_AGENT
from app.config import settings
from app.parsers import format_text_success, format_error
from app.providers.base import BrowserProvider


class GoogleSearchBrowser(BrowserProvider):
    provider_name: str = "google"
    base_url: str = "https://www.google.com/"

    def _focus_tab(self) -> None:
        """Switch to an existing Google tab if one exists."""
        try:
            for h in self.driver.window_handles:
                self.driver.switch_to.window(h)
                if "google.com" in self.driver.current_url.lower():
                    return
        except Exception:
            pass

    def _dismiss_banners(self) -> None:
        """Dismiss Google cookie consent and sign-in prompts if present."""
        try:
            self.driver.execute_script("""
                // Cookie consent buttons (e.g. 'Accept all', 'I agree', 'Reject all')
                var buttons = document.querySelectorAll('button, div[role="button"]');
                for (var b of buttons) {
                    var txt = (b.innerText || '').trim().toLowerCase();
                    if (txt === 'accept all' || txt === 'i agree' || txt === 'agree' || txt === 'read more') {
                        b.click();
                        break;
                    }
                }
                // Dismiss 'Stay signed out' iframe or popup if present
                var staySignedOut = document.querySelector('iframe[name*="callout" i]');
                if (staySignedOut && staySignedOut.offsetWidth > 0) {
                    var closeBtn = document.querySelector('button[aria-label*="close" i], button[aria-label*="dismiss" i]');
                    if (closeBtn) closeBtn.click();
                }
            """)
        except Exception:
            pass

    def new_chat(self) -> None:
        """Navigate to Google homepage."""
        self._focus_tab()
        try:
            self.driver.execute_cdp_cmd(
                "Network.setUserAgentOverride",
                {"userAgent": DEFAULT_USER_AGENT}
            )
        except Exception:
            pass
        self.driver.get(self.base_url)
        time.sleep(1.0)
        self._dismiss_banners()

    def ask(self, prompt: str, timeout: int = 60) -> dict:
        """Alias for search() to satisfy BrowserProvider interface."""
        return self.search(query=prompt, timeout=timeout)

    def search(self, query: str, num_results: int = 10, timeout: int = 60) -> dict:
        """
        Execute a live Google Search and extract organic results, featured snippets,
        and AI Overviews.
        
        Args:
            query: The search term to query on Google.
            num_results: Max number of organic search results to return (default: 10).
            timeout: Maximum seconds to wait for page load (default: 60).
        """
        start_time = time.time()
        if not query or not query.strip():
            return format_error(self.provider_name, "INVALID_QUERY", "Search query cannot be empty.")

        try:
            self._focus_tab()
            try:
                self.driver.execute_cdp_cmd(
                    "Network.setUserAgentOverride",
                    {"userAgent": DEFAULT_USER_AGENT}
                )
            except Exception:
                pass

            encoded_query = urllib.parse.quote_plus(query.strip())
            search_url = f"https://www.google.com/search?q={encoded_query}&hl=en"
            logger.info(f"[{self.provider_name}] Navigating to Google Search: {search_url}...")
            self.driver.get(search_url)

            # Wait for search results container to appear
            end_time = time.time() + timeout
            results_loaded = False
            while time.time() < end_time:
                self._dismiss_banners()
                has_results = self.driver.execute_script("""
                    return !!document.querySelector('#search, div.g, div.MjjYud, #rso');
                """)
                if has_results:
                    results_loaded = True
                    break
                time.sleep(0.5)

            if not results_loaded:
                raise TimeoutException("Google Search results page timed out.")

            # Wait briefly for dynamic AI Overview / rich snippets to stabilize
            time.sleep(1.5)

            # Extract structured search data via JavaScript
            extracted_data = self.driver.execute_script("""
                var data = {
                    ai_overview: null,
                    knowledge_panel: null,
                    featured_snippet: null,
                    organic_results: []
                };

                // 1. Check for AI Overview
                var allDivs = document.querySelectorAll('div, span');
                for (var d of allDivs) {
                    if ((d.innerText || '').trim() === 'AI Overview') {
                        var container = d.closest('div.MjjYud, div[data-attrid], div.g') || d.parentElement.parentElement;
                        if (container) {
                            var overviewText = (container.innerText || '').trim();
                            overviewText = overviewText.replace(/^AI Overview\\s*/i, '').trim();
                            if (overviewText.length > 20) {
                                data.ai_overview = overviewText;
                                break;
                            }
                        }
                    }
                }

                // 2. Check for Knowledge Panel
                var kp = document.querySelector('div.kp-wholepage, div[data-attrid*="kc:" i]');
                if (kp) {
                    var kpText = (kp.innerText || '').trim();
                    if (kpText.length > 30) {
                        data.knowledge_panel = kpText.slice(0, 1000);
                    }
                }

                // 3. Extract Organic Results
                var elements = document.querySelectorAll('div.g, div.MjjYud');
                var seenUrls = new Set();

                for (var el of elements) {
                    var titleEl = el.querySelector('h3');
                    var linkEl = el.querySelector('a[href^="http"]');
                    var snippetEl = el.querySelector('div[style*="-webkit-line-clamp"], div.VwiC3b, div[data-sncf], div.yXReg, span.aCOpRe');

                    if (titleEl && linkEl) {
                        var title = (titleEl.innerText || '').trim();
                        var url = linkEl.getAttribute('href') || '';
                        var snippet = snippetEl ? (snippetEl.innerText || '').trim() : '';

                        if (title && url && !url.includes('google.com/search') && !seenUrls.has(url)) {
                            seenUrls.add(url);
                            data.organic_results.push({
                                title: title,
                                url: url,
                                snippet: snippet
                            });
                        }
                    }
                }

                return data;
            """)

            ai_overview = extracted_data.get("ai_overview")
            organic_results = extracted_data.get("organic_results", [])[:num_results]
            knowledge_panel = extracted_data.get("knowledge_panel")

            # Build clean, human-readable Markdown text response
            markdown_lines = [f"### Google Search Results: \"{query.strip()}\"\n"]

            if ai_overview:
                markdown_lines.append(f"#### 🤖 Google AI Overview\n{ai_overview}\n\n---\n")

            if knowledge_panel and not ai_overview:
                markdown_lines.append(f"#### ℹ️ Knowledge Panel\n{knowledge_panel}\n\n---\n")

            if organic_results:
                markdown_lines.append("#### 🌐 Top Results\n")
                for i, r in enumerate(organic_results, 1):
                    markdown_lines.append(f"{i}. **[{r['title']}]({r['url']})**")
                    if r.get("snippet"):
                        markdown_lines.append(f"   {r['snippet']}\n")
                    else:
                        markdown_lines.append("\n")
            else:
                markdown_lines.append("No organic results found.")

            content = "\n".join(markdown_lines).strip()
            duration = round(time.time() - start_time, 2)

            return format_text_success(
                provider=self.provider_name,
                content=content,
                duration_seconds=duration,
                extra={
                    "query": query.strip(),
                    "total_results": len(organic_results),
                    "has_ai_overview": bool(ai_overview),
                    "results": organic_results,
                },
            )

        except TimeoutException as e:
            return self.capture_error("TIMEOUT", f"Google Search timed out: {e}", retryable=True)
        except Exception as e:
            logger.exception(f"[{self.provider_name}] Error: {e}")
            return self.capture_error("EXECUTION_ERROR", str(e), retryable=False)
