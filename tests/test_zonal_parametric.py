"""End-to-end smoke test for :class:`ParametricStudy` on the zonal fixture.

Covers the parametric pipeline
(load → mutate → initialize_model → run_solver → results) on the canonical
2-area zonal fixture under :data:`Data/zonal_test/`. The sweep varies a
single global scalar (``scalars.GenMix_Target``) so the mutation flows
through ``_build_per_area_data_slice`` (which references ``data["scalars"]``
by reference).

Each test verifies one slice of the contract documented in PRD §6 and
§8.2:

- ``OptimizationResults.is_zonal`` and ``.areas`` are populated;
- ``interregional_exchanges_df`` carries the PRD §2.4 schema with
  ``|L| * n_hours`` rows;
- the per-worker deep copy keeps :attr:`ParametricStudy._base_data`
  pristine across the run (PRD §10 picklability risk note);
- the swept parameter actually produces a different optimum.
"""

from __future__ import annotations

import copy
import os
import pickle

import pandas as pd
import pyomo.environ as pyo
import pytest

from sdom import load_data
from sdom.optimization_main import get_default_solver_config_dict
from sdom.parametric import ParametricStudy


REL_ZONAL_FIXTURE = "Data/zonal_test"
N_HOURS = 24

# Two-scenario sweep on a global scalar that the zonal slice reads by
# reference (``slice_dict["scalars"] = data["scalars"]`` in
# ``_build_per_area_data_slice``). 1.0 is the fixture's base value;
# 0.5 relaxes the renewable-share floor so the optimum drops.
GENMIX_TARGETS = [0.5, 1.0]

PRD_2_4_COLUMNS = [
    "line_id",
    "from_area",
    "to_area",
    "hour",
    "flow_signed_MW",
    "flow_FT_MW",
    "flow_TF_MW",
    "cap_FT_MW",
    "cap_TF_MW",
    "utilization_FT",
    "utilization_TF",
]


def _abs_data_path(rel: str) -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", rel))


def _highs_available() -> bool:
    for name in ("appsi_highs", "highs"):
        try:
            s = pyo.SolverFactory(name)
            if s is not None and s.available(exception_flag=False):
                return True
        except Exception:
            continue
    return False


# ---------------------------------------------------------------------------
# Module-scoped study run (one solve per scenario, shared across tests)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def zonal_study_run():
    if not _highs_available():
        pytest.skip("HiGHS solver not available")

    data = load_data(_abs_data_path(REL_ZONAL_FIXTURE))

    # Snapshot pre-run state for deep-copy verification.
    base_scalars_before = data["scalars"].copy(deep=True)
    base_per_area_demand_before = {
        a: df.copy(deep=True) for a, df in data["per_area_demand"].items()
    }

    solver_cfg = get_default_solver_config_dict(
        solver_name="highs",
        executable_path="",
    )
    solver_cfg["solve_keywords"]["tee"] = False
    solver_cfg["solve_keywords"]["report_timing"] = False
    solver_cfg["solve_keywords"]["keepfiles"] = False

    study = ParametricStudy(
        base_data=data,
        solver_config=solver_cfg,
        n_hours=N_HOURS,
        output_dir=None,
        n_cores=2,
    )
    study.add_scalar_sweep("scalars", "GenMix_Target", GENMIX_TARGETS)

    results = study.run()

    return {
        "study": study,
        "results": results,
        "data": data,
        "base_scalars_before": base_scalars_before,
        "base_per_area_demand_before": base_per_area_demand_before,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_all_scenarios_solve_optimally(zonal_study_run):
    """Both scenarios reach an optimal solution end-to-end."""
    results = zonal_study_run["results"]

    assert len(results) == len(GENMIX_TARGETS)
    for i, res in enumerate(results):
        assert res.is_optimal, (
            f"scenario {i} (GenMix_Target={GENMIX_TARGETS[i]}) "
            f"failed: solver_status={res.solver_status}, "
            f"termination={res.termination_condition}"
        )


def test_each_scenario_is_zonal_with_two_areas(zonal_study_run):
    """``is_zonal``/``areas`` populated by the zonal collector for every case."""
    for res in zonal_study_run["results"]:
        assert res.is_zonal is True
        assert set(res.areas) == {"A1", "A2"}
        assert {l["line_id"] for l in res.lines} == {"L_A1_A2"}


def test_interregional_exchanges_schema_and_row_count(zonal_study_run):
    """Each scenario's ``interregional_exchanges_df`` matches PRD §2.4."""
    for res in zonal_study_run["results"]:
        df = res.interregional_exchanges_df
        assert isinstance(df, pd.DataFrame)
        assert not df.empty
        assert list(df.columns) == PRD_2_4_COLUMNS
        # |L| * n_hours rows; |L| == 1 for the canonical fixture.
        assert len(df) == 1 * N_HOURS


def test_objective_values_are_positive_finite_and_differ(zonal_study_run):
    """Both objectives are positive and finite, and the sweep changes them."""
    costs = [res.total_cost for res in zonal_study_run["results"]]

    for c in costs:
        assert c is not None
        assert c > 0
        assert c == c  # not NaN
        assert c < float("inf")

    # Relaxing GenMix_Target from 1.0 to 0.5 must lower (or keep equal) the
    # optimum; the fixture's base load comfortably allows a strictly cheaper
    # mix at 0.5, so we require a non-trivial spread.
    assert abs(costs[0] - costs[1]) > 1.0, (
        f"Expected scenario costs to differ for GenMix_Target sweep; got "
        f"{costs[0]} vs {costs[1]}"
    )


def test_base_data_unchanged_after_run(zonal_study_run):
    """Per-worker deep copy keeps the parent ``base_data`` pristine.

    Mutating ``data["scalars"].loc["GenMix_Target", "Value"]`` inside a
    worker must not bleed into the parent process's data dict, and the
    per-area views (which the zonal builder reads from) must also be
    untouched on the parent side.
    """
    data = zonal_study_run["data"]
    before_scalars = zonal_study_run["base_scalars_before"]
    before_per_area_demand = zonal_study_run["base_per_area_demand_before"]

    # Global scalars: the row we swept is back to the original value.
    pd.testing.assert_frame_equal(data["scalars"], before_scalars)

    # Per-area demand views (consumed by the zonal slice) untouched.
    assert set(data["per_area_demand"].keys()) == set(before_per_area_demand.keys())
    for area_id, df_before in before_per_area_demand.items():
        pd.testing.assert_frame_equal(data["per_area_demand"][area_id], df_before)


def test_zonal_data_dict_is_pickleable(zonal_study_run):
    """Picklability lock for the multi-area ``data`` dict (PRD §10 risk)."""
    data = zonal_study_run["data"]

    # Round-trip through pickle: must succeed and preserve the per-area views.
    payload = pickle.dumps(data)
    restored = pickle.loads(payload)

    assert set(restored["per_area_demand"].keys()) == {"A1", "A2"}
    for a in ("A1", "A2"):
        pd.testing.assert_frame_equal(
            restored["per_area_demand"][a], data["per_area_demand"][a]
        )

    # Deep copy (the operation each worker performs on entry) also succeeds.
    deep = copy.deepcopy(data)
    assert set(deep["per_area_demand"].keys()) == {"A1", "A2"}
