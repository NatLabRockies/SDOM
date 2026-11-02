"""Reserve-enabled counterparts of the unchanged hydro regression cases."""

from pathlib import Path

import pytest
from pyomo.environ import Constraint, Var, value
from test_capacity_margin import enable_reserves
from test_zonal_daily_hydro_budget import _daily_budget_fixture, _highs_config
from utils_tests import (
    CBC_EXECUTABLE,
    CBC_NOT_AVAILABLE_REASON,
    check_budget_constraint,
    check_hydro_budget_matches_csv,
    check_supply_balance_constraint,
    get_n_eq_ineq_constraints,
    get_optimization_problem_solution_info,
)

from sdom import get_default_solver_config_dict, initialize_model, load_data, run_solver

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    pytest.param("no_exchange_run_of_river", 24, 194, 765, None, id="run-of-river"),
    pytest.param(
        "no_exchange_monthly_hydro_budget_multiple_balancing_p50", 730, 5113, 32141, 730, id="monthly"
    ),
    pytest.param("no_exchange_hydro_daily_budget_multiple_balancing_p95", 168, 1185, 7413, 24, id="daily"),
    pytest.param(
        "exchange_hydro_daily_budget_multiple_balancing_p95", 168, 1185, 8421, 24, id="daily-exchange"
    ),
]
EXPECTED = {
    "no_exchange_run_of_river": (
        3285154848.663223,
        26681.257521483964,
        0.0,
        1254.8104356595381,
        1340.7415193427717,
    ),
    "no_exchange_monthly_hydro_budget_multiple_balancing_p50": (
        441627.4738187364,
        0.5101603982069823,
        0.0,
        0.0,
        0.0,
    ),
    "no_exchange_hydro_daily_budget_multiple_balancing_p95": (
        578101.3102049921,
        0.7473687598678558,
        0.0,
        0.0,
        0.0,
    ),
    "exchange_hydro_daily_budget_multiple_balancing_p95": (-77686751.8882038, 1.0, 1.0, 0.0, 0.0),
    "zonal": (
        8231806786.052223,
        49227.36258708384,
        4047.8935031493993,
        1343.6108653816261,
        10861.252403005956,
    ),
}


def assert_enabled_solution(results, expected):
    """Lock enabled optima and significant build decisions within solver precision."""
    solution = get_optimization_problem_solution_info(results)
    keys = ("Total_Cost", "Total_CapWind", "Total_CapPV", "Total_CapScha_Li-Ion", "Total_CapScha_CAES")
    for key, target in zip(keys, expected, strict=True):
        assert solution[key] == pytest.approx(target, abs=10 if key == "Total_Cost" else 0.01, rel=0)
    for technology in ("PHS", "H2"):
        assert solution[f"Total_CapScha_{technology}"] == pytest.approx(0, abs=0.01)


def assert_hourly_physics(host, *, margin=0.04, relative_tolerance=0):
    """Check capability independently and all baseline/new constraint residuals."""
    for h in host.h:
        storage = host.storage
        activated = sum(
            value(storage.PD[h, j] - storage.PC[h, j] + host.reserves.storage_upward_capability[h, j])
            for j in storage.j
        )
        available = (
            sum(value(host.thermal.plant_installed_capacity[k]) for k in host.thermal.plants_set)
            + activated
            + sum(
                value(vre.capacity_factor[h, p] * vre.max_capacity[p] * vre.capacity_fraction[p])
                for vre in (host.pv, host.wind)
                for p in vre.plants_set
            )
            + value(
                host.hydro.generation[h]
                + host.nuclear.alpha * host.nuclear.ts_parameter[h]
                + host.other_renewables.alpha * host.other_renewables.ts_parameter[h]
            )
        )
        assert available >= (1 + margin) * value(host.demand.ts_parameter[h]) - 1e-5
        for j in storage.j:
            output = value(host.reserves.storage_activated_net_output[h, j])
            assert output <= value(storage.Pdis[j]) + 1e-5
            assert output <= (
                value(storage.data["Eff", j]) ** 0.5 * value(storage.SOC[host.h.prevw(h), j]) + 1e-5
            )
    for constraint in host.component_data_objects(Constraint, active=True):
        body = value(constraint.body)
        if constraint.has_lb():
            lower = value(constraint.lower)
            assert body >= lower - 1e-3 - relative_tolerance * abs(lower), constraint.name
        if constraint.has_ub():
            upper = value(constraint.upper)
            assert body <= upper + 1e-3 + relative_tolerance * abs(upper), constraint.name


@pytest.mark.parametrize(("folder", "hours", "equalities", "inequalities", "budget_hours"), CASES)
def test_four_percent_hydro_construction(folder, hours, *, equalities, inequalities, budget_hours):
    data = enable_reserves(load_data(str(ROOT / "Data" / folder)))
    model = initialize_model(data, n_hours=hours)
    assert get_n_eq_ineq_constraints(model) == {"equality": equalities, "inequality": inequalities}
    assert len(model.reserves.storage_upward_capability) == hours * len(model.storage.j)


@pytest.mark.parametrize(
    ("folder", "hours", "equalities", "inequalities", "budget_hours", "solver"),
    [
        pytest.param(
            *case.values,
            solver,
            id=f"{case.id}-{solver}",
            marks=(
                pytest.mark.skipif(CBC_EXECUTABLE is None, reason=CBC_NOT_AVAILABLE_REASON)
                if solver == "cbc"
                else ()
            ),
        )
        for index, case in enumerate(CASES)
        for solver in (("highs", "cbc") if index < 2 else ("highs",))
    ],
)
def test_four_percent_hydro_solves(folder, hours, *, equalities, inequalities, budget_hours, solver):
    path = ROOT / "Data" / folder
    model = initialize_model(enable_reserves(load_data(str(path))), n_hours=hours)
    config = get_default_solver_config_dict(
        solver_name=solver, executable_path=CBC_EXECUTABLE if solver == "cbc" else ""
    )
    config["solve_keywords"].update(tee=False, report_timing=False, keepfiles=False)
    results = run_solver(model, config)
    assert results.termination_condition == "optimal"
    assert_enabled_solution(results, EXPECTED[folder])
    # CBC's text solution stores eight significant digits; summed MWh inherit that rounding.
    relative_tolerance = 2e-8 if solver == "cbc" else 0
    assert_hourly_physics(model, relative_tolerance=relative_tolerance)
    balance = check_supply_balance_constraint(results)
    assert balance["is_satisfied"], balance
    exchange = folder.startswith("exchange_")
    assert balance["has_exports"] == exchange
    if not exchange:
        assert not balance["has_imports"]
    if budget_hours:
        tolerance = 1e-3 + relative_tolerance * max(
            abs(value(c.lower)) for c in model.hydro.budget_constraint.values()
        )
        budget = check_budget_constraint(model, block_name="hydro", tolerance=tolerance)
        assert budget["is_satisfied"], budget
        assert budget["n_budget_periods"] == hours // budget_hours
        csv_budget = check_hydro_budget_matches_csv(
            results, path, budget_hours=budget_hours, tolerance=tolerance
        )
        assert csv_budget["is_satisfied"], csv_budget


def test_four_percent_zonal_daily_budget_builds_and_solves(tmp_path):
    path = _daily_budget_fixture(tmp_path)
    data = enable_reserves(load_data(str(path)))
    model = initialize_model(data, n_hours=168)
    assert not hasattr(model, "reserves")
    assert all(len(model.area[a].reserves.Capability) == 168 for a in model.A)
    assert get_n_eq_ineq_constraints(model) == {"equality": 2370, "inequality": 13313}
    results = run_solver(model, _highs_config())
    assert results.termination_condition == "optimal"
    assert_enabled_solution(results, EXPECTED["zonal"])
    assert check_supply_balance_constraint(results)["is_satisfied"]
    for a in model.A:
        assert_hourly_physics(model.area[a])
        budget = check_budget_constraint(model.area[a])
        assert budget["is_satisfied"], budget
        assert budget["n_budget_periods"] == 7
    csv_budget = check_hydro_budget_matches_csv(results, path, budget_hours=24)
    assert csv_budget["is_satisfied"], csv_budget
    assert csv_budget["n_budget_periods"] == 7
    assert all(value(model.area[a].reserves.capacity_marging_fraction) == 0.04 for a in model.A)
    assert sum(v.is_binary() for v in model.component_data_objects(Var)) == 1344


@pytest.mark.parametrize(
    ("folder", "hours", "bound", "message"),
    [
        ("no_exchange_hydro_daily_budget_multiple_balancing_p95", 24, "large_hydro_min", "lower"),
        ("no_exchange_monthly_hydro_budget_multiple_balancing_p50", 730, "large_hydro_max", "upper"),
    ],
)
def test_four_percent_margin_preserves_hydro_budget_validation(folder, hours, *, bound, message):
    data = enable_reserves(load_data(str(ROOT / "Data" / folder)))
    if bound == "large_hydro_min":
        data["large_hydro_data"].loc[data["large_hydro_data"]["*Hour"] <= hours, "LargeHydro"] = 0
    else:
        data[bound].loc[data[bound]["*Hour"] <= hours, "LargeHydro"] = 0
    with pytest.raises(ValueError, match=rf"Infeasible hydro budget input.*\n- .*{message}"):
        initialize_model(data, n_hours=hours)


def test_four_percent_margin_preserves_zonal_hydro_budget_validation(tmp_path):
    data = enable_reserves(load_data(str(_daily_budget_fixture(tmp_path))))
    hydro = data["per_area_hydro"]["A1"]
    hydro.loc[hydro["*Hour"] <= 24, "LargeHydro"] = 0
    hydro.loc[hydro["*Hour"] <= 24, "LargeHydro_Min"] = 1
    with pytest.raises(ValueError, match=r"DailyBudgetFormulation.*area 'A1'.*lower"):
        initialize_model(data, n_hours=24)


def test_increased_margin_raises_cost_with_hourly_feasibility_preserved():
    data = enable_reserves(load_data(str(ROOT / "Data" / "no_exchange_run_of_river")))
    costs = []
    for margin in (0.0, 0.5):
        data["scalars"].loc["capacity_marging_fraction", "Value"] = margin
        model = initialize_model(data, n_hours=24)
        results = run_solver(model, _highs_config())
        assert results.is_optimal
        assert_hourly_physics(model, margin=margin)
        assert check_supply_balance_constraint(results)["is_satisfied"]
        costs.append(results.total_cost)
    assert costs[1] > costs[0] + 100
