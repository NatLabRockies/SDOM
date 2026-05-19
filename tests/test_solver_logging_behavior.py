"""Tests for solver output behavior in run_solver."""

from types import SimpleNamespace

from pyomo.opt import SolverStatus, TerminationCondition

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
