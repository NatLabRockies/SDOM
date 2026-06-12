from __future__ import annotations

from pathlib import Path

import pyomo.environ as pyo
import pytest

from sdom.optimization_main import get_default_solver_config_dict
from sdom.resiliency import OutageSpec


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def legacy_data_path() -> Path:
    return REPO_ROOT / "Data" / "no_exchange_run_of_river"


@pytest.fixture(scope="session")
def zonal_data_path() -> Path:
    return REPO_ROOT / "Data" / "zonal_test"


@pytest.fixture(scope="session")
def resiliency_snapshot_dir() -> Path:
    from _resiliency_fixtures import SNAPSHOT_DIR_MEA

    return SNAPSHOT_DIR_MEA


@pytest.fixture(scope="session")
def resiliency_inputs_dir() -> Path:
    from _resiliency_fixtures import INPUTS_DIR_MEA

    return INPUTS_DIR_MEA


@pytest.fixture(scope="session")
def outage_spec_small() -> OutageSpec:
    return OutageSpec(
        duration_hours=2,
        recovery_hours=2,
        outaged_assets={"imports": "all"},
    )


@pytest.fixture(scope="session")
def highs_solver_available() -> bool:
    for name in ("appsi_highs", "highs"):
        try:
            solver = pyo.SolverFactory(name)
            if solver is not None and solver.available(exception_flag=False):
                return True
        except Exception:
            continue
    return False


@pytest.fixture(scope="session")
def highs_solver_config(highs_solver_available: bool) -> dict:
    if not highs_solver_available:
        pytest.skip("HiGHS solver not available")

    config = get_default_solver_config_dict(solver_name="highs")
    config["solve_keywords"]["tee"] = False
    config["solve_keywords"]["report_timing"] = False
    config["solve_keywords"]["keepfiles"] = False
    return config
