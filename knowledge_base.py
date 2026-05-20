"""
Simple keyword-based knowledge base lookup.
Sections from knowledge_base.md are searched by word overlap with the query.
Top-2 relevant sections are injected into the AI context.
"""
import re
from pathlib import Path

_KB_PATH = Path(__file__).parent / "knowledge_base.md"
_sections: list[tuple[str, str, set[str]]] = []  # (header, body, token_set)


def _load() -> None:
    if not _KB_PATH.exists():
        return
    text = _KB_PATH.read_text(encoding="utf-8")
    # Split by h3 headers (###)
    parts = re.split(r"\n###\s+", text)
    for part in parts[1:]:  # skip preamble before first ###
        lines = part.strip().splitlines()
        header = lines[0].strip()
        body = "\n".join(lines[1:]).strip()
        if header and body:
            formatted_body = f"**{header}**\n{body}"
            tokens = set(re.findall(r"\w+", f"{header} {body}".lower()))
            _sections.append((header.lower(), formatted_body, tokens))


_load()


def get_relevant_context(query: str, max_sections: int = 2) -> str | None:
    """Return the most relevant KB sections for the query, or None if nothing matches."""
    if not _sections:
        return None

    query_words = set(re.findall(r"\w+", query.lower()))
    if not query_words:
        return None

    scored: list[tuple[int, str]] = []
    for _, body, tokens in _sections:
        overlap = len(query_words & tokens)
        if overlap > 0:
            scored.append((overlap, body))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = [body for _, body in scored[:max_sections]]
    return "\n\n---\n\n".join(top) if top else None
