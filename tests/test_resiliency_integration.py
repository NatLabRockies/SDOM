"""Phase 7 / Deliverable B end-to-end integration test on the real MEA 24h subset.

Runs the full resiliency chain (load -> baseline dispatch -> per-hour outage
evaluation), computes aggregate metrics, persists & reloads the results, and
generates one distribution plot. Marked ``slow`` so CI can opt out, but the
test is runnable in the standard pytest invocation used by this repository.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # non-interactive backend for headless CI
import matplotlib.pyplot as plt  # noqa: E402
import pyomo.environ as pyo  # noqa: E402
import pytest  # noqa: E402

from sdom.resiliency import (  # noqa: E402
    OutageSpec,
    ResiliencyResults,
    evaluate_resiliency,
    plot_metric_distribution,
)

from _resiliency_fixtures import (  # noqa: E402
    INPUTS_DIR_MEA as INPUTS_DIR,
    REPO_ROOT,
    SNAPSHOT_DIR_MEA as SNAPSHOT_DIR,
)


def _highs_available() -> bool:
    for name in ("appsi_highs", "highs"):
        try:
            s = pyo.SolverFactory(name)
            if s is not None and s.available(exception_flag=False):
                return True
        except Exception:
            continue
    return False


@pytest.mark.slow
@pytest.mark.skipif(not _highs_available(), reason="HiGHS solver not available")
@pytest.mark.skipif(
    not SNAPSHOT_DIR.exists() or not INPUTS_DIR.exists(),
    reason="Real MEA resiliency data not present",
)
def test_resiliency_full_chain_mea_24h(tmp_path):
    """End-to-end: load real MEA inputs, run baseline + 5-hour evaluation,
    compute metrics, save & reload, generate one plot."""
    spec = OutageSpec(
        duration_hours=4,
        recovery_hours=4,
        outaged_assets={"imports": "all"},
    )

    results = evaluate_resiliency(
        snapshot_dir=SNAPSHOT_DIR,
        inputs_dir=INPUTS_DIR,
        outage_spec=spec,
        year=2030,
        scenario_id=1,
        n_hours=24,
        hours=[1, 5, 10, 15, 20],
        n_workers=1,
        solver="highs",
    )

    # 1. Per-hour shape and solver status
    assert isinstance(results, ResiliencyResults)
    assert len(results.per_hour) == 5
    assert sorted(results.per_hour.index.tolist()) == [1, 5, 10, 15, 20]
    statuses = set(results.per_hour["solver_status"].tolist())
    assert statuses == {"optimal"}, f"unexpected solver statuses: {statuses}"

    # 2. Aggregate metrics
    agg = results.metrics()
    assert agg["n_hours_evaluated"] == 5
    assert agg["n_errors"] == 0
    # LOLP / LOLE must be finite numerics
    import math

    assert isinstance(agg["LOLP"], float) and math.isfinite(agg["LOLP"])
    assert isinstance(agg["LOLE"], float) and math.isfinite(agg["LOLE"])

    # 3. Persist + reload (requires a Parquet engine)
    pytest.importorskip("pyarrow")
    out_dir = results.save(tmp_path / "out")
    assert (out_dir / "per_hour.parquet").is_file()
    assert (out_dir / "summary.json").is_file()

    restored = ResiliencyResults.load(out_dir)
    restored_agg = restored.metrics()
    # Compare each scalar metric (NaN-safe via pytest.approx with nan_ok=True).
    for key in (
        "LOLP",
        "LOLE",
        "mean_EUE",
        "max_EUE",
        "EUE_p50",
        "EUE_p95",
        "EUE_p99",
    ):
        assert restored_agg[key] == pytest.approx(agg[key], rel=1e-9, nan_ok=True)
    assert restored_agg["n_hours_evaluated"] == agg["n_hours_evaluated"]
    assert restored_agg["n_errors"] == agg["n_errors"]

    # 4. Plot
    ax = plot_metric_distribution(results, kind="hist")
    # ``Axes`` lives in the abstract base ``matplotlib.axes.Axes``.
    from matplotlib.axes import Axes

    assert isinstance(ax, Axes)
    plt.close("all")
