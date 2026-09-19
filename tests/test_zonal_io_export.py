"""Tests for zonal-aware CSV export in :func:`sdom.io_manager.export_results`.

Covers emission of ``OutputInterregionalExchanges_{case}.csv``
when the optimization results contain a non-empty ``interregional_exchanges_df``.

Legacy single-area runs must NOT produce this file. The export is a pure
side-effect on top of :func:`_export_from_results_object`; the CSV schema
matches PRD §2.4 and the row count is ``|L| * n_hours``.
"""

from __future__ import annotations

import os

import pandas as pd
import pyomo.environ as pyo
import pytest

from sdom import initialize_model, load_data
from sdom.io_manager import export_results
from sdom.optimization_main import (
    get_default_solver_config_dict,
    run_solver,
)
from sdom.results import OptimizationResults


REL_LEGACY_FIXTURE = "Data/no_exchange_run_of_river"
REL_ZONAL_FIXTURE = "Data/zonal_test"

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

MARGINAL_PRICE_COLUMNS = [
    "hour",
    "area_id",
    "marginal_price_USD_per_MWh",
    "generation_component_USD_per_MWh",
    "congestion_component_USD_per_MWh",
    "supply_balance_dual",
    "line_congestion_dual_sum",
    "pricing_method",
    "pricing_status",
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


def _highs_config():
    config = get_default_solver_config_dict(solver_name="highs")
    config["solve_keywords"]["tee"] = False
    config["solve_keywords"]["report_timing"] = False
    config["solve_keywords"]["keepfiles"] = False
    return config


# ---------------------------------------------------------------------------
# Module-scoped solve fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def zonal_model_and_results():
    if not _highs_available():
        pytest.skip("HiGHS solver not available")
    data = load_data(_abs_data_path(REL_ZONAL_FIXTURE))
    model = initialize_model(data, n_hours=24)
    results = run_solver(model, _highs_config(), case_name="zonal_export_test")
    return model, results


@pytest.fixture(scope="module")
def legacy_results():
    if not _highs_available():
        pytest.skip("HiGHS solver not available")
    data = load_data(_abs_data_path(REL_LEGACY_FIXTURE))
    model = initialize_model(data, n_hours=24)
    return run_solver(model, _highs_config(), case_name="legacy_export_test")


# ---------------------------------------------------------------------------
# Zonal export emits OutputInterregionalExchanges_{case}.csv
# ---------------------------------------------------------------------------
def test_export_emits_interregional_exchanges_csv(tmp_path, zonal_model_and_results):
    """A zonal solve writes the per-line CSV with the PRD §2.4 schema."""
    model, results = zonal_model_and_results
    case = "zonal_export_test"

    export_results(results, case, output_dir=str(tmp_path))

    csv_path = tmp_path / f"OutputInterregionalExchanges_{case}.csv"
    assert csv_path.exists(), f"Expected {csv_path.name} to be emitted under zonal solve"

    df = pd.read_csv(csv_path)

    # PRD §2.4 schema: exact column set.
    assert list(df.columns) == PRD_2_4_COLUMNS

    # Row count: |L| * n_hours.
    n_lines = len(model.L)
    n_hours = len(model.h)
    assert len(df) == n_lines * n_hours

    # Round-trip preserves the in-memory DataFrame's row count.
    assert len(df) == len(results.interregional_exchanges_df)


# ---------------------------------------------------------------------------
# Legacy export does NOT emit OutputInterregionalExchanges_{case}.csv
# ---------------------------------------------------------------------------
def test_export_skips_interregional_exchanges_for_legacy(tmp_path, legacy_results):
    """Legacy single-area solves leave the interregional CSV unwritten."""
    case = "legacy_export_test"

    export_results(legacy_results, case, output_dir=str(tmp_path))

    csv_path = tmp_path / f"OutputInterregionalExchanges_{case}.csv"
    assert not csv_path.exists()

    # Generation CSV is still emitted as usual (sanity check on legacy path).
    assert (tmp_path / f"OutputGeneration_{case}.csv").exists()


# ---------------------------------------------------------------------------
# Empty interregional_exchanges_df does NOT trigger emission
# ---------------------------------------------------------------------------
def test_export_skips_when_interregional_dataframe_is_empty(tmp_path):
    """An ``OptimizationResults`` with the default empty DataFrame writes no CSV."""
    results = OptimizationResults()
    assert results.interregional_exchanges_df.empty

    export_results(results, "empty_case", output_dir=str(tmp_path))

    assert not (tmp_path / "OutputInterregionalExchanges_empty_case.csv").exists()


def test_zonal_marginal_prices_have_area_hour_rows_and_auditable_duals(
    zonal_model_and_results,
):
    """Zonal pricing exposes one available LMP per area-hour and line duals."""
    model, results = zonal_model_and_results
    prices = results.get_marginal_prices_dataframe()
    audit = results.get_line_congestion_duals_dataframe()

    assert list(prices.columns) == MARGINAL_PRICE_COLUMNS
    assert len(prices) == len(model.A) * len(model.h)
    assert set(prices["area_id"]) == set(model.A)
    assert set(prices["pricing_status"]) == {"available"}
    assert prices["marginal_price_USD_per_MWh"].notna().all()
    assert len(audit) == len(model.L) * len(model.h)

    for hour in model.h:
        hourly = prices.loc[prices["hour"] == hour].set_index("area_id")
        reference = sorted(model.A)[0]
        assert hourly.loc[reference, "congestion_component_USD_per_MWh"] == pytest.approx(0.0)
        assert (
            hourly["marginal_price_USD_per_MWh"]
            == hourly["generation_component_USD_per_MWh"]
            + hourly["congestion_component_USD_per_MWh"]
        ).all()

    for _, row in audit.iterrows():
        prices_at_hour = prices.loc[prices["hour"] == row["hour"]].set_index("area_id")
        price_delta = (
            prices_at_hour.loc[row["to_area"], "marginal_price_USD_per_MWh"]
            - prices_at_hour.loc[row["from_area"], "marginal_price_USD_per_MWh"]
        )
        assert price_delta == pytest.approx(-row["line_congestion_dual_sum"])
