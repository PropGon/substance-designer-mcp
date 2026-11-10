"""Search of Adobe's filter library by package name. Works without Designer running."""

from __future__ import annotations

import difflib
import re
from pathlib import Path


def packages_dir(designer_dir: Path | None) -> Path | None:
    if designer_dir is None:
        return None
    candidate = designer_dir / "resources" / "packages"
    return candidate if candidate.is_dir() else None


def search(directory: Path, query: str, limit: int = 20) -> dict:
    tokens = [t for t in re.split(r"[^a-z0-9]+", query.lower()) if t]
    if not tokens:
        raise ValueError("Escribe al menos una palabra para buscar, en ingles: noise, brick, tile...")
    names = sorted(path.stem for path in directory.glob("*.sbs"))

    def score(name: str) -> tuple[int, float]:
        hits = sum(token in name for token in tokens)
        return hits, difflib.SequenceMatcher(None, "_".join(tokens), name).ratio()

    full = [n for n in names if all(t in n for t in tokens)]
    if full:
        matches = sorted(full, key=lambda n: (-score(n)[1], n))
        exact = True
    else:
        partial = [n for n in names if any(t in n for t in tokens)]
        matches = sorted(partial, key=lambda n: (-score(n)[0], -score(n)[1], n))
        exact = False
    return {
        "query": query,
        "all_words_matched": exact,
        "total": len(matches),
        "matches": matches[:limit],
        "library_size": len(names),
        "hint": "Usa el nombre en create_node(library=...). Si el paquete tiene varios grafos, "
        "create_node te dira cuales y podras elegir con library_graph.",
    }
