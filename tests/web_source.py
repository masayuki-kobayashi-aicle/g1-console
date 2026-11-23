"""Lets tests inspect the page and the split browser scripts without starting a browser."""
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"


def source() -> str:
    return "\n".join((WEB / name).read_text(encoding="utf-8")
                     for name in ("index.html", "ui-core.js", "mobile.js"))
