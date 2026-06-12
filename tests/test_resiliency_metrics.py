"""Phase 6 - Deliverable A: aggregate metrics on ResiliencyResults."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sdom.resiliency import ResiliencyResults


_EUE_VALUES = [0.0, 0.0, 0.0, 0.0, 0.0, 5.0, 10.0, 0.0, 100.0, 200.0]
_USE_HOURS = [0, 0, 0, 0, 0, 1, 2, 0, 4, 5]


def _make_results(*, eue=None, use_hours=None, statuses=None, n=10):
    """Build a synthetic ``ResiliencyResults`` without solving anything."""
    eue = list(_EUE_VALUES if eue is None else eue)
    use_hours = list(_USE_HOURS if use_hours is None else use_hours)
    if statuses is None:
        statuses = ["optimal"] * n
    df = pd.DataFrame(
        {
            "EUE": eue,
            "USE_hours": use_hours,
            "max_unserved_MW": [0.0] * n,
            "objective_value": [0.0] * n,
            "solver_status": statuses,
            "solve_time_s": [0.01] * n,
            "truncated": [False] * n,
            "error_message": [""] * n,
        },
        index=pd.Index(list(range(1, n + 1)), name="hour"),
    )
    return ResiliencyResults(
        per_hour=df,
        metadata={"n_hours": n, "n_workers_used": 1, "solver": "highs"},
    )


def test_metrics_aggregate_synthetic():
    results = _make_results()
    m = results.metrics(level="aggregate")

    assert isinstance(m, dict)
    assert m["LOLP"] == pytest.approx(0.4)
    assert m["LOLE"] == pytest.approx(1.2)
    assert m["mean_EUE"] == pytest.approx(31.5)
    assert m["max_EUE"] == pytest.approx(200.0)

    arr = np.asarray(_EUE_VALUES, dtype=float)
    assert m["EUE_p50"] == pytest.approx(np.percentile(arr, 50, method="linear"))
    assert m["EUE_p95"] == pytest.approx(np.percentile(arr, 95, method="linear"))
    assert m["EUE_p99"] == pytest.approx(np.percentile(arr, 99, method="linear"))
    assert m["n_hours_evaluated"] == 10
    assert m["n_errors"] == 0


def test_metrics_excludes_errors_from_aggregate():
    eue = list(_EUE_VALUES)
    eue[8] = float("nan")  # hour with index 9 (0-based 8)
    statuses = ["optimal"] * 10
    statuses[8] = "error"
    results = _make_results(eue=eue, statuses=statuses)

    m = results.metrics(level="aggregate")

    assert m["n_hours_evaluated"] == 9
    assert m["n_errors"] == 1
    # Hour 9 (EUE=100) excluded; remaining values
    remaining = [v for i, v in enumerate(_EUE_VALUES) if i != 8]
    assert m["mean_EUE"] == pytest.approx(np.mean(remaining))
    assert m["max_EUE"] == pytest.approx(max(remaining))
    # LOLP across 9 hours: hours with EUE > 0 are 5, 6, 9 (orig idx 5,6,9) = 3/9
    assert m["LOLP"] == pytest.approx(3 / 9)


def test_metrics_per_hour_returns_per_hour_dataframe():
    results = _make_results()
    df = results.metrics(level="per_hour")
    assert isinstance(df, pd.DataFrame)
    assert "hour" in df.columns
    assert len(df) == 10
    # Mutating returned frame should not affect internal state.
    df.loc[0, "EUE"] = -999.0
    assert results.per_hour.iloc[0]["EUE"] == 0.0


def test_metrics_invalid_level_raises():
    results = _make_results()
    with pytest.raises(ValueError, match="level"):
        results.metrics(level="bogus")


def test_metrics_includes_probability_weighted_expected_keys():
    """Aggregate metrics expose ``EUE_expected`` and ``USE_hours_expected``."""
    results = _make_results()
    m = results.metrics(level="aggregate")

    assert "EUE_expected" in m
    assert "USE_hours_expected" in m


def test_expected_metrics_uniform_renormalize_matches_mean():
    """Q1=renormalize: ``P(h) = 1/len(hours)`` => expected == unweighted mean.

    With the renormalize convention, the probability-weighted expected
    metrics over a partial-evaluation set collapse to the arithmetic mean
    of the evaluated hours. Documented to avoid being mistaken for a bug.
    """
    results = _make_results()
    m = results.metrics(level="aggregate")

    assert m["EUE_expected"] == pytest.approx(m["mean_EUE"])
    assert m["USE_hours_expected"] == pytest.approx(m["LOLE"])


def test_expected_metrics_subset_renormalize_convention():
    """Subset evaluation: weights renormalize to 1/n_eval, not 1/n_total."""
    eue = [0.0, 4.0, 8.0]
    use_hours = [0, 1, 3]
    results = _make_results(eue=eue, use_hours=use_hours, n=3)
    m = results.metrics(level="aggregate")

    assert m["EUE_expected"] == pytest.approx((0.0 + 4.0 + 8.0) / 3)
    assert m["USE_hours_expected"] == pytest.approx((0 + 1 + 3) / 3)


def test_expected_metrics_identity_sum_p_times_eue():
    """``EUE_expected == sum_h P_h * EUE_h`` on a synthetic frame."""
    results = _make_results()
    m = results.metrics(level="aggregate")

    eue = np.asarray(_EUE_VALUES, dtype=float)
    p_h = 1.0 / len(eue)
    assert m["EUE_expected"] == pytest.approx(float(np.sum(p_h * eue)))


def test_expected_metrics_exclude_errored_hours():
    """Errored hours are dropped before renormalize, like unweighted stats."""
    eue = list(_EUE_VALUES)
    eue[8] = float("nan")
    statuses = ["optimal"] * 10
    statuses[8] = "error"
    results = _make_results(eue=eue, statuses=statuses)

    m = results.metrics(level="aggregate")
    remaining = [v for i, v in enumerate(_EUE_VALUES) if i != 8]
    assert m["n_errors"] == 1
    assert m["n_hours_evaluated"] == 9
    assert m["EUE_expected"] == pytest.approx(sum(remaining) / 9)
    # Existing unweighted metric must remain unchanged in name and value.
    assert m["mean_EUE"] == pytest.approx(np.mean(remaining))


def test_convenience_scalars():
    results = _make_results()
    arr = np.asarray(_EUE_VALUES, dtype=float)

    assert results.lolp() == pytest.approx(0.4)
    assert results.lole() == pytest.approx(1.2)
    assert results.eue() == pytest.approx(31.5)
    assert results.eue(p=0.5) == pytest.approx(np.percentile(arr, 50))
    assert results.eue(p=0.95) == pytest.approx(np.percentile(arr, 95))
