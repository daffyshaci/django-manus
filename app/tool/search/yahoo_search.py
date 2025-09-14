from typing import List

from app.tool.search.base import SearchItem, WebSearchEngine
import urllib
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

def _format_url(url):
    parsed_url = urlparse(url)
    path = parsed_url.path

    start_index = path.find("RU=")
    end_index = path.find("/", start_index)

    ru_value = path[start_index+3:end_index]
    decoded_ru_value = urllib.parse.unquote(ru_value)

    return decoded_ru_value

def parsing_bs(html):
    try:
        results = {}
        soup = BeautifulSoup(html, 'html.parser')
        new_list = []

        # Try multiple selectors for Yahoo search results
        web_results = []

        # Primary selector - modern Yahoo search results
        search_center = soup.find('ol', class_="searchCenterMiddle")
        if search_center:
            web_results = search_center.find_all('li')

        # Fallback selectors for different Yahoo layouts
        if not web_results:
            # Try alternative selectors
            selectors = [
                'div[data-testid="result"]',
                'div.dd.algo',
                'div.compTitle',
                'div.result',
                'li.dd',
                'div.web-result'
            ]

            for selector in selectors:
                web_results = soup.select(selector)
                if web_results:
                    break

        # If still no results, try finding any links with titles
        if not web_results:
            web_results = soup.find_all('div', class_=lambda x: x and ('result' in x or 'dd' in x))

        for web in web_results:
            data = {}
            title = None
            link = None
            snippet = None

            # Extract title and link
            # Try different title selectors
            title_selectors = [
                'h3 a',
                'a[aria-label]',
                '.title a',
                '.compTitle a',
                'h4 a',
                'h2 a'
            ]

            for selector in title_selectors:
                title_elem = web.select_one(selector)
                if title_elem:
                    # Get title from aria-label or text content
                    if title_elem.get('aria-label'):
                        title = title_elem['aria-label']
                    else:
                        title = title_elem.get_text(strip=True)

                    # Get link
                    link = title_elem.get('href')
                    if link:
                        link = _format_url(link)
                    break

            # If no title found, try alternative methods
            if not title:
                # Try finding any anchor with meaningful text
                anchors = web.find_all('a', href=True)
                for anchor in anchors:
                    text = anchor.get_text(strip=True)
                    if text and len(text) > 10:  # Meaningful title length
                        title = text
                        link = _format_url(anchor['href'])
                        break

            # Extract snippet/description
            snippet_selectors = [
                '.compText',
                '.abstract',
                '.snippet',
                'p',
                '.description'
            ]

            for selector in snippet_selectors:
                snippet_elem = web.select_one(selector)
                if snippet_elem:
                    snippet = snippet_elem.get_text(strip=True)
                    if snippet and len(snippet) > 20:  # Meaningful snippet length
                        break

            # Add result if we have at least title and link
            if title and link:
                data['title'] = title
                data['link'] = link
                if snippet:
                    data['snippet'] = snippet[:200]  # Limit snippet length
                new_list.append(data)

                # Limit to reasonable number of results
                if len(new_list) >= 10:
                    break

        results['results'] = new_list[:3]  # Return top 3 results
        return results

    except Exception as e:
        print(f"Error parsing BeautifulSoup: {e}")
        # Return empty results instead of failing completely
        return {'results': []}

def get_serp(query:str, gl:str='us'):
    try:
        url = f"https://search.yahoo.com/search"
        headers = {
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36'
        }
        data = {
            'q': query,
            'nojs': '1',
            'ei': 'UTF-8'
        }

        response = requests.get(url, headers=headers, params=data, timeout=7)
        response.raise_for_status()
        return response

    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        raise e


class YahooSearchEngine(WebSearchEngine):
    def perform_search(
        self, query: str, num_results: int = 10, *args, **kwargs
    ) -> List[dict]:
        """
        Yahoo search engine.

        Returns results formatted according to SearchItem model.
        """
        gl = kwargs.get('country', 'us')
        raw_results = get_serp(query, gl)
        html = raw_results.text
        parser_yahoo_html = parsing_bs(html)
        fix_result = parser_yahoo_html['results']

        results = []
        for i, item in enumerate(fix_result):
            if isinstance(item, str):
                # If it's just a URL
                results.append(
                    SearchItem(title=f"Google Result {i+1}", url=item, description="")
                )
            else:
                # item is a dict from the API response
                results.append(
                    SearchItem(
                        title=item.get('title', ''),
                        url=item.get('link', ''),
                        description=item.get('snippet', '')
                    )
                )

        return results
