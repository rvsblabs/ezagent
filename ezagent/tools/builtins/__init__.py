from pathlib import Path

_BUILTINS_DIR = Path(__file__).parent

PREBUILT_TOOLS = {
    "memory": _BUILTINS_DIR / "memory",
    "sqlite": _BUILTINS_DIR / "sqlite",
    "web_search": _BUILTINS_DIR / "web_search",
    "http": _BUILTINS_DIR / "http",
    "filesystem": _BUILTINS_DIR / "filesystem",
    "arxiv": _BUILTINS_DIR / "arxiv",
    "pdf_reader": _BUILTINS_DIR / "pdf_reader",
    "perplexity_research": _BUILTINS_DIR / "perplexity_research",
    "extract_structured": _BUILTINS_DIR / "extract_structured",
}
