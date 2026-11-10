"""Hydro unused-budget reporting from explicitly assigned dispatch values."""

from pathlib import Path

import pandas as pd
import pytest
from pyomo.environ import Var
from pyomo.opt import SolverResults
from utils_tests import check_budget_constraint, check_supply_balance_constraint

from sdom import export_results, get_default_solver_config_dict, initialize_model, load_data, run_solver
from sdom.results import collect_results_from_model

ROOT = Path(__file__).resolve().parents[1]
HYDRO_METRICS = ("Total Hydro curtailment", "Hydro curtailment percentage")


def _reporting_data(formulation, *, zonal=False, alpha=1.0, budget_per_hour=250_000.0):
    """Load real inputs and isolate hydro reporting with controlled profiles."""
    folder = "zonal_test" if zonal else "no_exchange_hydro_daily_budget_multiple_balancing_p95"
    data = load_data(str(ROOT / "Data" / folder))
    data["formulations"].loc[data["formulations"]["Component"] == "Hydro", "Formulation"] = formulation
    data["scalars"].loc["AlphaLargHy", "Value"] = alpha
    if zonal:
        for area, hydro in data["per_area_hydro"].items():
            hydro["LargeHydro"] = budget_per_hour * (1 if area == "A1" else 3)
            hydro["LargeHydro_Min"] = 0.0
            hydro["LargeHydro_Max"] = 1_000_000.0
    else:
        data["large_hydro_data"]["LargeHydro"] = budget_per_hour
        data["large_hydro_min"]["LargeHydro"] = 0.0
        data["large_hydro_max"]["LargeHydro"] = 1_000_000.0
    return data


def _reporting_model(formulation, *, n_hours=1, zonal=False, alpha=1.0, budget_per_hour=250_000.0):
    """Build a real-data model with controlled profiles for collector unit tests."""
    data = _reporting_data(formulation, zonal=zonal, alpha=alpha, budget_per_hour=budget_per_hour)
    model = initialize_model(data, n_hours=n_hours)
    for variable in model.component_data_objects(Var):
        variable.set_value(max(0.0, variable.lb or 0.0))
    return model


def _set_hydro_generation(host, dispatch, *, first_hour_delta=0.0):
    for hour in host.h:
        host.hydro.generation[hour].set_value(dispatch)
    host.hydro.generation[1].set_value(dispatch + first_hour_delta)


def _collect(model):
    """Exercise collection without claiming the assigned values form a solved system."""
    solver_result = SolverResults()
    solver_result.solver.status = "ok"
    solver_result.solver.termination_condition = "optimal"
    return collect_results_from_model(model, solver_result)


def _hydro_rows(summary):
    return summary.loc[summary["Metric"].isin(HYDRO_METRICS)].reset_index(drop=True)


def test_hydro_summary_reports_unused_budget_in_twh_and_availability_percentage():
    model = _reporting_model("DailyBudgetUpperBoundFormulation", alpha=0.5)
    for hour in model.h:
        model.hydro.generation[hour].set_value(187_500.0)

    results = _collect(model)

    expected = pd.DataFrame(
        {
            "Metric": list(HYDRO_METRICS),
            "Technology": ["Hydro", "Hydro"],
            "Run": [1, 1],
            "Optimal Value": [1.5, 25.0],
            "Unit": ["TWh", "%"],
        }
    )
    pd.testing.assert_frame_equal(_hydro_rows(results.get_summary_dataframe()), expected)


def test_zonal_hydro_percentage_uses_aggregated_energy_not_average_percentages():
    model = _reporting_model("DailyBudgetUpperBoundFormulation", zonal=True)
    _set_hydro_generation(model.area["A1"], 0.0)
    _set_hydro_generation(model.area["A2"], 750_000.0)

    rows = _hydro_rows(_collect(model).summary_df)

    assert rows["Technology"].tolist() == ["Hydro", "Hydro"]
    assert rows["Unit"].tolist() == ["TWh", "%"]
    assert rows["Optimal Value"].tolist() == pytest.approx([6.0, 25.0])


@pytest.mark.parametrize(
    ("formulation", "unused_mwh", "expected_unused"),
    [
        ("DailyBudgetFormulation", 0.15, 0.0),
        ("DailyBudgetFormulation", -0.15, 0.0),
        ("DailyBudgetUpperBoundFormulation", -0.15, 0.0),
        ("DailyBudgetUpperBoundFormulation", 0.15, 0.15),
    ],
)
def test_hydro_reporting_handles_only_tiny_numerical_residuals(formulation, unused_mwh, expected_unused):
    # A 6e6 MWh budget has tolerance 1e-3 + 5e-8 * 6e6 = 0.301 MWh.
    model = _reporting_model(formulation)
    _set_hydro_generation(model, 250_000.0, first_hour_delta=-unused_mwh)

    rows = _hydro_rows(_collect(model).summary_df)

    assert rows["Optimal Value"].tolist() == pytest.approx(
        [expected_unused / 1e6, 100.0 * expected_unused / 6e6], abs=1e-12
    )


@pytest.mark.parametrize(
    ("formulation", "unused_mwh"),
    [
        ("DailyBudgetFormulation", 0.302),
        ("DailyBudgetFormulation", -0.302),
        ("DailyBudgetUpperBoundFormulation", -0.302),
    ],
)
def test_hydro_reporting_rejects_residuals_outside_documented_tolerance(formulation, unused_mwh):
    model = _reporting_model(formulation)
    _set_hydro_generation(model, 250_000.0, first_hour_delta=-unused_mwh)

    with pytest.raises(ValueError, match=r"Hydro budget violation.*period 1.*MWh"):
        _collect(model)


@pytest.mark.parametrize("zonal", [False, True], ids=["periods", "areas"])
def test_hydro_reporting_does_not_cancel_budget_excess_against_unused_energy(zonal):
    model = _reporting_model("DailyBudgetUpperBoundFormulation", n_hours=48, zonal=zonal)
    if zonal:
        _set_hydro_generation(model.area["A1"], 250_001.0)
        _set_hydro_generation(model.area["A2"], 749_999.0)
    else:
        for hour in model.h:
            model.hydro.generation[hour].set_value(250_001.0 if hour <= 24 else 249_999.0)

    with pytest.raises(ValueError, match=r"Hydro budget violation.*period 1"):
        _collect(model)


@pytest.mark.parametrize("zonal", [False, True], ids=["copperplate", "zonal"])
@pytest.mark.parametrize(
    "formulation",
    [
        "DailyBudgetFormulation",
        "DailyBudgetUpperBoundFormulation",
        "MonthlyBudgetFormulation",
        "MonthlyBudgetUpperBoundFormulation",
    ],
)
def test_zero_hydro_budgets_report_zero_energy_and_percentage(formulation, zonal):
    model = _reporting_model(formulation, zonal=zonal, budget_per_hour=0.0)

    assert _hydro_rows(_collect(model).summary_df)["Optimal Value"].tolist() == [0.0, 0.0]


@pytest.mark.parametrize("zonal", [False, True], ids=["copperplate", "zonal"])
def test_run_of_river_reports_zero_without_counting_activation_as_unused_budget(zonal):
    model = _reporting_model("RunOfRiverFormulation", n_hours=25, zonal=zonal, alpha=0.5)
    hosts = [model.area[area] for area in model.A] if zonal else [model]
    for host in hosts:
        dispatch = 375_000.0 if zonal and host.index() == "A2" else 125_000.0
        _set_hydro_generation(host, dispatch)

    assert len(model.h) == 25
    assert _hydro_rows(_collect(model).summary_df)["Optimal Value"].tolist() == [0.0, 0.0]


@pytest.mark.parametrize(
    ("formulation", "requested_hours", "modeled_hours", "dispatch", "expected_twh", "expected_pct"),
    [
        ("DailyBudgetFormulation", 25, 48, 250_000.0, 0.0, 0.0),
        ("DailyBudgetUpperBoundFormulation", 25, 48, 125_000.0, 6.0, 50.0),
        ("MonthlyBudgetFormulation", 731, 1460, 250_000.0, 0.0, 0.0),
        ("MonthlyBudgetUpperBoundFormulation", 731, 1460, 125_000.0, 182.5, 50.0),
    ],
)
def test_hydro_reporting_uses_complete_rounded_periods_only(
    formulation, requested_hours, *, modeled_hours, dispatch, expected_twh, expected_pct
):
    model = _reporting_model(formulation, n_hours=requested_hours)
    _set_hydro_generation(model, dispatch)

    assert len(model.h) == modeled_hours
    assert _hydro_rows(_collect(model).summary_df)["Optimal Value"].tolist() == [expected_twh, expected_pct]


def test_hydro_reporting_does_not_treat_hourly_above_profile_dispatch_as_curtailment():
    model = _reporting_model("DailyBudgetUpperBoundFormulation")
    for hour in model.h:
        model.hydro.generation[hour].set_value(375_000.0 if hour <= 12 else 125_000.0)

    assert _hydro_rows(_collect(model).summary_df)["Optimal Value"].tolist() == [0.0, 0.0]


@pytest.mark.parametrize("zonal", [False, True], ids=["copperplate", "zonal"])
@pytest.mark.parametrize("invalid", [None, float("nan"), float("inf")], ids=["missing", "nan", "infinity"])
def test_hydro_reporting_rejects_missing_or_nonfinite_dispatch(zonal, invalid):
    model = _reporting_model("DailyBudgetUpperBoundFormulation", zonal=zonal)
    host = model.area["A1"] if zonal else model
    host.hydro.generation[1].set_value(invalid)

    with pytest.raises(ValueError, match=r"(Incomplete hydro dispatch|Nonfinite hydro budget or dispatch)"):
        _collect(model)


@pytest.mark.parametrize(("dispatch", "violates"), [(0.000999, False), (0.001001, True)])
def test_zero_budget_excess_uses_absolute_tolerance(dispatch, violates):
    model = _reporting_model("DailyBudgetUpperBoundFormulation", budget_per_hour=0.0)
    model.hydro.generation[1].set_value(dispatch)

    if violates:
        with pytest.raises(ValueError, match="Hydro budget violation"):
            _collect(model)
    else:
        assert _hydro_rows(_collect(model).summary_df)["Optimal Value"].tolist() == [0.0, 0.0]


@pytest.mark.parametrize("zonal", [False, True], ids=["copperplate", "zonal"])
def test_hydro_reporting_leaves_vre_metrics_and_units_unchanged(zonal):
    model = _reporting_model("DailyBudgetUpperBoundFormulation", zonal=zonal)
    hosts = [model.area[area] for area in model.A] if zonal else [model]
    for host in hosts:
        for hour in host.h:
            host.pv.generation[hour].set_value(2.0)
            host.pv.curtailment[hour].set_value(3.0)

    summary = _collect(model).summary_df
    rows = summary.loc[summary["Metric"].isin(("Total VRE curtailment", "VRE curtailment percentage"))]

    assert rows["Technology"].tolist() == ["Solar PV", "Wind", "All", "All"]
    assert rows["Unit"].tolist() == ["MWh", "MWh", "MWh", "%"]
    curtailment = 144.0 if zonal else 72.0
    assert rows["Optimal Value"].tolist() == [curtailment, 0.0, curtailment, 60.0]


@pytest.mark.parametrize("zonal", [False, True], ids=["copperplate", "zonal"])
@pytest.mark.parametrize(
    "formulation",
    [
        "DailyBudgetFormulation",
        "DailyBudgetUpperBoundFormulation",
        "MonthlyBudgetFormulation",
        "MonthlyBudgetUpperBoundFormulation",
        "RunOfRiverFormulation",
    ],
)
def test_hydro_summary_csv_preserves_exact_rows(tmp_path, formulation, zonal):
    model = _reporting_model(formulation, zonal=zonal)
    hosts = [model.area[area] for area in model.A] if zonal else [model]
    for host in hosts:
        dispatch = 750_000.0 if zonal and host.index() == "A2" else 250_000.0
        if "UpperBound" in formulation:
            dispatch *= 0.5
        _set_hydro_generation(host, dispatch)
    results = _collect(model)

    export_results(results, case="hydro", output_dir=str(tmp_path))

    exported = pd.read_csv(tmp_path / "OutputSummary_hydro.csv")
    pd.testing.assert_frame_equal(_hydro_rows(exported), _hydro_rows(results.summary_df))


@pytest.mark.parametrize("zonal", [False, True], ids=["copperplate", "zonal"])
@pytest.mark.parametrize(
    ("formulation", "hours"),
    [("DailyBudgetUpperBoundFormulation", 24), ("MonthlyBudgetUpperBoundFormulation", 730)],
)
def test_solved_hydro_summary_matches_available_and_dispatched_energy(formulation, hours, *, zonal):
    model = initialize_model(_reporting_data(formulation, zonal=zonal), n_hours=hours)
    config = get_default_solver_config_dict(solver_name="highs", executable_path="")
    config["solve_keywords"].update(tee=False, report_timing=False, keepfiles=False)

    results = run_solver(model, config)

    assert results.termination_condition == "optimal"
    assert results.total_cost >= 0
    assert check_supply_balance_constraint(results)["is_satisfied"]
    hosts = [model.area[area] for area in model.A] if zonal else [model]
    for host in hosts:
        assert check_budget_constraint(host)["is_satisfied"]
    budget = hours * (1_000_000.0 if zonal else 250_000.0)
    dispatched = results.generation_df["Hydro Generation (MW)"].sum()
    unused = budget - dispatched
    assert unused > 0
    assert _hydro_rows(results.summary_df)["Optimal Value"].tolist() == pytest.approx(
        [unused / 1e6, 100.0 * unused / budget]
    )
