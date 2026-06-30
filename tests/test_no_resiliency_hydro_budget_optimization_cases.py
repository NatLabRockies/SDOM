import os
import pytest

from sdom import load_data
from sdom import run_solver, initialize_model, get_default_solver_config_dict

from utils_tests import get_n_eq_ineq_constraints, get_optimization_problem_info, get_optimization_problem_solution_info, check_supply_balance_constraint, check_budget_constraint
from utils_tests import CBC_EXECUTABLE, CBC_NOT_AVAILABLE_REASON
from constants_test import REL_PATH_DATA_HYDRO_BUDGET_TEST, REL_PATH_DATA_DAILY_HYDRO_BUDGET_TEST

def test_optimization_model_ini_case_no_resiliency_730h_monthly_budget():

    test_data_path = os.path.join(os.path.dirname(__file__), '..', REL_PATH_DATA_HYDRO_BUDGET_TEST)
    test_data_path = os.path.abspath(test_data_path)
    
    data = load_data( test_data_path )

    model = initialize_model(data, n_hours = 730, with_resilience_constraints=False)

    constraint_counts = get_n_eq_ineq_constraints( model )

    assert constraint_counts["equality"] == 5113
    assert constraint_counts["inequality"] == 25571


def test_optimization_model_res_case_no_resiliency_730h_monthly_budget_highs():

    test_data_path = os.path.join(os.path.dirname(__file__), '..', REL_PATH_DATA_HYDRO_BUDGET_TEST)
    test_data_path = os.path.abspath(test_data_path)
    
    data = load_data( test_data_path )

    model = initialize_model( data, n_hours = 730, with_resilience_constraints = False )

    solver_dict = get_default_solver_config_dict(solver_name="highs", executable_path="")
    try:
        results = run_solver( model, solver_dict )
        assert results is not None
    except Exception as e:
        pytest.fail(f"{run_solver.__name__} failed with error: {e}")
    
    problem_info_dict = get_optimization_problem_info( results )

    problem_sol_dict = get_optimization_problem_solution_info( results )
    assert problem_sol_dict["Termination condition"] == "optimal"

    assert abs( problem_sol_dict["Total_Cost"] - 441627.4738187364 ) <= 10 
    assert abs( problem_sol_dict["Total_CapWind"] - 0.0 ) <= 1
    assert abs( problem_sol_dict["Total_CapPV"] - 0.0 ) <= 0.001
    assert abs( problem_sol_dict["Total_CapScha_Li-Ion"] - 0.0 ) <= 1
    assert abs( problem_sol_dict["Total_CapScha_CAES"] - 0.0 ) <= 1
    assert abs( problem_sol_dict["Total_CapScha_PHS"] - 0.0 ) <= 1
    assert abs( problem_sol_dict["Total_CapScha_H2"] - 0.0 ) <= 1

    # Check supply balance constraint
    supply_balance_check = check_supply_balance_constraint(results)
    assert supply_balance_check["is_satisfied"], f"Supply balance violated at hours: {supply_balance_check['violations']}"
    assert supply_balance_check["has_imports"] == False, "Imports should not be present in this test case"
    assert supply_balance_check["has_exports"] == False, "Exports should not be present in this test case"

    # Check hydro budget constraint (monthly budget = 730 hours)
    budget_check = check_budget_constraint(model, block_name="hydro")
    assert budget_check["is_satisfied"], f"Hydro budget violated at periods: {budget_check['violations']}"
    assert budget_check["n_budget_periods"] == 1, f"Expected 1 monthly budget period, got {budget_check['n_budget_periods']}"


@pytest.mark.skipif(CBC_EXECUTABLE is None, reason=CBC_NOT_AVAILABLE_REASON)
def test_optimization_model_res_case_no_resiliency_730h_monthly_budget_cbc():

    test_data_path = os.path.join(os.path.dirname(__file__), '..', REL_PATH_DATA_HYDRO_BUDGET_TEST)
    test_data_path = os.path.abspath(test_data_path)
    
    data = load_data( test_data_path )

    model = initialize_model( data, n_hours = 730, with_resilience_constraints = False )

    solver_dict = get_default_solver_config_dict(solver_name="cbc", executable_path=CBC_EXECUTABLE)
    try:
        results = run_solver( model, solver_dict )
        assert results is not None
    except Exception as e:
        pytest.fail(f"{run_solver.__name__} failed with error: {e}")

    problem_info_dict = get_optimization_problem_info( results )
    assert problem_info_dict["Number of constraints"] == 19388
    assert problem_info_dict["Number of variables"] == 22306
    assert problem_info_dict["Number of binary variables"] == 2920
    assert problem_info_dict["Number of objectives"] == 1
    assert problem_info_dict["Number of nonzeros"] == 8768

    problem_sol_dict = get_optimization_problem_solution_info( results )
    assert problem_sol_dict["Termination condition"] == "optimal"

    assert abs( problem_sol_dict["Total_Cost"] - 441627.4738187364 ) <= 10 
    assert abs( problem_sol_dict["Total_CapWind"] - 0.0 ) <= 1
    assert abs( problem_sol_dict["Total_CapPV"] - 0.0 ) <= 0.001
    assert abs( problem_sol_dict["Total_CapScha_Li-Ion"] - 0.0 ) <= 1
    assert abs( problem_sol_dict["Total_CapScha_CAES"] - 0.0 ) <= 1
    assert abs( problem_sol_dict["Total_CapScha_PHS"] - 0.0 ) <= 1
    assert abs( problem_sol_dict["Total_CapScha_H2"] - 0.0 ) <= 1




def test_optimization_model_ini_case_no_resiliency_168h_daily_budget():

    test_data_path = os.path.join(os.path.dirname(__file__), '..', REL_PATH_DATA_DAILY_HYDRO_BUDGET_TEST)
    test_data_path = os.path.abspath(test_data_path)
    
    data = load_data( test_data_path )

    model = initialize_model(data, n_hours = 168, with_resilience_constraints=False)

    constraint_counts = get_n_eq_ineq_constraints( model )

    assert constraint_counts["equality"] == 1185
    assert constraint_counts["inequality"] == 5901


def test_optimization_model_res_case_no_resiliency_168h_daily_budget_highs():

    test_data_path = os.path.join(os.path.dirname(__file__), '..', REL_PATH_DATA_DAILY_HYDRO_BUDGET_TEST)
    test_data_path = os.path.abspath(test_data_path)
    
    data = load_data( test_data_path )

    model = initialize_model( data, n_hours = 168, with_resilience_constraints = False )

    solver_dict = get_default_solver_config_dict(solver_name="highs", executable_path="")
    try:
        results = run_solver( model, solver_dict )
        assert results is not None
    except Exception as e:
        pytest.fail(f"{run_solver.__name__} failed with error: {e}")
    
    problem_info_dict = get_optimization_problem_info( results )

    problem_sol_dict = get_optimization_problem_solution_info( results )
    assert problem_sol_dict["Termination condition"] == "optimal"
    print(problem_sol_dict["Total_Cost"])
    assert abs( problem_sol_dict["Total_Cost"] - 578101.3 ) <= 10 
    assert abs( problem_sol_dict["Total_CapWind"] - 0.0 ) <= 1
    assert abs( problem_sol_dict["Total_CapPV"] - 0.0 ) <= 0.001
    assert abs( problem_sol_dict["Total_CapScha_Li-Ion"] - 0.0 ) <= 1
    assert abs( problem_sol_dict["Total_CapScha_CAES"] - 0.0 ) <= 1
    assert abs( problem_sol_dict["Total_CapScha_PHS"] - 0.0 ) <= 1
    assert abs( problem_sol_dict["Total_CapScha_H2"] - 0.0 ) <= 1

    # Check supply balance constraint
    supply_balance_check = check_supply_balance_constraint(results)
    assert supply_balance_check["is_satisfied"], f"Supply balance violated at hours: {supply_balance_check['violations']}"
    assert supply_balance_check["has_imports"] == False, "Imports should not be present in this test case"
    assert supply_balance_check["has_exports"] == False, "Exports should not be present in this test case"

    # Check hydro budget constraint (daily budget = 24 hours, 168/24 = 7 periods)
    budget_check = check_budget_constraint(model, block_name="hydro")
    assert budget_check["is_satisfied"], f"Hydro budget violated at periods: {budget_check['violations']}"
    assert budget_check["n_budget_periods"] == 7, f"Expected 7 daily budget periods, got {budget_check['n_budget_periods']}"
    assert budget_check["budget_scalar"] == 24, f"Expected daily budget scalar of 24 hours, got {budget_check['budget_scalar']}"