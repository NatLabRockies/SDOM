import os
import pytest

from sdom import load_data
from sdom import run_solver, initialize_model, get_default_solver_config_dict

from utils_tests import check_supply_balance_constraint, get_n_eq_ineq_constraints, get_optimization_problem_info, get_optimization_problem_solution_info
from utils_tests import CBC_EXECUTABLE, CBC_NOT_AVAILABLE_REASON
from constants_test import REL_PATH_DATA_RUN_OF_RIVER_TEST

def test_optimization_model_ini_case_no_resiliency_24h():

    test_data_path = os.path.join(os.path.dirname(__file__), '..', REL_PATH_DATA_RUN_OF_RIVER_TEST)
    test_data_path = os.path.abspath(test_data_path)
    
    data = load_data( test_data_path )

    model = initialize_model(data, n_hours = 24, with_resilience_constraints=False)

    constraint_counts = get_n_eq_ineq_constraints( model )

    assert constraint_counts["equality"] == 194
    assert constraint_counts["inequality"] == 549


def test_optimization_model_res_case_no_resiliency_highs():

    test_data_path = os.path.join(os.path.dirname(__file__), '..', REL_PATH_DATA_RUN_OF_RIVER_TEST)
    test_data_path = os.path.abspath(test_data_path)
    
    data = load_data( test_data_path )

    model = initialize_model( data, n_hours = 24, with_resilience_constraints = False )

    #solver_dict = get_default_solver_config_dict(solver_name="cbc", executable_path=".\\Solver\\bin\\cbc.exe")
    solver_dict = get_default_solver_config_dict(solver_name="highs", executable_path="")
    try:
        results = run_solver( model, solver_dict )
        assert results is not None
    except Exception as e:
        pytest.fail(f"{run_solver.__name__} failed with error: {e}")
    
    problem_info_dict = get_optimization_problem_info( results )

    problem_sol_dict = get_optimization_problem_solution_info( results )
    assert problem_sol_dict["Termination condition"] == "optimal"
    assert abs( problem_sol_dict["Total_Cost"] - 3285154847.471892 ) <= 10 
    assert abs( problem_sol_dict["Total_CapWind"] - 26681.257521521577 ) <= 1
    assert abs( problem_sol_dict["Total_CapPV"] - 0.0 ) <= 0.001
    assert abs( problem_sol_dict["Total_CapScha_Li-Ion"] - 1254.8104 ) <= 1
    assert abs( problem_sol_dict["Total_CapScha_CAES"] -1340.7415 ) <= 1
    assert abs( problem_sol_dict["Total_CapScha_PHS"] - 0.0 ) <= 1
    assert abs( problem_sol_dict["Total_CapScha_H2"] - 0.0 ) <= 1

    # Check supply balance constraint
    supply_balance_check = check_supply_balance_constraint(results)
    assert supply_balance_check["is_satisfied"], f"Supply balance violated at hours: {supply_balance_check['violations']}"
    assert supply_balance_check["has_imports"] == False, "Imports should not be present in this test case"
    assert supply_balance_check["has_exports"] == False, "Exports should not be present in this test case"



@pytest.mark.skipif(CBC_EXECUTABLE is None, reason=CBC_NOT_AVAILABLE_REASON)
def test_optimization_model_res_case_no_resiliency_cbc():

    test_data_path = os.path.join(os.path.dirname(__file__), '..', REL_PATH_DATA_RUN_OF_RIVER_TEST)
    test_data_path = os.path.abspath(test_data_path)
    
    data = load_data( test_data_path )

    model = initialize_model( data, n_hours = 24, with_resilience_constraints = False )

    solver_dict = get_default_solver_config_dict(solver_name="cbc", executable_path=CBC_EXECUTABLE)
    try:
        results = run_solver( model, solver_dict )
        assert results is not None
    except Exception as e:
        pytest.fail(f"{run_solver.__name__} failed with error: {e}")

    problem_info_dict = get_optimization_problem_info( results )
    assert problem_info_dict["Number of constraints"] == 646
    assert problem_info_dict["Number of variables"] == 628
    assert problem_info_dict["Number of binary variables"] == 96
    assert problem_info_dict["Number of objectives"] == 1
    assert problem_info_dict["Number of nonzeros"] == 282

    problem_sol_dict = get_optimization_problem_solution_info( results )
    assert problem_sol_dict["Termination condition"] == "optimal"
    assert abs( problem_sol_dict["Total_Cost"] - 3285154847.471892 ) <= 10
    assert abs( problem_sol_dict["Total_CapWind"] - 26681.257521521577 ) <= 1
    assert abs( problem_sol_dict["Total_CapPV"] - 0.0 ) <= 0.001
    assert abs( problem_sol_dict["Total_CapScha_Li-Ion"] - 1254.8104 ) <= 1
    assert abs( problem_sol_dict["Total_CapScha_CAES"] -1340.7415 ) <= 1
    assert abs( problem_sol_dict["Total_CapScha_PHS"] - 0.0 ) <= 1
    assert abs( problem_sol_dict["Total_CapScha_H2"] - 0.0 ) <= 1

    # Check supply balance constraint
    supply_balance_check = check_supply_balance_constraint(results)
    assert supply_balance_check["is_satisfied"], f"Supply balance violated at hours: {supply_balance_check['violations']}"
    assert supply_balance_check["has_imports"] == False, "Imports should not be present in this test case"
    assert supply_balance_check["has_exports"] == False, "Exports should not be present in this test case"

