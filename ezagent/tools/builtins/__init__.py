from pathlib import Path

_BUILTINS_DIR = Path(__file__).parent

PREBUILT_TOOLS = {
    "memory": _BUILTINS_DIR / "memory",
}
