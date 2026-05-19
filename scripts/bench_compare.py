"""Compare pytest-benchmark JSON outputs from two runs.

Usage
-----
python scripts/bench_compare.py --base bench-main.json --candidate bench-pr.json
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BenchStat:
    name: str
    mean: float
    median: float
    stddev: float
    rounds: int


def _load_stats(path: Path) -> dict[str, BenchStat]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, BenchStat] = {}

    for bench in data.get("benchmarks", []):
        fullname = bench.get("fullname") or bench.get("name")
        stats = bench.get("stats", {})
        out[fullname] = BenchStat(
            name=fullname,
            mean=float(stats.get("mean", 0.0)),
            median=float(stats.get("median", 0.0)),
            stddev=float(stats.get("stddev", 0.0)),
            rounds=int(stats.get("rounds", 0)),
        )

    return out


def _pct_delta(base: float, candidate: float) -> float:
    if base == 0.0:
        return 0.0
    return ((candidate - base) / base) * 100.0


def _format_seconds(value: float) -> str:
    return f"{value:.6f}s"


def _print_summary(
    base: dict[str, BenchStat],
    cand: dict[str, BenchStat],
    warn_threshold_pct: float,
) -> int:
    common = sorted(set(base).intersection(cand))
    if not common:
        print("No overlapping benchmark names found between base and candidate.")
        return 1

    rows: list[tuple[str, float, BenchStat, BenchStat]] = []
    for name in common:
        b = base[name]
        c = cand[name]
        delta_pct = _pct_delta(b.mean, c.mean)
        rows.append((name, delta_pct, b, c))

    rows.sort(key=lambda x: x[1], reverse=True)

    regressions = [r for r in rows if r[1] > warn_threshold_pct]
    improvements = [r for r in rows if r[1] < -warn_threshold_pct]

    print(f"Compared {len(common)} benchmark(s).")
    print(
        f"Regressions (>{warn_threshold_pct:.1f}% slower): {len(regressions)} | "
        f"Improvements (<-{warn_threshold_pct:.1f}% faster): {len(improvements)}"
    )
    print()

    print("Top regressions:")
    if regressions:
        for name, delta_pct, b, c in regressions[:10]:
            print(
                f"  {name}\n"
                f"    base={_format_seconds(b.mean)} candidate={_format_seconds(c.mean)} "
                f"delta={delta_pct:+.2f}%"
            )
    else:
        print("  None")

    print()
    print("Top improvements:")
    if improvements:
        for name, delta_pct, b, c in sorted(improvements, key=lambda x: x[1])[:10]:
            print(
                f"  {name}\n"
                f"    base={_format_seconds(b.mean)} candidate={_format_seconds(c.mean)} "
                f"delta={delta_pct:+.2f}%"
            )
    else:
        print("  None")

    print()
    print("All overlapping benchmarks (sorted by slowdown):")
    for name, delta_pct, b, c in rows:
        print(
            f"  {name}: base={_format_seconds(b.mean)} candidate={_format_seconds(c.mean)} "
            f"delta={delta_pct:+.2f}% rounds(base/cand)={b.rounds}/{c.rounds}"
        )

    base_only = sorted(set(base) - set(cand))
    cand_only = sorted(set(cand) - set(base))

    if base_only:
        print("\nBenchmarks only in base:")
        for name in base_only:
            print(f"  {name}")

    if cand_only:
        print("\nBenchmarks only in candidate:")
        for name in cand_only:
            print(f"  {name}")

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True, help="Path to base benchmark JSON")
    parser.add_argument(
        "--candidate",
        type=Path,
        required=True,
        help="Path to candidate benchmark JSON",
    )
    parser.add_argument(
        "--warn-threshold-pct",
        type=float,
        default=15.0,
        help="Percent slowdown/faster threshold used for quick grouping",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_stats = _load_stats(args.base)
    cand_stats = _load_stats(args.candidate)
    return _print_summary(base_stats, cand_stats, args.warn_threshold_pct)


if __name__ == "__main__":
    raise SystemExit(main())
