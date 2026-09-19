"""Tests for solver output behavior in run_solver."""

from types import SimpleNamespace

import pandas as pd
import pyomo.environ as pyo
from pyomo.opt import SolverStatus, TerminationCondition

from sdom.optimization_main import _collect_fixed_decision_marginal_prices
from sdom.optimization_main import _fix_pricing_decisions, get_default_solver_config_dict
from sdom.optimization_main import run_solver
from sdom.results import OptimizationResults


class _FakeSolver:
    def __init__(self):
        self.last_kwargs = None

    def solve(self, model, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(
            solver=SimpleNamespace(
                status=SolverStatus.ok,
                termination_condition=TerminationCondition.optimal,
            ),
            problem=[],
        )


class _FakeModel:
    GenMix_Target = SimpleNamespace(value=0.5)


class _CloneFailureModel:
    h = [1]

    def clone(self):
        raise RuntimeError("clone failed")


def test_solver_config_defaults_to_quiet_streaming():
    cfg = get_default_solver_config_dict(solver_name="highs")
    assert cfg["solve_keywords"]["tee"] is False


def test_solver_config_allows_streaming_opt_in():
    cfg = get_default_solver_config_dict(
        solver_name="highs",
        stream_solver_output=True,
    )
    assert cfg["solve_keywords"]["tee"] is True


def test_run_solver_disables_tee_for_appsi_highs(monkeypatch):
    fake_solver = _FakeSolver()

    monkeypatch.setattr("sdom.optimization_main.configure_solver", lambda _cfg: fake_solver)
    monkeypatch.setattr(
        "sdom.optimization_main.collect_results_from_model",
        lambda _model, _solver_result, _case_name: OptimizationResults(
            termination_condition="optimal",
            solver_status="ok",
        ),
    )

    cfg = {
        "solver_name": "appsi_highs",
        "solve_keywords": {
            "tee": True,
            "load_solutions": True,
            "timelimit": None,
            "report_timing": False,
            "keepfiles": False,
        },
    }

    run_solver(_FakeModel(), cfg)

    assert fake_solver.last_kwargs is not None
    assert fake_solver.last_kwargs["tee"] is False


def test_run_solver_keeps_tee_for_non_appsi_highs(monkeypatch):
    fake_solver = _FakeSolver()

    monkeypatch.setattr("sdom.optimization_main.configure_solver", lambda _cfg: fake_solver)
    monkeypatch.setattr(
        "sdom.optimization_main.collect_results_from_model",
        lambda _model, _solver_result, _case_name: OptimizationResults(
            termination_condition="optimal",
            solver_status="ok",
        ),
    )

    cfg = {
        "solver_name": "cbc",
        "solve_keywords": {
            "tee": True,
            "load_solutions": True,
            "timelimit": None,
            "report_timing": False,
            "keepfiles": False,
        },
    }

    run_solver(_FakeModel(), cfg)

    assert fake_solver.last_kwargs is not None
    assert fake_solver.last_kwargs["tee"] is True


def test_run_solver_passes_configured_solver_to_pricing(monkeypatch):
    fake_solver = _FakeSolver()
    pricing_configs = []

    monkeypatch.setattr("sdom.optimization_main.configure_solver", lambda _cfg: fake_solver)
    monkeypatch.setattr(
        "sdom.optimization_main.collect_results_from_model",
        lambda _model, _solver_result, _case_name: OptimizationResults(
            termination_condition="optimal",
            solver_status="ok",
        ),
    )
    monkeypatch.setattr(
        "sdom.optimization_main._collect_fixed_decision_marginal_prices",
        lambda _model, solver_config: (
            pricing_configs.append(solver_config) or (None, None)
        ),
    )

    cfg = {
        "solver_name": "cbc",
        "solve_keywords": {
            "tee": False,
            "load_solutions": True,
            "timelimit": None,
            "report_timing": False,
            "keepfiles": False,
        },
    }

    run_solver(_FakeModel(), cfg)

    assert pricing_configs == [cfg]


def test_fixed_decision_pricing_disables_tee_for_appsi_highs(monkeypatch):
    fake_solver = _FakeSolver()
    model = pyo.ConcreteModel()
    model.h = pyo.Set(initialize=[1])
    model.dispatch = pyo.Var()
    model.SupplyBalance = pyo.Constraint(expr=model.dispatch == 0)

    monkeypatch.setattr(
        "sdom.optimization_main.configure_solver", lambda _cfg: fake_solver
    )

    _collect_fixed_decision_marginal_prices(
        model,
        {
            "solver_name": "appsi_highs",
            "solve_keywords": {
                "tee": True,
                "load_solutions": True,
                "timelimit": None,
                "report_timing": False,
                "keepfiles": False,
            },
        },
    )

    assert fake_solver.last_kwargs["tee"] is False


def test_fixed_decision_pricing_reports_clone_failure_as_unavailable():
    prices, line_duals = _collect_fixed_decision_marginal_prices(
        _CloneFailureModel(),
        {"solver_name": "appsi_highs", "solve_keywords": {}},
    )

    assert list(prices["pricing_status"]) == ["unavailable_pricing_lp"]
    assert pd.isna(prices.loc[0, "marginal_price_USD_per_MWh"])
    assert line_duals.empty


def test_fix_pricing_decisions_fixes_incumbent_investment_variables():
    model = pyo.ConcreteModel()
    model.binary_choice = pyo.Var(domain=pyo.Binary, initialize=1)
    model.integer_choice = pyo.Var(domain=pyo.Integers, initialize=2)
    model.capacity_fraction = pyo.Var(initialize=0.25)
    model.plant_installed_capacity = pyo.Var(initialize=10.0)
    model.Pcha = pyo.Var(initialize=3.0)
    model.Pdis = pyo.Var(initialize=4.0)
    model.Ecap = pyo.Var(initialize=5.0)
    model.dispatch = pyo.Var(initialize=6.0)

    _fix_pricing_decisions(model)

    for variable, expected_value in (
        (model.binary_choice, 1),
        (model.integer_choice, 2),
        (model.capacity_fraction, 0.25),
        (model.plant_installed_capacity, 10.0),
        (model.Pcha, 3.0),
        (model.Pdis, 4.0),
        (model.Ecap, 5.0),
    ):
        assert variable.fixed
        assert pyo.value(variable) == expected_value
    assert not model.dispatch.fixed
