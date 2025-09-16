from typing import List

# from googlesearch import search

from app.tool.search.base import SearchItem, WebSearchEngine

import requests # type: ignore

def formated_serp(response, n=5):
    try:
        formated = ""
        for result in response['organic'][:n]:
            formated += f"**Title**: {result.get('title', '')}\n"
            formated += f"**Link**: {result.get('link', '')}\n"
            formated += f"**Snippet**: {result.get('snippet', '')}\n\n"
        return formated
    except KeyError:
        return response['organic'][:n]

def get_serp(q:str, gl:str='us'):
    try:
        url = "https://google.serper.dev/search"

        payload = {
            "q": q,
            "gl": gl,
        }
        headers = {
            'X-API-KEY': 'bcdf4d4ffb4d7e7191c3092d7c54a03b36e57563',
            'Content-Type': 'application/json'
        }

        response = requests.request("POST", url, headers=headers, json=payload)
        response.raise_for_status()
        organic_results = response.json()['organic']
        return organic_results
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        raise e



class GoogleSearchEngine(WebSearchEngine):
    def perform_search(
        self, query: str, num_results: int = 10, *args, **kwargs
    ) -> List[SearchItem]:
        """
        Google search engine.

        Returns results formatted according to SearchItem model.
        """
        gl = kwargs.get('country', 'us')
        raw_results = get_serp(query, gl)

        results = []
        for i, item in enumerate(raw_results):
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
