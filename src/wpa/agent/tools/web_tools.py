import webbrowser
from langchain_core.tools import tool


@tool
def open_url(url: str) -> str:
    """
    Open a URL in the default web browser.
    Example: open_url('https://google.com')
    """
    try:
        if not url.startswith("http"):
            url = "https://" + url
        webbrowser.open(url)
        return f"Opened {url} in browser."
    except Exception as e:
        return f"Could not open URL: {e}"


@tool
def web_search(query: str) -> str:
    """
    Search the web using DuckDuckGo (no API key needed, works offline-ish).
    Returns top 3 results as text. Requires internet connection.
    """
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
        if not results:
            return f"No results found for: {query}"
        output = []
        for i, r in enumerate(results, 1):
            output.append(f"{i}. {r['title']}\\n   {r['body']}\\n   URL: {r['href']}")
        return "\\n\\n".join(output)
    except Exception as e:
        return f"Search failed (check internet connection): {e}"


@tool
def search_and_open(query: str) -> str:
    """
    Search for a query and open the top result in browser.
    Example: search_and_open('Python tutorials')
    """
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=1))
        if not results:
            # Fallback: open Google search
            url = f"https://google.com/search?q={query.replace(' ', '+')}"
            webbrowser.open(url)
            return f"No direct results, opened Google search for: {query}"
        url = results[0]['href']
        webbrowser.open(url)
        return f"Opened: {results[0]['title']} ({url})"
    except Exception as e:
        return f"Search failed: {e}"


# Test
# print("\n🧪 Testing open_url...")
# print(open_url.invoke({"url": "https://google.com"}))
# print("\n🧪 Testing web_search...")
# print(web_search.invoke({"query": "Python programming"}))
# print("\n🧪 Testing search_and_open...")
# print(search_and_open.invoke({"query": "Python tutorials"}))
