"""Tests for the ``critical_load_MW`` override on outage dispatch (#73).

Covers the new keyword argument added to ``build_outage_dispatch`` and its
forwarding through ``run_resiliency_evaluation`` and ``evaluate_resiliency``.
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from sdom.resiliency import (
    OutageSpec,
    build_outage_dispatch,
    evaluate_resiliency,
    run_resiliency_evaluation,
)

from test_resiliency_outage_dispatch import (
    _make_baseline_results,
    _make_designed_system,
)


def _build(start_hour=5, duration=4, recovery=4, n_hours=24, **kwargs):
    """Build a tiny outage LP and return ``(model, ds, br, start, duration)``.

    A non-flat baseline load (``10*t``) is injected so the override can be
    distinguished from the baseline value at every hour.
    """
    ds = _make_designed_system(n=n_hours, load_value=50.0)
    varying = pd.Series(
        [10.0 * t for t in range(1, n_hours + 1)],
        index=ds.load.index,
        name=ds.load.name,
    )
    ds = ds.__class__(
        storage_caps=ds.storage_caps,
        thermal_caps=ds.thermal_caps,
        solar_caps=ds.solar_caps,
        wind_caps=ds.wind_caps,
        load=varying,
        cf_solar=ds.cf_solar,
        cf_wind=ds.cf_wind,
        nuclear=ds.nuclear,
        hydro=ds.hydro,
        other_renewables=ds.other_renewables,
        import_cap=ds.import_cap,
        import_price=ds.import_price,
        export_cap=ds.export_cap,
        export_price=ds.export_price,
        phi_fix_t=ds.phi_fix_t,
        phi_var_t=ds.phi_var_t,
        month_of_hour=ds.month_of_hour,
    )
    br = _make_baseline_results(ds, soc_value=20.0)
    spec = OutageSpec(
        duration_hours=duration,
        recovery_hours=recovery,
        outaged_assets={"balancing_units": "all"},
    )
    model = build_outage_dispatch(
        br,
        start_hour=start_hour,
        outage_spec=spec,
        designed_system=ds,
        n_hours=n_hours,
        **kwargs,
    )
    return model, ds, br, start_hour, duration


def test_critical_load_default_is_baseline():
    """``critical_load_MW=None`` (default) must match ``designed_system.load``."""
    model, ds, _, _, _ = _build()
    for t in model.h:
        assert float(model.load_param[t]) == pytest.approx(float(ds.load.loc[t]))
    assert model._sdom_outage_meta["critical_load_MW"] is None


def test_critical_load_overrides_outage_window_only():
    crit = 123.5
    model, ds, _, start, duration = _build(critical_load_MW=crit)
    outage_end = start + duration - 1
    for t in model.h:
        expected = crit if start <= t <= outage_end else float(ds.load.loc[t])
        assert float(model.load_param[t]) == pytest.approx(expected), (
            f"hour {t}: got {float(model.load_param[t])}, expected {expected}"
        )


def test_critical_load_zero_is_valid():
    model, _, _, start, duration = _build(critical_load_MW=0.0)
    for t in range(start, start + duration):
        assert float(model.load_param[t]) == pytest.approx(0.0)
    assert model._sdom_outage_meta["critical_load_MW"] == 0.0


def test_critical_load_negative_raises():
    with pytest.raises(ValueError, match="critical_load_MW must be non-negative"):
        _build(critical_load_MW=-1.0)


def test_critical_load_nan_raises():
    with pytest.raises(ValueError, match="critical_load_MW must be a finite number"):
        _build(critical_load_MW=float("nan"))


def test_critical_load_inf_raises():
    with pytest.raises(ValueError, match="critical_load_MW must be a finite number"):
        _build(critical_load_MW=float("inf"))


def test_critical_load_metadata_round_trip():
    model, _, _, _, _ = _build(critical_load_MW=77.0)
    assert model._sdom_outage_meta["critical_load_MW"] == pytest.approx(77.0)


# ---------------------------------------------------------------------------
# Forwarding through the runner
# ---------------------------------------------------------------------------
def test_runner_forwards_critical_load():
    ds = _make_designed_system(n=24, load_value=50.0)
    br = _make_baseline_results(ds, soc_value=20.0)
    spec = OutageSpec(
        duration_hours=2,
        recovery_hours=2,
        outaged_assets={"balancing_units": "all"},
    )

    captured_kwargs: list[dict] = []

    def _fake_build(baseline_results, **kwargs):
        captured_kwargs.append(kwargs)
        return build_outage_dispatch(baseline_results, **kwargs)

    with patch("sdom.resiliency.runner._build_outage_dispatch", side_effect=_fake_build):
        run_resiliency_evaluation(
            br,
            outage_spec=spec,
            designed_system=ds,
            hours=[1, 5],
            n_hours=24,
            n_workers=1,
            critical_load_MW=42.0,
            solver_options={},
        )

    assert len(captured_kwargs) == 2
    for kw in captured_kwargs:
        assert kw["critical_load_MW"] == pytest.approx(42.0)


@pytest.mark.parametrize(
    "bad_value, match",
    [
        (-1.0, "non-negative"),
        (float("nan"), "finite number"),
        (float("inf"), "finite number"),
    ],
)
def test_runner_validates_critical_load_before_workers(bad_value, match):
    """Invalid ``critical_load_MW`` must raise in the parent process before
    any payload is built, instead of being swallowed by the per-hour
    error-isolation wrapper in ``_solve_one_hour``."""
    ds = _make_designed_system(n=4, load_value=10.0)
    br = _make_baseline_results(ds, soc_value=2.0)
    spec = OutageSpec(
        duration_hours=1,
        recovery_hours=1,
        outaged_assets={"balancing_units": "all"},
    )

    with patch("sdom.resiliency.runner._build_outage_dispatch") as fake_build:
        with pytest.raises(ValueError, match=match):
            run_resiliency_evaluation(
                br,
                outage_spec=spec,
                designed_system=ds,
                hours=[1],
                n_hours=4,
                n_workers=1,
                critical_load_MW=bad_value,
            )
        fake_build.assert_not_called()


def test_evaluate_resiliency_forwards_critical_load(monkeypatch):
    """``evaluate_resiliency`` must pass ``critical_load_MW`` to the runner."""
    from sdom.resiliency import evaluate as evaluate_module

    captured: dict = {}

    def _fake_runner(baseline_results, **kwargs):
        captured.update(kwargs)

        class _FakeResults:
            per_hour = pd.DataFrame()
            metadata: dict = {}

        return _FakeResults()

    def _fake_load(*_args, **_kwargs):
        return _make_designed_system(n=4, load_value=10.0)

    def _fake_build(_designed_system, **_kwargs):
        class _Model:
            pass

        return _Model()

    def _fake_run_baseline(_model, **_kwargs):
        ds = _make_designed_system(n=4, load_value=10.0)
        return _make_baseline_results(ds, soc_value=5.0)

    monkeypatch.setattr(evaluate_module, "load_designed_system", _fake_load)
    monkeypatch.setattr(evaluate_module, "build_baseline_dispatch", _fake_build)
    monkeypatch.setattr(evaluate_module, "run_baseline_dispatch", _fake_run_baseline)
    monkeypatch.setattr(evaluate_module, "run_resiliency_evaluation", _fake_runner)

    spec = OutageSpec(
        duration_hours=2,
        recovery_hours=1,
        outaged_assets={"balancing_units": "all"},
    )
    evaluate_resiliency(
        "snapshot/",
        inputs_dir="inputs/",
        outage_spec=spec,
        n_hours=4,
        critical_load_MW=99.0,
    )
    assert captured["critical_load_MW"] == pytest.approx(99.0)
