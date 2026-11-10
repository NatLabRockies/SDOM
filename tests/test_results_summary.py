"""Verify summary construction and strict dispatch-total validation."""

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import pyomo.environ as pyo
import pytest
from pyomo.core.base.var import IndexedVar, VarData
from test_hydro_curtailment_results import _collect, _reporting_model

import sdom.results._values as result_values
from sdom import get_default_solver_config_dict, initialize_model, load_data, run_solver
from sdom.common.utilities import concatenate_dataframes
from sdom.results.summary import _build_metric_summary, _build_summary_dataframe

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("values", [[], [0.0], [1.0, 0.0, 2.5], [-1.0, 2.0, 0.5]])
def test_checked_dispatch_sum_matches_numeric_total(values):
    model = pyo.ConcreteModel()
    hours = range(1, len(values) + 1)
    model.h = pyo.Set(initialize=hours, ordered=True)
    model.dispatch = pyo.Var(model.h, initialize=dict(enumerate(values, start=1)))
    dispatch = model.dispatch
    assert isinstance(dispatch, IndexedVar)
    assert result_values._sum_initialized_dispatch(dispatch, hours) == pytest.approx(sum(values))


@pytest.mark.parametrize("invalid", [None, np.nan, np.inf, -np.inf])
def test_checked_dispatch_sum_rejects_missing_or_nonfinite_values(invalid):
    model = pyo.ConcreteModel()
    model.h = pyo.Set(initialize=[1, 2], ordered=True)
    model.dispatch = pyo.Var(model.h, initialize=1.0)
    dispatch = model.dispatch
    assert isinstance(dispatch, IndexedVar)
    datum = dispatch[2]
    assert isinstance(datum, VarData)
    datum.set_value(invalid, skip_validation=True)
    with pytest.raises(ValueError, match=r"dispatch.*hour 2"):
        result_values._sum_initialized_dispatch(dispatch, [1, 2])


def test_batched_metric_rows_preserve_legacy_coercion_identifiers_and_order():
    metrics = [
        ("Capacity", {1: 10.0, 2: 20.0}, "MW"),
        ("Empty", {}, "MW"),
        ("Mixed", {"missing": None, "numeric": "4.5", "invalid": "not numeric"}, "MWh"),
    ]
    expected = pd.DataFrame(
        {"Metric": ["Total cost"], "Technology": [None], "Run": [1], "Optimal Value": [12.5], "Unit": ["$US"]}
    )
    for metric, values, unit in metrics:
        expected = concatenate_dataframes(expected, values, run=1, metric=metric, unit=unit)
    pd.testing.assert_frame_equal(_build_metric_summary(12.5, metrics), expected)


@pytest.fixture(scope="module")
def solved_summary_case(request):
    scenario = request.param
    data = load_data(str(ROOT / "Data" / scenario))
    model = initialize_model(data, n_hours=24)
    config = get_default_solver_config_dict(solver_name="highs", executable_path="")
    config["solve_keywords"]["report_timing"] = False
    config["solve_keywords"]["keepfiles"] = False
    results = run_solver(model, config)
    assert results.is_optimal
    return model, results


@pytest.mark.parametrize(
    "solved_summary_case",
    ["no_exchange_run_of_river", "exchange_hydro_daily_budget_multiple_balancing_p95", "zonal_test"],
    indirect=True,
)
def test_summary_preserves_schema_totals_and_owned_area_metrics(solved_summary_case):
    model, results = solved_summary_case
    frame = results.summary_df
    assert frame.columns.tolist() == ["Metric", "Technology", "Run", "Optimal Value", "Unit"]
    assert frame.dtypes.astype(str).to_dict() == {
        "Metric": "object",
        "Technology": "object",
        "Run": "int64",
        "Optimal Value": "float64",
        "Unit": "object",
    }
    assert frame["Run"].eq(1).all()
    assert frame.iloc[0]["Metric"] == "Total cost"
    assert frame.iloc[0]["Optimal Value"] == pytest.approx(pyo.value(model.Obj))
    assert frame.iloc[-2:]["Metric"].tolist() == [
        "Total Hydro curtailment", "Hydro curtailment percentage"
    ]
    assert not frame.duplicated(["Metric", "Technology"]).any()
    hosts = [model.area[area] for area in model.A] if results.is_zonal else [model]
    demand = sum(pyo.value(host.demand.ts_parameter[h]) for host in hosts for h in host.h)
    actual_demand = frame.loc[frame["Metric"] == "Total demand", "Optimal Value"].item()
    assert actual_demand == pytest.approx(demand)
    for area in results.areas:
        local = results.area_summary_df[area]
        assert not local.empty
        assert local.columns.tolist() == frame.columns.tolist()
        assert "Total Hydro curtailment" not in set(local["Metric"])
        local_demand = sum(pyo.value(model.area[area].demand.ts_parameter[h]) for h in model.h)
        assert local.loc[local["Metric"] == "Total demand", "Optimal Value"].item() == pytest.approx(local_demand)


def test_summary_builds_without_repeated_dataframe_concatenation(monkeypatch):
    model = _reporting_model("RunOfRiverFormulation")
    results = _collect(model)

    def reject_concat(*args, **kwargs):
        raise AssertionError("Summary construction must batch rows before creating its DataFrame")

    monkeypatch.setattr(pd, "concat", reject_concat)
    frame = _build_summary_dataframe(model, results, list(model.storage.j))
    assert not frame.empty


@pytest.mark.parametrize("zonal", [False, True], ids=["copperplate", "zonal"])
@pytest.mark.parametrize("invalid", [None, np.nan, np.inf])
def test_summary_invalid_storage_charge_propagates_from_collection(invalid, *, zonal, caplog):
    model = _reporting_model("RunOfRiverFormulation", zonal=zonal)
    host = model.area[next(iter(model.A))] if zonal else model
    technology = next(iter(host.storage.j))
    host.storage.PC[1, technology].set_value(invalid, skip_validation=True)
    with caplog.at_level(logging.WARNING), pytest.raises(ValueError, match=r"storage\.PC.*hour 1"):
        _collect(model)
    assert "Could not build per-area summary" not in caplog.text


@pytest.mark.parametrize("component", ["imports", "exports"])
@pytest.mark.parametrize("invalid", [None, np.nan, np.inf])
def test_summary_invalid_exchange_dispatch_is_rejected(component, invalid):
    model = _reporting_model("RunOfRiverFormulation")
    host = getattr(model, component)
    host.variable = pyo.Var(model.h, initialize=1.0)
    results = _collect(model)
    datum = host.variable[1]
    assert isinstance(datum, VarData)
    datum.set_value(invalid, skip_validation=True)
    with pytest.raises(ValueError, match=rf"{component}\.variable.*hour 1"):
        _build_summary_dataframe(model, results, list(model.storage.j))
