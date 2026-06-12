"""Phase 1 TDD tests for the resiliency data loader (MEA case).

Migrated from the legacy 3MW PGnE fixture to the tracked MEA snapshot /
inputs under ``Data/resiliency_eval/`` (see ``tests/_resiliency_fixtures.py``)
because the post-CEM-reuse builder is infeasible on PGnE and several numeric
assertions were stale (efficiency convention changed to ``sqrt(round_trip)``
per ``formulations_storage.py``).
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

import pandas as pd
import pytest

from sdom.resiliency import (
    BaselineState,
    DesignedSystem,
    load_designed_system,
)

from _resiliency_fixtures import (
    INPUTS_DIR_MEA,
    SNAPSHOT_DIR_MEA,
    SCENARIO_ID,
    YEAR,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def designed_system_mea():
    """Load the MEA designed system once per test module."""
    return load_designed_system(
        SNAPSHOT_DIR_MEA,
        inputs_dir=INPUTS_DIR_MEA,
        year=YEAR,
        scenario_id=SCENARIO_ID,
    )


class TestLoadDesignedSystemMEA:
    """Validates loader output against the MEA snapshot."""

    def test_returns_designed_system_instance(self, designed_system_mea):
        assert isinstance(designed_system_mea, DesignedSystem)
        assert designed_system_mea.year == YEAR
        assert designed_system_mea.scenario_id == SCENARIO_ID

    def test_storage_capacities_li_ion(self, designed_system_mea):
        assert "Li-Ion" in designed_system_mea.storage_caps
        li = designed_system_mea.storage_caps["Li-Ion"]
        assert li["Cap_Pch"] == pytest.approx(74.99985, rel=1e-4)
        assert li["Cap_Pdis"] == pytest.approx(74.99985, rel=1e-4)
        assert li["Cap_E"] == pytest.approx(446.37133, rel=1e-4)
        # eta_{ch,dis} are one-way values = sqrt(round-trip Eff) per the CEM
        # convention in formulations_storage.py (which squares them internally).
        assert li["eta_ch"] == pytest.approx(math.sqrt(0.85), rel=1e-4)
        assert li["eta_dis"] == pytest.approx(math.sqrt(0.85), rel=1e-4)
        assert li["vom"] == pytest.approx(0.0, abs=1e-9)

    def test_storage_capacities_h2(self, designed_system_mea):
        assert "H2" in designed_system_mea.storage_caps
        h2 = designed_system_mea.storage_caps["H2"]
        assert h2["Cap_Pch"] == pytest.approx(142.18804, rel=1e-4)
        assert h2["Cap_Pdis"] == pytest.approx(147.4, rel=1e-4)
        assert h2["Cap_E"] == pytest.approx(17898.53206, rel=1e-4)
        assert h2["eta_ch"] == pytest.approx(math.sqrt(0.4), rel=1e-4)

    def test_zero_capacity_storage_excluded(self, designed_system_mea):
        # Vanadium and PHS have zero energy capacity in the MEA snapshot too.
        assert "Vanadium" not in designed_system_mea.storage_caps
        assert "PHS" not in designed_system_mea.storage_caps

    def test_thermal_techs_filtered_out(self, designed_system_mea):
        # GasCC / Diesel are 0 MW in the MEA snapshot.
        assert "GasCC" not in designed_system_mea.thermal_caps
        assert "Diesel" not in designed_system_mea.thermal_caps

    def test_vre_per_plant_capacities(self, designed_system_mea):
        # MEA snapshot has a single solar plant and a single wind plant; their
        # effective installed MW = Capacity (MW) * Selection.
        assert designed_system_mea.solar_caps == pytest.approx(
            {"3621133": 361.0}, rel=1e-4
        )
        assert list(designed_system_mea.wind_caps) == ["994997"]
        assert designed_system_mea.wind_caps["994997"] == pytest.approx(
            307.884939, rel=1e-4
        )

    def test_vre_capacity_matches_summary_aggregate(self, designed_system_mea):
        solar_total = sum(designed_system_mea.solar_caps.values())
        wind_total = sum(designed_system_mea.wind_caps.values())
        assert solar_total == pytest.approx(361.0, abs=0.1)
        assert wind_total == pytest.approx(307.884939, abs=0.1)

    @pytest.mark.parametrize(
        "attr",
        [
            "load",
            "nuclear",
            "hydro",
            "other_renewables",
            "import_cap",
            "import_price",
            "export_cap",
            "export_price",
            "phi_fix_t",
            "phi_var_t",
            "month_of_hour",
        ],
    )
    def test_hourly_series_length(self, designed_system_mea, attr):
        series = getattr(designed_system_mea, attr)
        assert isinstance(series, pd.Series)
        assert len(series) == 8760

    @pytest.mark.parametrize("attr", ["cf_solar", "cf_wind"])
    def test_hourly_dataframe_shape(self, designed_system_mea, attr):
        df = getattr(designed_system_mea, attr)
        assert isinstance(df, pd.DataFrame)
        assert df.shape[0] == 8760
        assert df.shape[1] >= 1

    def test_demand_charges_mea_values(self, designed_system_mea):
        # MEA scalars: phi_fix uniform at 12,570 USD/kW-month, phi_var=0.
        phi_fix = designed_system_mea.phi_fix_t
        phi_var = designed_system_mea.phi_var_t
        assert (phi_fix == 12570.0).all()
        assert (phi_var == 0.0).all()

    def test_month_of_hour_is_one_through_twelve(self, designed_system_mea):
        moh = designed_system_mea.month_of_hour
        assert set(moh.unique()) == set(range(1, 13))

    def test_baseline_state_importable(self):
        # Phase-1 placeholder dataclass - just ensure it instantiates.
        bs = BaselineState()
        assert hasattr(bs, "soc_trajectory")


class TestErrorHandling:
    """Failure-mode tests for the loader."""

    def test_missing_summary_raises(self, tmp_path):
        # Empty snapshot directory -> FileNotFoundError
        empty_snapshot = tmp_path / "empty_snap"
        empty_snapshot.mkdir()
        with pytest.raises(FileNotFoundError, match="OutputSummary"):
            load_designed_system(
                empty_snapshot,
                inputs_dir=INPUTS_DIR_MEA,
                year=YEAR,
                scenario_id=SCENARIO_ID,
            )

    def test_zero_capacity_warns(self, designed_system_mea, caplog):
        # Re-load to trigger warnings in a controlled context.
        with caplog.at_level(logging.WARNING, logger="sdom.resiliency.data_loader"):
            load_designed_system(
                SNAPSHOT_DIR_MEA,
                inputs_dir=INPUTS_DIR_MEA,
                year=YEAR,
                scenario_id=SCENARIO_ID,
            )
        messages = [rec.getMessage() for rec in caplog.records]
        # Vanadium/PHS storage techs are zero in MEA too.
        assert any("Vanadium" in m for m in messages)
        assert any("PHS" in m for m in messages)


def _write_synthetic_summary(path: Path, scenarios: list[int]):
    """Write a minimal OutputSummary CSV with the given scenarios."""
    rows = []
    for sc in scenarios:
        rows += [
            ("Capacity", "GasCC", sc, 0, "MW"),
            ("Capacity", "Diesel", sc, 0, "MW"),
            ("Capacity", "Solar PV", sc, 1.0, "MW"),
            ("Capacity", "Wind", sc, 1.0, "MW"),
            ("Charge power capacity", "Li-Ion", sc, 1.0, "MW"),
            ("Discharge power capacity", "Li-Ion", sc, 1.0, "MW"),
            ("Energy capacity", "Li-Ion", sc, 4.0, "MWh"),
            ("Charge power capacity", "Vanadium", sc, 0, "MW"),
            ("Discharge power capacity", "Vanadium", sc, 0, "MW"),
            ("Energy capacity", "Vanadium", sc, 0, "MWh"),
            ("Charge power capacity", "PHS", sc, 0, "MW"),
            ("Discharge power capacity", "PHS", sc, 0, "MW"),
            ("Energy capacity", "PHS", sc, 0, "MWh"),
            ("Charge power capacity", "H2", sc, 0, "MW"),
            ("Discharge power capacity", "H2", sc, 0, "MW"),
            ("Energy capacity", "H2", sc, 0, "MWh"),
        ]
    df = pd.DataFrame(
        rows, columns=["Metric", "Technology", "Scenario", "Optimal Value", "Unit"]
    )
    df.to_csv(path, index=False)


def _write_synthetic_vre(path: Path, scenarios: list[int]):
    rows = []
    for sc in scenarios:
        rows.append(
            (sc, "3621133", "Solar PV", 1.0, 35.0, -118.0, 10000.0)
        )
        rows.append(
            (sc, "994997", "Wind", 1.0, 33.0, -116.0, 1300.0)
        )
    df = pd.DataFrame(
        rows,
        columns=[
            "Scenario",
            "VRE unit ID",
            "Technology",
            "Selection ",
            "latitude",
            "longitude",
            "Capacity (MW)",
        ],
    )
    df.to_csv(path, index=False)


class TestScenarioIdResolution:
    """Hybrid resolution rules for the scenario_id argument."""

    def test_single_scenario_used_regardless_of_user_id(self, tmp_path, caplog):
        snap = tmp_path / "snap"
        snap.mkdir()
        _write_synthetic_summary(snap / "2030_OutputSummary_synthetic.csv", [7])
        _write_synthetic_vre(snap / "2030_OutputSelectedVRE_synthetic.csv", [7])
        # User passes scenario_id=99, but only run 7 exists -> use 7 (with warning)
        with caplog.at_level(logging.WARNING, logger="sdom.resiliency.data_loader"):
            ds = load_designed_system(
                snap,
                inputs_dir=INPUTS_DIR_MEA,
                year=2030,
                scenario_id=99,
            )
        assert ds.scenario_id == 7
        messages = [rec.getMessage().lower() for rec in caplog.records]
        assert any("scenario_id" in m or "run" in m for m in messages)

    def test_multi_scenario_unknown_id_raises(self, tmp_path):
        snap = tmp_path / "snap"
        snap.mkdir()
        _write_synthetic_summary(snap / "2030_OutputSummary_multi.csv", [1, 2, 3])
        _write_synthetic_vre(snap / "2030_OutputSelectedVRE_multi.csv", [1, 2, 3])
        with pytest.raises(ValueError) as exc:
            load_designed_system(
                snap,
                inputs_dir=INPUTS_DIR_MEA,
                year=2030,
                scenario_id=42,
            )
        msg = str(exc.value)
        assert "42" in msg
        for sid in ("1", "2", "3"):
            assert sid in msg

    def test_multi_scenario_valid_id_works(self, tmp_path):
        snap = tmp_path / "snap"
        snap.mkdir()
        _write_synthetic_summary(snap / "2030_OutputSummary_multi.csv", [1, 2, 3])
        _write_synthetic_vre(snap / "2030_OutputSelectedVRE_multi.csv", [1, 2, 3])
        ds = load_designed_system(
            snap,
            inputs_dir=INPUTS_DIR_MEA,
            year=2030,
            scenario_id=2,
        )
        assert ds.scenario_id == 2
        assert "Li-Ion" in ds.storage_caps
