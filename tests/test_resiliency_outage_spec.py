"""Phase 4 / Deliverable A: tests for the ``OutageSpec`` dataclass."""

from __future__ import annotations

import pandas as pd
import pytest

from sdom.resiliency import (
    BaselineDispatchResults,
    DesignedSystem,
    MUST_RUN_COMPONENTS,
    OutageSpec,
    VALID_COMPONENTS,
)


# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def synthetic_designed_system() -> DesignedSystem:
    n = 24
    idx = pd.RangeIndex(start=1, stop=n + 1, name="Hour")
    storage_caps = {
        "Li-Ion": {
            "Cap_Pch": 10.0,
            "Cap_Pdis": 10.0,
            "Cap_E": 40.0,
            "eta_ch": 0.9,
            "eta_dis": 0.9,
            "soc_min_frac": 0.0,
            "vom": 0.0,
        },
        "H2": {
            "Cap_Pch": 5.0,
            "Cap_Pdis": 5.0,
            "Cap_E": 100.0,
            "eta_ch": 0.7,
            "eta_dis": 0.7,
            "soc_min_frac": 0.0,
            "vom": 0.0,
        },
    }
    return DesignedSystem(
        storage_caps=storage_caps,
        thermal_caps={"83": {"capacity_MW": 100.0, "var_cost": 30.0}},
        solar_caps={"S1": 50.0},
        wind_caps={"994997": 30.0},
        load=pd.Series([50.0] * n, index=idx),
        cf_solar=pd.DataFrame({"S1": [0.3] * n}, index=idx),
        cf_wind=pd.DataFrame({"994997": [0.4] * n}, index=idx),
        nuclear=pd.Series([0.0] * n, index=idx),
        hydro=pd.Series([0.0] * n, index=idx),
        other_renewables=pd.Series([0.0] * n, index=idx),
        import_cap=pd.Series([100.0] * n, index=idx),
        import_price=pd.Series([50.0] * n, index=idx),
        export_cap=pd.Series([0.0] * n, index=idx),
        export_price=pd.Series([0.0] * n, index=idx),
        phi_fix_t=pd.Series([10.0] * n, index=idx),
        phi_var_t=pd.Series([2.0] * n, index=idx),
        month_of_hour=pd.Series([1] * n, index=idx),
    )


@pytest.fixture
def synthetic_baseline_results(synthetic_designed_system) -> BaselineDispatchResults:
    n = 24
    idx = pd.RangeIndex(start=1, stop=n + 1, name="Hour")
    soc = pd.DataFrame(
        {"Li-Ion": [20.0] * n, "H2": [50.0] * n},
        index=idx,
    )
    return BaselineDispatchResults(
        soc_trajectory=soc,
        objective_value=0.0,
        solver_status="optimal",
        metadata={"designed_system": synthetic_designed_system},
    )


# ---------------------------------------------------------------------------
# Construction & basic resolution
# ---------------------------------------------------------------------------
def test_minimal_construction(synthetic_designed_system):
    spec = OutageSpec(
        duration_hours=24,
        recovery_hours=24,
        outaged_assets={"balancing_units": "all"},
    )
    spec.validate(synthetic_designed_system)


def test_recovery_hours_int_broadcast(synthetic_designed_system):
    spec = OutageSpec(
        duration_hours=4,
        recovery_hours=24,
        outaged_assets={"balancing_units": "all"},
    )
    rec = spec.resolve_recovery_hours(synthetic_designed_system)
    assert rec == {"Li-Ion": 24, "H2": 24}


def test_recovery_hours_dict(synthetic_designed_system):
    spec = OutageSpec(
        duration_hours=4,
        recovery_hours={"Li-Ion": 12, "H2": 48},
        outaged_assets={"balancing_units": "all"},
    )
    assert spec.recovery_hours == {"Li-Ion": 12, "H2": 48}
    assert spec.resolve_recovery_hours(synthetic_designed_system) == {"Li-Ion": 12, "H2": 48}

    spec_missing = OutageSpec(
        duration_hours=4,
        recovery_hours={"Li-Ion": 12},
        outaged_assets={"balancing_units": "all"},
    )
    with pytest.raises(ValueError, match="recovery_hours"):
        spec_missing.resolve_recovery_hours(synthetic_designed_system)


def test_per_asset_durations_overrides(synthetic_designed_system):
    spec = OutageSpec(
        duration_hours=24,
        recovery_hours=4,
        outaged_assets={"balancing_units": "all"},
        per_asset_durations={("balancing_units", "83"): 12},
    )
    assert spec.resolve_duration("balancing_units", "83") == 12
    # No override for solar plant -> falls back to duration_hours.
    assert spec.resolve_duration("solar", "S1") == 24


def test_derating_factors_default(synthetic_designed_system):
    spec = OutageSpec(
        duration_hours=4,
        recovery_hours=4,
        outaged_assets={"wind": ["994997"]},
    )
    # Listed asset, no override -> rho = 0 (full outage).
    assert spec.resolve_derating("wind", "994997") == 0.0
    # Unlisted asset -> rho = 1 (no outage).
    assert spec.resolve_derating("solar", "S1") == 1.0
    assert spec.resolve_derating("balancing_units", "83") == 1.0


def test_derating_factor_out_of_range_raises():
    with pytest.raises(ValueError, match=r"derating"):
        OutageSpec(
            duration_hours=4,
            recovery_hours=4,
            outaged_assets={"wind": ["994997"]},
            derating_factors={("wind", "994997"): 1.5},
        )


def test_derating_factor_negative_raises():
    with pytest.raises(ValueError, match=r"derating"):
        OutageSpec(
            duration_hours=4,
            recovery_hours=4,
            outaged_assets={"wind": ["994997"]},
            derating_factors={("wind", "994997"): -0.1},
        )


def test_outaged_assets_unknown_component_raises():
    with pytest.raises(ValueError) as exc:
        OutageSpec(
            duration_hours=4,
            recovery_hours=4,
            outaged_assets={"unknownX": "all"},
        )
    msg = str(exc.value)
    for comp in VALID_COMPONENTS:
        assert comp in msg


def test_outaged_assets_string_must_be_all():
    with pytest.raises(ValueError, match=r"all"):
        OutageSpec(
            duration_hours=4,
            recovery_hours=4,
            outaged_assets={"wind": "first"},
        )


def test_outaged_assets_iterable_validates_against_designed_system(synthetic_designed_system):
    spec = OutageSpec(
        duration_hours=4,
        recovery_hours=4,
        outaged_assets={"wind": ["nonexistent_id"]},
    )
    with pytest.raises(ValueError, match=r"nonexistent_id"):
        spec.validate(synthetic_designed_system)


def test_min_soc_recovery_default_is_baseline(
    synthetic_designed_system, synthetic_baseline_results
):
    spec = OutageSpec(
        duration_hours=4,
        recovery_hours=4,
        outaged_assets={"balancing_units": "all"},
    )
    recovery_end_hour = {"Li-Ion": 8, "H2": 8}
    targets = spec.resolve_min_soc_recovery(
        synthetic_baseline_results,
        synthetic_designed_system,
        recovery_end_hour=recovery_end_hour,
    )
    # Baseline SOC at hour 8 = 20.0 (Li-Ion) / Cap_E 40 = 0.5;
    # 50.0 (H2) / Cap_E 100 = 0.5.
    assert targets["Li-Ion"] == pytest.approx(0.5)
    assert targets["H2"] == pytest.approx(0.5)


def test_min_soc_recovery_user_dict_overrides(
    synthetic_designed_system, synthetic_baseline_results
):
    spec = OutageSpec(
        duration_hours=4,
        recovery_hours=4,
        outaged_assets={"balancing_units": "all"},
        min_soc_recovery={"Li-Ion": 0.7},
    )
    recovery_end_hour = {"Li-Ion": 8, "H2": 8}
    targets = spec.resolve_min_soc_recovery(
        synthetic_baseline_results,
        synthetic_designed_system,
        recovery_end_hour=recovery_end_hour,
    )
    assert targets["Li-Ion"] == pytest.approx(0.7)
    # H2 falls back to baseline.
    assert targets["H2"] == pytest.approx(0.5)


def test_must_run_components_accepted(synthetic_designed_system):
    spec = OutageSpec(
        duration_hours=4,
        recovery_hours=4,
        outaged_assets={
            "hydro": "all",
            "nuclear": "all",
            "other_renewables": "all",
        },
    )
    spec.validate(synthetic_designed_system)
    for comp in MUST_RUN_COMPONENTS:
        assert spec.resolve_outaged_asset_ids(comp, synthetic_designed_system) == ["all"]


def test_must_run_iterable_raises_not_implemented(synthetic_designed_system):
    spec = OutageSpec(
        duration_hours=4,
        recovery_hours=4,
        outaged_assets={"hydro": ["plant_a"]},
    )
    with pytest.raises(NotImplementedError, match=r"hydro"):
        spec.validate(synthetic_designed_system)


def test_imports_component_uses_grid_id(synthetic_designed_system):
    spec = OutageSpec(
        duration_hours=4,
        recovery_hours=4,
        outaged_assets={"imports": "all"},
    )
    spec.validate(synthetic_designed_system)
    assert spec.resolve_outaged_asset_ids("imports", synthetic_designed_system) == ["grid"]
    assert spec.resolve_derating("imports", "grid") == 0.0
