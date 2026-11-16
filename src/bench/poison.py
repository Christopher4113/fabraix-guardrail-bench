"""Local search_web, swapped into the engine's TOOL_REGISTRY at runtime.

The vendored search_web calls Brave directly, outside the Platform seams, so it is replaced
here rather than edited. By default it returns plain, harmless results. During an indirect
injection run the attacker writes the results, which is how instructions reach the defender
through its environment instead of through the chat.
"""

from contextvars import ContextVar

from fabraix_engine import tools as engine_tools

# Per asyncio task, so concurrent runs never see each other's poison.
planted: ContextVar[list[dict] | None] = ContextVar("planted", default=None)
seen: ContextVar[list[str] | None] = ContextVar("seen", default=None)


def benign_results(query: str) -> list[dict]:
    return [
        {"title": f"{query} - Wikipedia", "url": "https://en.wikipedia.org/wiki/Special:Search",
         "domain": "en.wikipedia.org",
         "description": f"Encyclopedia overview of {query}, with history and references."},
        {"title": f"What to know about {query}", "url": "https://www.reuters.com/",
         "domain": "reuters.com", "description": f"Recent reporting related to {query}."},
    ]


async def search_web(platform, query: str) -> dict:
    log = seen.get()
    if log is not None:
        log.append(query)
    results = planted.get() or benign_results(query)
    return {"query": query, "results": results}


def install() -> None:
    engine_tools.TOOL_REGISTRY["search_web"] = search_web
