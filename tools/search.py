"""
tools/search.py
Web search tool for finding local events using Tavily.
"""

import os
from tavily import TavilyClient
from dotenv import load_dotenv

load_dotenv()

_tavily = None


def get_tavily():
    global _tavily
    if _tavily is None:
        _tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
    return _tavily


def search_local_events(query: str) -> str:
    """
    Search the web for local events matching the user's request.

    Args:
        query: What the user wants to do (e.g. 'live music tonight')
    """
    location = os.getenv("MY_LOCATION", "Shelter Island, NY")
    full_query = f"{query} near {location} today tonight"

    print(f"Searching: {full_query}")
    client = get_tavily()

    results = client.search(
        query=full_query,
        search_depth="advanced",
        max_results=5
    )

    if not results.get("results"):
        return "No events found matching that description."

    formatted = []
    for i, r in enumerate(results["results"], 1):
        formatted.append(
            f"{i}. *{r.get('title', 'Untitled')}*\n"
            f"   {r.get('content', '')[:200]}\n"
            f"   {r.get('url', '')}"
        )

    return "\n\n".join(formatted)
