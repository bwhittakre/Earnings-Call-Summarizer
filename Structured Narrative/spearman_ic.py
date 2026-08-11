"""Tiny Spearman Rank IC helper shared by tests and eval parity checks."""
from __future__ import annotations

from typing import Sequence


def spearman_rank_ic(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Pearson correlation of average ranks; None if n < 3 or zero variance."""
    pairs = [
        (float(x), float(y))
        for x, y in zip(xs, ys, strict=False)
        if x is not None and y is not None and x == x and y == y
    ]
    n = len(pairs)
    if n < 3:
        return None
    xv = [p[0] for p in pairs]
    yv = [p[1] for p in pairs]

    def ranks(vals: list[float]) -> list[float]:
        order = sorted(range(n), key=lambda i: vals[i])
        out = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                out[order[k]] = avg
            i = j + 1
        return out

    rx = ranks(xv)
    ry = ranks(yv)
    mean_x = sum(rx) / n
    mean_y = sum(ry) / n
    num = sum((a - mean_x) * (b - mean_y) for a, b in zip(rx, ry, strict=True))
    den_x = sum((a - mean_x) ** 2 for a in rx) ** 0.5
    den_y = sum((b - mean_y) ** 2 for b in ry) ** 0.5
    if den_x == 0 or den_y == 0:
        return None
    return num / (den_x * den_y)
