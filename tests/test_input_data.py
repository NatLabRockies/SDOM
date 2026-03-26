import os

import pandas as pd
import pytest

from constants_test import (
    REL_PATH_DATA_RUN_OF_RIVER_TEST,
    REL_PATH_DATA_HYDRO_BUDGET_TEST,
    REL_PATH_DATA_DAILY_HYDRO_BUDGET_IMP_EXP_TEST,
    DICT_EXPECTED_DATA_KEYS_TO_TYPE,
)

from sdom import load_data, initialize_model
from sdom.io_manager import check_formulation, get_formulation

def test_load_data_folder_exist():
    test_data_path = os.path.join(os.path.dirname(__file__), '..', REL_PATH_DATA_RUN_OF_RIVER_TEST)
    test_data_path = os.path.abspath(test_data_path)

    assert os.path.exists(test_data_path)
    


def test_load_data_keys_and_types():
    test_data_path = os.path.join(os.path.dirname(__file__), '..', REL_PATH_DATA_RUN_OF_RIVER_TEST)
    test_data_path = os.path.abspath(test_data_path)
    
    data = load_data( test_data_path )
    data_keys = data.keys()
    not_expected_keys_in_this_test = ["large_hydro_max", "large_hydro_min", "cap_imports", "cap_exports", "price_imports", "price_exports"]
    for key, expected_type in DICT_EXPECTED_DATA_KEYS_TO_TYPE.items():
        if key in not_expected_keys_in_this_test:
                assert key not in data_keys, f"Key '{key}' should not be present in run of River test data"
                continue  # Skip these keys as they are not for run of River
        assert key in data_keys, f"Missing expected key: {key}"
        assert isinstance(data[key], expected_type), f"Key '{key}' has incorrect type. Expected {expected_type}, got {type(data[key])}"

    

def test_load_data_param_values():
    test_data_path = os.path.join(os.path.dirname(__file__), '..', REL_PATH_DATA_RUN_OF_RIVER_TEST)
    test_data_path = os.path.abspath(test_data_path)
    
    data = load_data( test_data_path )
    
    df = data["scalars"]
    # Check some specific values in the scalars DataFrame
    assert abs( df.loc["LifeTimeVRE"].Value - 30 ) <= 0.05
    assert abs( df.loc["GenMix_Target"].Value - 1 ) <= 0.05
    assert abs( df.loc["r"].Value - 0.06 ) <= 0.0005

def test_load_data_thermal_values():
    test_data_path = os.path.join(os.path.dirname(__file__), '..', REL_PATH_DATA_RUN_OF_RIVER_TEST)
    test_data_path = os.path.abspath(test_data_path)

    data = load_data( test_data_path )

    df = data["thermal_data"]
    min_capacity_v = [0.0 , 0.0]
    max_capacity_v = [4897.0, 0.0]
    lifetime_v = [30.0, 30.0]
    Capex_v = [0, 0]
    heat_rate_v = [1, 1]
    fuel_cost_v = [129.2517007, 129.2517007]
    vom_v = [7.5, 7.5]
    for idx, row in df.iterrows():
        assert abs( row["MinCapacity"] - min_capacity_v[idx] ) <= 0.05
        assert abs( row["MaxCapacity"] - max_capacity_v[idx] ) <= 0.05
        assert abs( row["Lifetime"] - lifetime_v[idx] ) <= 0.05
        assert abs( row["Capex"] - Capex_v[idx] ) <= 0.05
        assert abs( row["HeatRate"] - heat_rate_v[idx] ) <= 0.05
        assert abs( row["FuelCost"] - fuel_cost_v[idx] ) <= 0.05
        assert abs( row["VOM"] - vom_v[idx] ) <= 0.05

    model = initialize_model(data, n_hours = 24, with_resilience_constraints=False)
    assert list(model.thermal.plants_set) == ['83_GAS', '83_Coal']
    

def test_load_data_storage_values():
    test_data_path = os.path.join(os.path.dirname(__file__), '..', REL_PATH_DATA_RUN_OF_RIVER_TEST)
    test_data_path = os.path.abspath(test_data_path)

    data = load_data( test_data_path )

    assert data["STORAGE_SET_J_TECHS"] == ["Li-Ion", "CAES", "PHS", "H2"]
    assert data["STORAGE_SET_B_TECHS"] == ["Li-Ion", "PHS",]

    df = data["storage_data"]
    P_capex_v = [97.78, 842.63, 1063.32, 1414.84]
    E_capex_v = [115.67, 34.66, 53.12, 1.09]
    Eff_v = [0.86,0.632133333,0.782,0.44]
    Min_Duration_v = [1, 1, 1, 1]
    Max_Duration_v = [12, 24, 24, 6480]
    Max_P_v = [100000, 100000, 100000, 100000]
    MaxCycles_v = [3250, 100000, 100000, 100000]
    FOM_v = [10.3, 4.120718067, 8.241436134, 47.38825777]
    VOM_v = [3.09, 4.120718067, 1.030179517, 0]
    Lifetime_v = [13, 30, 55, 18]
    CostRatio_v = [0.5, 0.325, 0.5, 0.49]
    

    # Check some specific values in the storage_data DataFrame
    for i, tech in enumerate( data["STORAGE_SET_J_TECHS"] ):
        assert abs( df.loc["P_Capex", tech] - P_capex_v[i] ) <= 0.05
        assert abs( df.loc["E_Capex", tech] - E_capex_v[i] ) <= 0.05
        assert abs( df.loc["Eff", tech] - Eff_v[i] ) <= 0.05
        assert abs( df.loc["Min_Duration", tech] - Min_Duration_v[i] ) <= 0.05
        assert abs( df.loc["Max_Duration", tech] - Max_Duration_v[i] ) <= 0.05
        assert abs( df.loc["Max_P", tech] - Max_P_v[i] ) <= 0.05
        assert abs( df.loc["MaxCycles", tech] - MaxCycles_v[i] ) <= 0.05
        assert abs( df.loc["FOM", tech] - FOM_v[i] ) <= 0.05
        assert abs( df.loc["VOM", tech] - VOM_v[i] ) <= 0.05
        assert abs( df.loc["Lifetime", tech] - Lifetime_v[i] ) <= 0.05
        assert abs( df.loc["CostRatio", tech] - CostRatio_v[i] ) <= 0.05


# =============================================================================
# check_formulation
# =============================================================================

def test_check_formulation_raises_on_invalid():
    """check_formulation must raise ValueError for an unrecognised formulation."""
    with pytest.raises(ValueError, match="BadFormulation"):
        check_formulation("BadFormulation", ["ValidA", "ValidB"])


def test_check_formulation_passes_on_valid():
    """check_formulation must not raise when the formulation is in the valid list."""
    check_formulation("ValidA", ["ValidA", "ValidB"])  # no exception expected


# =============================================================================
# get_formulation
# =============================================================================

def test_get_formulation_case_insensitive():
    """get_formulation must match component names regardless of case."""
    formulations_df = pd.DataFrame({
        "Component": ["Hydro", "Imports", "Exports"],
        "Formulation": ["RunOfRiverFormulation", "NotModel", "NotModel"],
    })
    data = {"formulations": formulations_df}
    assert get_formulation(data, "hydro") == "RunOfRiverFormulation"
    assert get_formulation(data, "HYDRO") == "RunOfRiverFormulation"


# =============================================================================
# load_data – hydro-budget branch (large_hydro_max / large_hydro_min)
# =============================================================================

def test_load_data_hydro_budget_has_large_hydro_bounds():
    """Non-RunOfRiver formulation must load large_hydro_max and large_hydro_min."""
    test_data_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '..', REL_PATH_DATA_HYDRO_BUDGET_TEST)
    )

    data = load_data(test_data_path)

    assert "large_hydro_max" in data, "large_hydro_max should be present for budget formulation"
    assert "large_hydro_min" in data, "large_hydro_min should be present for budget formulation"
    assert isinstance(data["large_hydro_max"], pd.DataFrame)
    assert isinstance(data["large_hydro_min"], pd.DataFrame)
    assert not data["large_hydro_max"].empty
    assert not data["large_hydro_min"].empty


# =============================================================================
# load_data – imports/exports branch (CapacityPriceNetLoadFormulation)
# =============================================================================

def test_load_data_imports_exports_keys_present():
    """CapacityPriceNetLoadFormulation must load cap/price import and export tables."""
    test_data_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '..', REL_PATH_DATA_DAILY_HYDRO_BUDGET_IMP_EXP_TEST)
    )

    data = load_data(test_data_path)

    for key in ("cap_imports", "price_imports", "cap_exports", "price_exports"):
        assert key in data, f"Key '{key}' should be present for CapacityPriceNetLoadFormulation"
        assert isinstance(data[key], pd.DataFrame), f"Key '{key}' should be a DataFrame"
        assert not data[key].empty, f"DataFrame for '{key}' should not be empty"