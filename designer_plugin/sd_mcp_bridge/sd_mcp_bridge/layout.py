"""Left-to-right layered layout. Designer's API has no auto-layout, so it is computed here."""

from __future__ import annotations


def compute_layout(
    nodes: list[str], edges: list[tuple[str, str]], spacing_x: float, spacing_y: float
) -> dict[str, tuple[float, float]]:
    """Each node goes one column right of its furthest source; columns are centred on y=0."""
    known = set(nodes)
    parents: dict[str, list[str]] = {node: [] for node in nodes}
    for source, target in edges:
        if source in known and target in known and source != target:
            parents[target].append(source)

    columns: dict[str, int] = {}

    def column_of(node: str, visiting: frozenset[str] = frozenset()) -> int:
        if node in columns:
            return columns[node]
        visiting = visiting | {node}
        available = [p for p in parents[node] if p not in visiting]  # tolerate cycles
        result = 1 + max((column_of(p, visiting) for p in available), default=-1)
        columns[node] = result
        return result

    for node in nodes:
        column_of(node)

    by_column: dict[int, list[str]] = {}
    for node in nodes:
        by_column.setdefault(columns[node], []).append(node)

    positions: dict[str, tuple[float, float]] = {}
    for column in sorted(by_column):
        members = by_column[column]

        def barycenter(node: str) -> float:
            placed = [positions[p][1] for p in parents[node] if p in positions]
            return sum(placed) / len(placed) if placed else 0.0

        members = sorted(members, key=lambda n: (barycenter(n), nodes.index(n)))
        top = -(len(members) - 1) * spacing_y / 2
        for row, node in enumerate(members):
            positions[node] = (column * spacing_x, top + row * spacing_y)
    return positions
