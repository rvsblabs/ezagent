from pathlib import Path

_BUILTINS_DIR = Path(__file__).parent

PREBUILT_TOOLS = {
    "memory": _BUILTINS_DIR / "memory",
    "web_search": _BUILTINS_DIR / "web_search",
    "http": _BUILTINS_DIR / "http",
    "filesystem": _BUILTINS_DIR / "filesystem",
}
