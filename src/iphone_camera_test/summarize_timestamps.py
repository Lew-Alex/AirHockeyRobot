#!/usr/bin/env python3
"""Summarize the frame-timestamp CSVs that the Camera120 app writes.

    python3 summarize_timestamps.py rec_20261107_120000.csv [more.csv ...]

For each file this prints the frame count, the average frame rate, the median
and worst gap between frames, and how many gaps were more than 1.5 times the
median (a sign of dropped or late frames).
"""

from __future__ import annotations

import csv
import statistics
import sys
from pathlib import Path


def summarize(path: Path) -> str:
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) < 2:
        return f"{path.name}: {len(rows)} frames, too few to summarize"

    stamps = [float(row["pts_seconds"]) for row in rows]
    gaps_ms = [float(row["gap_ms"]) for row in rows[1:]]
    span = stamps[-1] - stamps[0]
    median_gap = statistics.median(gaps_ms)
    late = sum(1 for gap in gaps_ms if gap > 1.5 * median_gap)

    return (
        f"{path.name}: {len(stamps)} frames over {span:.2f} s, "
        f"{(len(stamps) - 1) / span:.2f} fps average, "
        f"median gap {median_gap:.2f} ms, worst gap {max(gaps_ms):.2f} ms, "
        f"{late} gaps over 1.5x the median"
    )


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    for name in argv:
        print(summarize(Path(name)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
