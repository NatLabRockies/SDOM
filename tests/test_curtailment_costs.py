"""Optional technology-specific curtailment costs through the SDOM API."""

from pathlib import Path

import pandas as pd
import pytest
from pyomo.environ import Constraint, Var, value
from pyomo.opt import SolverResults
from utils_tests import check_budget_constraint, check_supply_balance_constraint

from sdom import export_results, get_default_solver_config_dict, initialize_model, load_data, run_solver
from sdom.results import collect_results_from_model

ROOT = Path(__file__).resolve().parents[1]
RATES = ("SolarCurtailmentCost", "WindCurtailmentCost", "HydroCurtailmentCost")
METRICS = (
    "Total Solar curtailment cost",
    "Total Wind curtailment cost",
    "Total Hydro curtailment cost",
)
TECHNOLOGIES = ("Solar PV", "Wind", "Hydro")


def cost_data(*, rates=(), zonal=False, formulation="DailyBudgetUpperBoundFormulation", alpha=0.5):
    """Control profiles in real inputs without changing shared datasets."""
    folder = "zonal_test" if zonal else "no_exchange_hydro_daily_budget_multiple_balancing_p95"
    data = load_data(str(ROOT / "Data" / folder))
    data["formulations"].loc[data["formulations"]["Component"] == "Hydro", "Formulation"] = formulation
    data["scalars"].loc["AlphaLargHy", "Value"] = alpha
    for parameter, rate in rates:
        data["scalars"].loc[parameter, "Value"] = rate
    if zonal:
        for area, hydro in data["per_area_hydro"].items():
            hydro["LargeHydro"] = 10.0 if area == "A1" else 30.0
            hydro["LargeHydro_Min"] = 0.0
            hydro["LargeHydro_Max"] = 100.0
    else:
        data["large_hydro_data"]["LargeHydro"] = 10.0
        data["large_hydro_min"]["LargeHydro"] = 0.0
        data["large_hydro_max"]["LargeHydro"] = 100.0
    return data


def assign_dispatch(model):
    """Assign reporting values, not a purported optimal or feasible solution."""
    for variable in model.component_data_objects(Var):
        variable.set_value(max(0.0, variable.lb or 0.0))
    hosts = [model.area[area] for area in model.A] if hasattr(model, "A") else [model]
    for host in hosts:
        for hour in host.h:
            host.pv.curtailment[hour].set_value(2.0)
            host.wind.curtailment[hour].set_value(3.0)
            host.hydro.generation[hour].set_value(4.0)


def collect(model):
    """Collect assigned values without claiming solver optimality."""
    return collect_results_from_model(model, SolverResults())


@pytest.mark.parametrize(
    ("rates", "expected"),
    [
        ((), (0.0, 0.0, 0.0)),
        (tuple(zip(RATES, (0.0, 0.0, 0.0), strict=True)), (0.0, 0.0, 0.0)),
        (((RATES[0], 5.0),), (240.0, 0.0, 0.0)),
        (((RATES[1], 10.0),), (0.0, 720.0, 0.0)),
        (((RATES[2], 20.0),), (0.0, 0.0, 2880.0)),
        (((RATES[0], 5.0), (RATES[2], 20.0)), (240.0, 0.0, 2880.0)),
        (tuple(zip(RATES, (5.0, 10.0, 20.0), strict=True)), (240.0, 720.0, 2880.0)),
        (tuple(zip(RATES, (-5.0, -10.0, -20.0), strict=True)), (-240.0, -720.0, -2880.0)),
    ],
)
@pytest.mark.parametrize("zonal", [False, True])
def test_rates_independently_contribute_signed_linear_costs_without_new_decisions(rates, expected, zonal):
    baseline = initialize_model(cost_data(zonal=zonal), n_hours=1)
    model = initialize_model(cost_data(rates=rates, zonal=zonal), n_hours=1)
    assign_dispatch(baseline)
    assign_dispatch(model)
    for component in (Var, Constraint):
        assert [item.name for item in model.component_data_objects(component)] == [
            item.name for item in baseline.component_data_objects(component)
        ]
    hosts = [model.area[area] for area in model.A] if zonal else [model]
    actual = [
        sum(value(getattr(host, technology).curtailment_cost_expr) for host in hosts)
        for technology in ("pv", "wind", "hydro")
    ]
    # A2 has 20 extra MWh of available hydro per hour; VRE values are identical.
    expected_system = list(expected)
    if zonal:
        expected_system = [2 * item for item in expected]
        expected_system[2] += dict(rates).get(RATES[2], 0.0) * 480.0
    assert actual == pytest.approx(expected_system)
    assert value(model.Obj) - value(baseline.Obj) == pytest.approx(sum(expected_system), abs=1e-5)
    assert model.Obj.expr.polynomial_degree() == 1


@pytest.mark.parametrize("parameter", RATES)
@pytest.mark.parametrize("invalid", ["", "not-a-number", None, float("nan"), float("inf"), -float("inf")])
def test_supplied_rates_must_be_numeric_and_finite(parameter, invalid):
    data = cost_data()
    data["scalars"] = data["scalars"].astype(object)
    data["scalars"].loc[parameter, "Value"] = invalid
    with pytest.raises(ValueError, match=parameter):
        initialize_model(data, n_hours=24)


@pytest.mark.parametrize("parameter", RATES)
def test_duplicate_rates_are_rejected_even_when_zero(parameter):
    data = cost_data()
    data["scalars"] = pd.concat(
        [data["scalars"], pd.DataFrame({"Value": [0.0, 0.0]}, index=pd.Index([parameter, parameter]))]
    )
    with pytest.raises(ValueError, match=parameter):
        initialize_model(data, n_hours=24)


@pytest.mark.parametrize("zonal", [False, True])
@pytest.mark.parametrize("sign", [0.0, 1.0, -1.0])
def test_summary_costs_reconcile_with_objective_area_totals_and_export(tmp_path, zonal, sign):
    rates = tuple(zip(RATES, (sign * 5, sign * 10, sign * 20), strict=True))
    model = initialize_model(cost_data(rates=rates, zonal=zonal), n_hours=24)
    assign_dispatch(model)
    results = collect(model)
    expected = [sign * item for item in ((480, 1440, 15360) if zonal else (240, 720, 2880))]
    assert results.cost_breakdown["curtailment_cost"] == pytest.approx(
        dict(zip(TECHNOLOGIES, expected, strict=True))
    )
    rows = results.get_summary_dataframe().loc[lambda frame: frame["Metric"].isin(METRICS)]
    assert rows["Metric"].tolist() == list(METRICS)
    assert rows["Technology"].tolist() == list(TECHNOLOGIES)
    assert rows["Unit"].tolist() == ["$US"] * 3
    assert rows["Optimal Value"].tolist() == pytest.approx(expected)
    assert results.total_cost == pytest.approx(value(model.Obj))
    costs = results.cost_breakdown
    existing = sum(costs[key]["All"] for key in ("capex", "power_capex", "energy_capex", "fom", "vom"))
    existing += costs["fuel_cost"]["Thermal"] + costs["imports_cost"] - costs["exports_revenue"]
    assert results.total_cost == pytest.approx(existing + sum(expected))
    if zonal:
        for technology, total in zip(TECHNOLOGIES, expected, strict=True):
            assert (
                sum(area["curtailment_cost"][technology] for area in results.area_cost_breakdown.values())
                == total
            )
        area_totals = []
        for area, summary in results.area_summary_df.items():
            area_rows = summary.loc[summary["Metric"].isin(METRICS)]
            assert area_rows["Technology"].tolist() == list(TECHNOLOGIES)
            assert area_rows["Optimal Value"].tolist() == list(
                results.area_cost_breakdown[area]["curtailment_cost"].values()
            )
            area_totals.append(summary.loc[summary["Metric"] == "Total cost", "Optimal Value"].item())
        assert sum(area_totals) == pytest.approx(results.total_cost)
    export_results(results, case="curtailment", output_dir=str(tmp_path))
    exported = pd.read_csv(tmp_path / "OutputSummary_curtailment.csv")
    assert exported.columns.tolist() == ["Metric", "Technology", "Run", "Optimal Value", "Unit"]
    assert exported.loc[exported["Metric"].isin(METRICS), "Optimal Value"].tolist() == pytest.approx(expected)


@pytest.mark.parametrize("zonal", [False, True])
@pytest.mark.parametrize("technology", ["pv", "wind", "hydro"])
@pytest.mark.parametrize("invalid", [None, float("nan"), float("inf")])
def test_collection_rejects_missing_nonfinite_enabled_costs(zonal, technology, invalid):
    model = initialize_model(
        cost_data(rates=tuple(zip(RATES, (5, 10, 20), strict=True)), zonal=zonal), n_hours=24
    )
    assign_dispatch(model)
    host = model.area["A1"] if zonal else model
    getattr(host, technology).curtailment_cost_expr.set_value(invalid)
    with pytest.raises(ValueError, match=r"curtailment.*cost"):
        collect(model)


@pytest.mark.parametrize("zonal", [False, True])
@pytest.mark.parametrize(
    ("formulation", "requested", "hours", "eligible"),
    [
        ("RunOfRiverFormulation", 25, 25, False),
        ("DailyBudgetFormulation", 25, 48, False),
        ("MonthlyBudgetFormulation", 731, 1460, False),
        ("DailyBudgetUpperBoundFormulation", 25, 48, True),
        ("MonthlyBudgetUpperBoundFormulation", 731, 1460, True),
    ],
)
def test_hydro_cost_uses_only_complete_upper_bound_budgets(formulation, requested, *, hours, eligible, zonal):
    model = initialize_model(
        cost_data(rates=((RATES[2], 7),), zonal=zonal, formulation=formulation), n_hours=requested
    )
    assign_dispatch(model)
    assert len(model.h) == hours
    hosts = [model.area[area] for area in model.A] if zonal else [model]
    for host in hosts:
        profile = 30.0 if zonal and host.index() == "A2" else 10.0
        # Half the hours exceed the profile. Only the period residual is charged.
        interval = 730 if "Monthly" in formulation else 24
        for hour in host.h:
            if eligible:
                dispatch = profile * (1.5 if (hour - 1) % interval < interval // 2 else 0.1)
            else:
                dispatch = profile if "Budget" in formulation else 0.5 * profile
            host.hydro.generation[hour].set_value(dispatch)
        expected = 7 * hours * profile * 0.2 if eligible else 0.0
        assert value(host.hydro.curtailment_cost_expr) == pytest.approx(expected)
    costs = collect(model).cost_breakdown["curtailment_cost"]
    assert costs["Hydro"] == pytest.approx(7 * hours * (40 if zonal else 10) * 0.2 if eligible else 0)


@pytest.mark.parametrize("budget", [0.0, 10.0])
@pytest.mark.parametrize("zonal", [False, True])
def test_zero_hydro_dispatch_capability_still_charges_positive_budget(budget, zonal):
    data = cost_data(rates=((RATES[2], 20),), zonal=zonal, alpha=0)
    if zonal:
        for hydro in data["per_area_hydro"].values():
            hydro["LargeHydro"] = budget
    else:
        data["large_hydro_data"]["LargeHydro"] = budget
    model = initialize_model(data, n_hours=24)
    assign_dispatch(model)
    hosts = [model.area[area] for area in model.A] if zonal else [model]
    for host in hosts:
        for hour in host.h:
            host.hydro.generation[hour].set_value(0.0)
    assert collect(model).cost_breakdown["curtailment_cost"]["Hydro"] == 480 * budget * len(hosts)


@pytest.mark.parametrize("zonal", [False, True])
def test_empty_vre_fleets_are_safe_and_only_resource_owning_areas_incur_cost(zonal):
    data = cost_data(rates=tuple(zip(RATES, (5, 10, 20), strict=True)), zonal=zonal)
    if zonal:
        data["per_area_pv_plants"]["A1"] = data["per_area_pv_plants"]["A1"].iloc[:0].copy()
        data["per_area_wind_plants"]["A2"] = data["per_area_wind_plants"]["A2"].iloc[:0].copy()
    else:
        data["cap_solar"] = data["cap_solar"].iloc[:0].copy()
        data["cap_wind"] = data["cap_wind"].iloc[:0].copy()
    model = initialize_model(data, n_hours=24)
    assign_dispatch(model)
    results = collect(model)
    assert results.cost_breakdown["curtailment_cost"]["Solar PV"] == (240 if zonal else 0)
    assert results.cost_breakdown["curtailment_cost"]["Wind"] == (720 if zonal else 0)
    if zonal:
        assert results.area_cost_breakdown["A1"]["curtailment_cost"]["Solar PV"] == 0
        assert results.area_cost_breakdown["A2"]["curtailment_cost"]["Wind"] == 0


@pytest.mark.parametrize(
    "formulation", ["DailyBudgetUpperBoundFormulation", "MonthlyBudgetUpperBoundFormulation"]
)
def test_missing_area_hydro_has_zero_budget_bounds_and_cost(formulation):
    data = cost_data(rates=((RATES[2], 20),), zonal=True, formulation=formulation)
    del data["per_area_hydro"]["A1"]
    model = initialize_model(data, n_hours=1)
    assign_dispatch(model)
    for hour in model.h:
        model.area["A1"].hydro.generation[hour].set_value(0)
    results = collect(model)
    assert results.area_cost_breakdown["A1"]["curtailment_cost"]["Hydro"] == 0
    assert results.cost_breakdown["curtailment_cost"]["Hydro"] == pytest.approx(20 * 26 * len(model.h))


def test_hydro_reporting_tolerance_does_not_clip_objective_cost():
    model = initialize_model(cost_data(rates=((RATES[2], 20),)), n_hours=24)
    assign_dispatch(model)
    for hour in model.h:
        model.hydro.generation[hour].set_value(10.0)
    model.hydro.generation[1].set_value(10.0005)
    results = collect(model)
    assert results.summary_df.loc[
        results.summary_df["Metric"] == "Total Hydro curtailment", "Optimal Value"
    ].item() == 0
    assert results.cost_breakdown["curtailment_cost"]["Hydro"] == pytest.approx(-0.01)


def test_missing_enabled_expression_is_an_explicit_collection_error():
    model = initialize_model(cost_data(rates=((RATES[0], 5),)), n_hours=24)
    assign_dispatch(model)
    model.pv.del_component("curtailment_cost_expr")
    with pytest.raises(ValueError, match=r"Missing.*curtailment cost.*Solar PV"):
        collect(model)


@pytest.mark.parametrize("zonal", [False, True])
def test_omitted_rates_emit_zero_rows_without_changing_existing_metrics(zonal):
    omitted = initialize_model(cost_data(zonal=zonal), n_hours=24)
    zero = initialize_model(
        cost_data(zonal=zonal, rates=tuple(zip(RATES, (0, 0, 0), strict=True))), n_hours=24
    )
    assign_dispatch(omitted)
    assign_dispatch(zero)
    first, second = collect(omitted), collect(zero)
    pd.testing.assert_frame_equal(first.summary_df, second.summary_df)
    assert first.summary_df.loc[first.summary_df["Metric"].isin(METRICS), "Optimal Value"].tolist() == [
        0,
        0,
        0,
    ]


def dispatch_choice_data(*, zonal=False, formulation="DailyBudgetUpperBoundFormulation"):
    """Reduce real inputs to three fixed 10 MW resources competing for 10 MW demand."""
    data = cost_data(zonal=zonal, formulation=formulation, alpha=1.0)
    data["scalars"].loc[["AlphaNuclear", "AlphaOtheRe"], "Value"] = 0.0
    data["scalars"].loc["GenMix_Target", "Value"] = 1.0
    for key in ("cap_solar", "cap_wind"):
        table = data[key]
        table["capacity"] = 10.0 / len(table)
        table["MinCapacity"] = table["capacity"]
        table[["CAPEX_M", "FOM_M", "trans_cap_cost"]] = 0.0
    for key in ("cf_solar", "cf_wind"):
        data[key].iloc[:, 1:] = 1.0
    data["load_data"].iloc[:, 1:] = 10.0
    data["thermal_data"] = data["thermal_data"].iloc[:0].copy()
    data["storage_data"] = data["storage_data"].iloc[:, :0].copy()
    data["STORAGE_SET_J_TECHS"] = []
    data["STORAGE_SET_B_TECHS"] = []
    if zonal:
        for key in ("per_area_pv_plants", "per_area_wind_plants"):
            for table in data[key].values():
                table["capacity"] = 10.0 / len(table)
                table["MinCapacity"] = table["capacity"]
                table[["CAPEX_M", "FOM_M", "trans_cap_cost"]] = 0.0
        for key in ("per_area_capacity_factors_pv", "per_area_capacity_factors_wind", "per_area_demand"):
            for table in data[key].values():
                table.iloc[:, 1:] = 10.0 if key == "per_area_demand" else 1.0
        for hydro in data["per_area_hydro"].values():
            hydro["LargeHydro"] = 10.0
            hydro["LargeHydro_Max"] = 10.0
        for area in data["per_area_balancing_units"]:
            data["per_area_balancing_units"][area] = data["thermal_data"].copy()
            data["per_area_storage"][area] = data["storage_data"].copy()
    return data


@pytest.mark.parametrize("technology", TECHNOLOGIES)
@pytest.mark.parametrize("zonal", [False, True])
@pytest.mark.parametrize(
    ("formulation", "hours"),
    [("DailyBudgetUpperBoundFormulation", 24), ("MonthlyBudgetUpperBoundFormulation", 730)],
)
def test_signed_rate_changes_dispatch_preference_and_reconciles_solved_objective(
    technology, zonal, *, formulation, hours
):
    parameter = RATES[TECHNOLOGIES.index(technology)]
    config = get_default_solver_config_dict(solver_name="highs", executable_path="")
    config["solve_keywords"].update(tee=False, report_timing=False, keepfiles=False)
    selected_generation = []
    for selected_rate in (20.0, -20.0):
        data = dispatch_choice_data(zonal=zonal, formulation=formulation)
        for rate in RATES:
            data["scalars"].loc[rate, "Value"] = selected_rate if rate == parameter else 1.0
        model = initialize_model(data, n_hours=hours)
        results = run_solver(model, config)
        assert results.is_optimal
        assert check_supply_balance_constraint(results)["is_satisfied"]
        hosts = [model.area[area] for area in model.A] if zonal else [model]
        for host in hosts:
            assert check_budget_constraint(host)["is_satisfied"]
        energy = hours * 10 * len(hosts)
        selected_generation.append(results.generation_totals[technology])
        assert results.capacity["Solar PV"] == pytest.approx(10 * len(hosts))
        assert results.capacity["Wind"] == pytest.approx(10 * len(hosts))
        assert results.total_cost == pytest.approx(
            (2 * energy) if selected_rate > 0 else (-19 * energy), abs=1e-5
        )
        assert sum(results.cost_breakdown["curtailment_cost"].values()) == pytest.approx(results.total_cost)
        assert results.cost_breakdown["curtailment_cost"][technology] == pytest.approx(
            0 if selected_rate > 0 else -20 * energy, abs=1e-5
        )
    assert selected_generation == pytest.approx([energy, 0], abs=1e-5)
