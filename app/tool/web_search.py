import asyncio
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field, model_validator
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import config
from app.logger import logger
from app.tool.base import BaseTool, ToolResult
from app.tool.search import (
    BaiduSearchEngine,
    BingSearchEngine,
    DuckDuckGoSearchEngine,
    GoogleSearchEngine,
    WebSearchEngine,
    YahooSearchEngine,
)
from app.tool.search.base import SearchItem
from app.llm import LLM
from app.prompt.extract_content import EXTRACT_CONTENT_SYSTEM_PROMPT


class SearchResult(BaseModel):
    """Represents a single search result returned by a search engine."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    position: int = Field(description="Position in search results")
    url: str = Field(description="URL of the search result")
    title: str = Field(default="", description="Title of the search result")
    description: str = Field(
        default="", description="Description or snippet of the search result"
    )
    source: str = Field(description="The search engine that provided this result")
    raw_content: Optional[str] = Field(
        default=None, description="Raw content from the search result page if available"
    )

    def __str__(self) -> str:
        """String representation of a search result."""
        return f"{self.title} ({self.url})"


class SearchMetadata(BaseModel):
    """Metadata about the search operation."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    total_results: int = Field(description="Total number of results found")
    language: str = Field(description="Language code used for the search")
    country: str = Field(description="Country code used for the search")


class SearchResponse(ToolResult):
    """Structured response from the web search tool, inheriting ToolResult."""

    query: str = Field(description="The search query that was executed")
    results: List[SearchResult] = Field(
        default_factory=list, description="List of search results"
    )
    metadata: Optional[SearchMetadata] = Field(
        default=None, description="Metadata about the search"
    )
    extracted_content: Optional[str] = Field(
        default=None, description="Content extracted by LLM based on the goal"
    )
    snippet: Optional[str] = Field(
        default=None,
        description="Raw content snippet from first fetched result when no goal provided",
    )

    @model_validator(mode="after")
    def populate_output(self) -> "SearchResponse":
        """Populate output as structured dict to match desired schema."""
        if self.error:
            return self

        # Build the output object according to the requested shape
        search_result = [
            {
                "position": r.position,
                "title": (r.title or "").strip(),
                "url": r.url,
                "description": (r.description or "").strip(),
            }
            for r in self.results
        ]

        self.output = {
            "search_result": search_result,
            "extracted_content": self.extracted_content or "",
        }
        if self.snippet and self.snippet.strip():
            self.output["snippet"] = self.snippet
        return self


class WebContentFetcher:
    """Utility class for fetching web content."""

    @staticmethod
    async def fetch_content(url: str, timeout: int = 10) -> Optional[str]:
        """
        Fetch and extract structured content from a webpage based on headings.

        Args:
            url: The URL to fetch content from
            timeout: Request timeout in seconds

        Returns:
            Structured text content organized by headings or None if fetching fails
        """
        # Sanitize incoming URL to avoid issues with stray quotes/backticks/whitespace
        url = (url or "").strip().strip('`"\'')
        if not url:
            return None
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

        try:
            # Use asyncio to run requests in a thread pool
            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: requests.get(url, headers=headers, timeout=timeout)
            )

            if response.status_code != 200:
                logger.warning(
                    f"Failed to fetch content from {url}: HTTP {response.status_code}"
                )
                return None

            # Parse HTML with BeautifulSoup
            soup = BeautifulSoup(response.text, "html.parser")

            # Remove script and style elements
            for script in soup(["script", "style", "header", "footer", "nav"]):
                script.extract()

            # Extract structured content based on headings
            heading_tags = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']
            title = soup.title.string if soup.title else None

            structured_content = []

            # Add title if available
            if title:
                structured_content.append(f"Title: {title.strip()}")
                structured_content.append("\n")

            # Process each heading and its content
            for heading in soup.find_all(heading_tags):
                heading_text = heading.get_text(strip=True)
                if not heading_text:
                    continue

                structured_content.append(f"{heading.name.upper()}: {heading_text}")

                content = []
                next_element = heading.find_next_sibling()

                while next_element and next_element.name not in heading_tags:
                    if next_element.name in ['p', 'ul', 'ol', 'pre', 'code']:
                        text_content = next_element.get_text(separator='\n\n', strip=True)
                        if text_content:
                            content.append(text_content)
                    elif next_element.name == 'table':
                        content.append(str(next_element))
                    next_element = next_element.find_next_sibling()

                if content:
                    full_content = '\n'.join(content)
                    structured_content.append(full_content)

                structured_content.append("\n")

            # If no headings found, fallback to simple text extraction
            if len(structured_content) <= 2:  # Only title and newline
                text = soup.get_text(separator="\n", strip=True)
                text = " ".join(text.split())
                return text[:10000] if text else None

            # Join all structured content and limit size
            final_content = '\n'.join(structured_content)
            return final_content[:10000] if final_content else None

        except Exception as e:
            logger.warning(f"Error fetching content from {url}: {e}")
            return None


class WebSearch(BaseTool):
    """Search the web for information using various search engines."""

    name: str = "web_search"
    description: str = """Search the web for real-time information about any topic.
    This tool returns comprehensive search results with relevant information, URLs, titles, and descriptions.
    If the primary search engine fails, it automatically falls back to alternative engines."""
    parameters: dict = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "(required) The search query to submit to the search engine.",
            },
            "num_results": {
                "type": "integer",
                "description": "(optional) The number of search results to return. Default is 3, maximum is 3.",
                "default": 3,
                "minimum": 1,
                "maximum": 3,
            },
            "lang": {
                "type": "string",
                "description": "(optional) Language code for search results (default: en).",
                "default": "en",
            },
            "country": {
                "type": "string",
                "description": "(optional) Country code for search results (default: us).",
                "default": "us",
            },
            "extract_content": {
                "type": "boolean",
                "description": "Whether to extract content from result pages (sequential with early-stop when goal present). Default is true.",
                "default": True,
            },
            "goal": {
                "type": "string",
                "description": "(optional) Extraction goal for 'extract_content'",
            }
        },
        "required": ["query", "goal"],
    }
    _search_engine: dict[str, WebSearchEngine] = {
        "google": GoogleSearchEngine(),
        "yahoo": YahooSearchEngine(),
        "baidu": BaiduSearchEngine(),
        "duckduckgo": DuckDuckGoSearchEngine(),
        "bing": BingSearchEngine(),
    }
    content_fetcher: WebContentFetcher = WebContentFetcher()
    llm: Optional[LLM] = Field(default_factory=LLM, exclude=True)

    async def execute(
        self,
        query: str,
        num_results: int = 3,
        lang: Optional[str] = None,
        country: Optional[str] = None,
        # Backward-compatible flags: prefer extract_content if provided
        extract_content: Optional[bool] = None,
        goal: Optional[str] = None,
        fetch_content: Optional[bool] = None,
    ) -> SearchResponse:
        """
        Execute a Web search and return detailed search results.

        Args:
            query: The search query to submit to the search engine
            num_results: The number of search results to return (default: 3, max: 3)
            lang: Language code for search results (default from config)
            country: Country code for search results (default from config)
            extract_content: Whether to extract content from result pages
            goal: Goal text to guide LLM extraction
            fetch_content: Deprecated; maintained for compatibility. Use extract_content instead.

        Returns:
            A structured response containing search results and metadata
        """
        # Determine effective extract flag
        if extract_content is None and fetch_content is None:
            effective_extract = True
        else:
            effective_extract = extract_content if extract_content is not None else bool(fetch_content)

        # Limit num_results to maximum of 3
        num_results = min(num_results, 3)

        # Get settings from config
        retry_delay = (
            getattr(config.search_config, "retry_delay", 60)
            if config.search_config
            else 60
        )
        max_retries = (
            getattr(config.search_config, "max_retries", 3)
            if config.search_config
            else 3
        )

        # Use config values for lang and country if not specified
        if lang is None:
            lang = (
                getattr(config.search_config, "lang", "en")
                if config.search_config
                else "en"
            )

        if country is None:
            country = (
                getattr(config.search_config, "country", "us")
                if config.search_config
                else "us"
            )

        search_params = {"lang": lang, "country": country}
        # Initialize snippet holder (only used when goal is None)
        snippet: Optional[str] = None

        # Try searching with retries when all engines fail
        for retry_count in range(max_retries + 1):
            results = await self._try_all_engines(query, num_results, search_params)

            if results:
                extracted_text: Optional[str] = None

                # Goal-driven sequential fetch with early stop
                if effective_extract and goal:
                    for i, result in enumerate(results):
                        content = await self.content_fetcher.fetch_content(result.url)
                        if content:
                            # Keep raw content for the matched result
                            results[i].raw_content = content
                            # Use LLM to extract according to goal
                            try:
                                extracted_text = await self._extract_with_llm(
                                    page_content=content, goal=goal, url=result.url
                                )
                            except Exception as e:
                                logger.warning(f"LLM extraction failed for {result.url}: {e}")
                                extracted_text = None

                            # Early stop: break immediately after first successful fetch
                            break
                        # If no content, try next result
                    # end for
                elif effective_extract and not goal:
                    # Sequential fetch with early stop at first content found (no LLM)
                    for i, result in enumerate(results):
                        content = await self.content_fetcher.fetch_content(result.url)
                        if content:
                            results[i].raw_content = content
                            # build snippet from normalized whitespace
                            try:
                                normalized = " ".join(content.split())
                                snippet = (normalized[:10000]).strip() if normalized else None
                            except Exception:
                                snippet = None
                            break
                # else: do not fetch content

                # Return a successful structured response
                return SearchResponse(
                    status="success",
                    query=query,
                    results=results,
                    metadata=SearchMetadata(
                        total_results=len(results),
                        language=lang,
                        country=country,
                    ),
                    extracted_content=extracted_text if goal else None,
                    snippet=snippet,
                )

            if retry_count < max_retries:
                # All engines failed, wait and retry
                logger.warning(
                    f"All search engines failed. Waiting {retry_delay} seconds before retry {retry_count + 1}/{max_retries}..."
                )
                await asyncio.sleep(retry_delay)
            else:
                logger.error(
                    f"All search engines failed after {max_retries} retries. Giving up."
                )

        # Return an error response
        return SearchResponse(
            query=query,
            error="All search engines failed to return results after multiple retries.",
            results=[],
        )

    async def _try_all_engines(
        self, query: str, num_results: int, search_params: Dict[str, Any]
    ) -> List[SearchResult]:
        """Try all search engines in the configured order."""
        engine_order = self._get_engine_order()
        failed_engines = []

        for engine_name in engine_order:
            engine = self._search_engine[engine_name]
            logger.info(f"🔎 Attempting search with {engine_name.capitalize()}...")
            search_items = await self._perform_search_with_engine(
                engine, query, num_results, search_params
            )

            if not search_items:
                continue

            if failed_engines:
                logger.info(
                    f"Search successful with {engine_name.capitalize()} after trying: {', '.join(failed_engines)}"
                )

            # Transform search items into structured results and limit to 3 results
            limited_items = search_items[:3]  # Ensure maximum 3 results
            return [
                SearchResult(
                    position=i + 1,
                    url=(item.url or "").strip().strip('`"\''),
                    title=item.title
                    or f"Result {i+1}",  # Ensure we always have a title
                    description=item.description or "",
                    source=engine_name,
                )
                for i, item in enumerate(limited_items)
            ]

        if failed_engines:
            logger.error(f"All search engines failed: {', '.join(failed_engines)}")
        return []

    async def _fetch_content_for_results(
        self, results: List[SearchResult]
    ) -> List[SearchResult]:
        """Fetch and add web content to search results."""
        if not results:
            return []

        # Create tasks for each result
        tasks = [self._fetch_single_result_content(result) for result in results]

        # Type annotation to help type checker
        fetched_results = await asyncio.gather(*tasks)

        # Explicit validation of return type
        return [
            (
                result
                if isinstance(result, SearchResult)
                else SearchResult(**result.dict())
            )
            for result in fetched_results
        ]

    async def _fetch_single_result_content(self, result: SearchResult) -> SearchResult:
        """Fetch content for a single search result."""
        if result.url:
            content = await self.content_fetcher.fetch_content(result.url)
            if content:
                result.raw_content = content
        return result

    def _get_engine_order(self) -> List[str]:
        """Determines the order in which to try search engines."""
        preferred = (
            getattr(config.search_config, "engine", "yahoo").lower()
            if config.search_config
            else "google"
        )
        fallbacks = (
            [engine.lower() for engine in config.search_config.fallback_engines]
            if config.search_config
            and hasattr(config.search_config, "fallback_engines")
            else []
        )

        # Start with preferred engine, then fallbacks, then remaining engines
        engine_order = [preferred] if preferred in self._search_engine else []
        engine_order.extend(
            [
                fb
                for fb in fallbacks
                if fb in self._search_engine and fb not in engine_order
            ]
        )
        engine_order.extend([e for e in self._search_engine if e not in engine_order])

        return engine_order

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10)
    )
    async def _perform_search_with_engine(
        self,
        engine: WebSearchEngine,
        query: str,
        num_results: int,
        search_params: Dict[str, Any],
    ) -> List[SearchItem]:
        """Execute search with the given engine and parameters."""
        return await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: list(
                engine.perform_search(
                    query,
                    num_results=num_results,
                    lang=search_params.get("lang"),
                    country=search_params.get("country"),
                )
            ),
        )

    async def _extract_with_llm(self, page_content: str, goal: str, url: Optional[str] = None) -> Optional[str]:
        """Use LLM to extract content from page_content based on the goal."""
        try:
            system_msg = {"role": "system", "content": EXTRACT_CONTENT_SYSTEM_PROMPT}
            user_msg = {
                "role": "user",
                "content": (
                    "**RAW TEXT:**\n"
                    f"{page_content}"
                    "**EXTRACTION REQUEST:** (Optional)\n"
                    f"{goal or 'No specific request'}\n"
                    f"URL:\n{url or ''}\n\n"
                ),
            }

            # Define a simple tool schema to force JSON extraction
            extraction_tool = {
                "type": "function",
                "function": {
                    "name": "return_extracted_content",
                    "description": "Return the extracted content as a single string.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "extracted_content": {
                                "type": "string",
                                "description": "The content extracted from the page according to the goal",
                            }
                        },
                        "required": ["extracted_content"],
                    },
                },
            }

            response = await self.llm.ask_tool(
                messages=[user_msg],
                system_msgs=[system_msg],
                tools=[extraction_tool],
                tool_choice="required",
                temperature=0.2,
                timeout=180,
            )

            if response and getattr(response, "tool_calls", None):
                try:
                    import json

                    args = json.loads(response.tool_calls[0].function.arguments)
                    extracted = args.get("extracted_content")
                    if isinstance(extracted, str) and extracted.strip():
                        return extracted.strip()
                except Exception:
                    return None
            # If no tool call, try to use content of message
            if response and getattr(response, "content", None):
                text = response.content.strip()
                return text or None
        except Exception as e:
            logger.warning(f"LLM extraction exception: {e}")
            return None


if __name__ == "__main__":
    web_search = WebSearch()
    search_response = asyncio.run(
        web_search.execute(
            query="Python programming", extract_content=True, num_results=1, goal="Ringkas isi halaman"
        )
    )
    print(search_response.output)
