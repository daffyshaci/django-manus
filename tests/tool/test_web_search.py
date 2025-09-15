import asyncio
from typing import List, Optional

import pytest

from app.tool.web_search import WebSearch, SearchResponse
from app.tool.search.base import SearchItem


@pytest.mark.asyncio
async def test_web_search_without_goal_returns_snippet_and_no_extracted_content(monkeypatch):
    """
    When goal is None and extract_content=True:
    - Should fetch content sequentially and stop at first successful fetch
    - Should populate snippet in output
    - Should NOT populate extracted_content (empty string in output)
    """
    web_search = WebSearch()

    # Prepare mock search results (SearchItem -> then transformed internally)
    mock_items: List[SearchItem] = [
        SearchItem(title="First", url="https://example.com/1", description="desc1"),
        SearchItem(title="Second", url="https://example.com/2", description="desc2"),
    ]

    async def mock_perform_search_with_engine(engine, query, num_results, search_params):
        return mock_items

    # Counter to ensure early stop after first content
    call_counter = {"count": 0}

    class FakeFetcher:
        async def fetch_content(self, url: str, timeout: int = 10):
            call_counter["count"] += 1
            # Always return content for the first URL; shouldn't be called for the second due to early stop
            return f"Content from {url}"

    # Patch internals
    monkeypatch.setattr(WebSearch, "_perform_search_with_engine", staticmethod(mock_perform_search_with_engine))
    web_search.content_fetcher = FakeFetcher()  # instance-level patch

    # Execute without goal (so snippet path is used)
    resp: SearchResponse = await web_search.execute(
        query="unit test query", extract_content=True, num_results=2, goal=None
    )

    assert resp.status == "success"
    # Ensure only first fetch executed due to early stop
    assert call_counter["count"] == 1

    # Output assertions
    assert isinstance(resp.output, dict)
    assert "search_result" in resp.output
    assert "extracted_content" in resp.output
    assert resp.output.get("extracted_content") == ""  # no goal => empty string
    assert "snippet" in resp.output  # snippet must be present

    # Snippet should be built from first result content
    expected_snippet = " ".join(f"Content from https://example.com/1".split())[:800].strip()
    assert resp.output["snippet"] == expected_snippet


@pytest.mark.asyncio
async def test_web_search_with_goal_returns_extracted_content_and_no_snippet(monkeypatch):
    """
    When goal is provided:
    - Should fetch content sequentially and then run LLM extraction
    - Should populate extracted_content in output
    - Should NOT include snippet in output
    """
    web_search = WebSearch()

    mock_items: List[SearchItem] = [
        SearchItem(title="Only", url="https://example.com/only", description="desc"),
    ]

    async def mock_perform_search_with_engine(engine, query, num_results, search_params):
        return mock_items

    class FakeFetcher:
        async def fetch_content(self, url: str, timeout: int = 10):
            return "Page content for extraction"

    async def mock_extract_with_llm(page_content: str, goal: str, url: Optional[str] = None):
        assert page_content == "Page content for extraction"
        assert goal == "Summarize this"
        return "Extracted summary"

    # Patch internals
    monkeypatch.setattr(WebSearch, "_perform_search_with_engine", staticmethod(mock_perform_search_with_engine))
    web_search.content_fetcher = FakeFetcher()
    monkeypatch.setattr(WebSearch, "_extract_with_llm", staticmethod(mock_extract_with_llm))

    resp: SearchResponse = await web_search.execute(
        query="unit test query", extract_content=True, num_results=1, goal="Summarize this"
    )

    assert resp.status == "success"
    assert isinstance(resp.output, dict)
    assert "search_result" in resp.output
    assert "extracted_content" in resp.output
    assert resp.output["extracted_content"] == "Extracted summary"
    # Ensure snippet is not present when goal is provided
    assert "snippet" not in resp.output