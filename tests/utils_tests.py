import os
import shutil
import sys
from pathlib import Path

import pandas as pd
from pyomo.environ import Constraint

from sdom import OptimizationResults
from sdom.common.utilities import get_complete_path
from sdom.constants import INPUT_CSV_NAMES


def get_cbc_executable():
    """Return a usable CBC executable path, or ``None`` if none is available.

    Resolution order:

    1. ``SDOM_CBC_PATH`` environment variable (if it points to an existing file).
    2. Vendored binary at ``<repo>/Solver/bin/cbc[.exe]`` matching the current OS.
    3. ``cbc`` discovered on ``PATH``.
    """
    env_path = os.environ.get("SDOM_CBC_PATH")
    if env_path and Path(env_path).is_file():
        return env_path

    repo_root = Path(__file__).resolve().parent.parent
    binary_name = "cbc.exe" if sys.platform == "win32" else "cbc"
    vendored = repo_root / "Solver" / "bin" / binary_name
    if vendored.is_file():
        return str(vendored)

    found = shutil.which("cbc")
    if found:
        return found
    return None


CBC_EXECUTABLE = get_cbc_executable()
CBC_NOT_AVAILABLE_REASON = (
    "CBC executable not available; set SDOM_CBC_PATH or install CBC to run this test"
)


def get_n_eq_ineq_constraints(model):
    # Count constraints by type
    constraint_counts = {"equality": 0, "inequality": 0}

    for constraint in model.component_objects(Constraint, active=True):
        for index in constraint:
            con = constraint[index]
            if con.equality:  # Check if it's an equality constraint
                constraint_counts["equality"] += 1
            else:  # Otherwise, it's an inequality constraint
                constraint_counts["inequality"] += 1

    return constraint_counts


def get_optimization_problem_info(results: OptimizationResults) -> dict:
    """Extract problem information from optimization results.

    Parameters
    ----------
    results : OptimizationResults
        The optimization results object from run_solver().

    Returns
    -------
    dict
        Dictionary with problem information (constraints, variables, etc.).
    """
    if results is not None:
        return results.get_problem_info()
    return None


def get_optimization_problem_solution_info(results: OptimizationResults) -> dict:
    """Extract solution information from optimization results.

    Parameters
    ----------
    results : OptimizationResults
        The optimization results object from run_solver().

    Returns
    -------
    dict
        Dictionary with solution information (termination condition, costs, capacities).
    """
    if results is not None:
        return {
            "Termination condition": results.termination_condition,
            "Total_Cost": results.total_cost,
            "Total_CapWind": results.total_cap_wind,
            "Total_CapPV": results.total_cap_pv,
            "Total_CapScha": results.total_cap_storage_charge,
            "Total_CapScha_Li-Ion": results.total_cap_storage_charge.get("Li-Ion", 0.0),
            "Total_CapScha_CAES": results.total_cap_storage_charge.get("CAES", 0.0),
            "Total_CapScha_PHS": results.total_cap_storage_charge.get("PHS", 0.0),
            "Total_CapScha_H2": results.total_cap_storage_charge.get("H2", 0.0),
        }
    return None


def check_supply_balance_constraint(results: OptimizationResults, tolerance: float = 1e-3) -> dict:
    """Check that the supply balance constraint is satisfied for all time steps.

    Verifies that for each hour in the solution, the supply balance equation is met:
    Load + StorageCharge - StorageDischarge - Nuclear - Hydro - OtherRenewables
    - SolarPV - Wind - Thermal - Imports + Exports + NetOutflow == 0.
    For zonal results, ``NetOutflow`` is derived from interregional flows.

    Parameters
    ----------
    results : OptimizationResults
        The optimization results object from run_solver().
    tolerance : float, optional
        Tolerance for checking balance equality. Defaults to 1e-3.

    Returns
    -------
    dict
        Dictionary with:
        - 'is_satisfied': bool indicating if all hours satisfy the balance
        - 'has_imports': bool indicating if imports are present
        - 'has_exports': bool indicating if exports are present
        - 'max_imbalance': float maximum absolute imbalance found
        - 'violations': list of (hour, imbalance) tuples for hours exceeding tolerance
    """
    if results is None:
        return {"is_satisfied": False, "error": "Results object is None"}

    gen_df = results.get_generation_dataframe()
    if gen_df.empty:
        return {"is_satisfied": False, "error": "Generation DataFrame is empty"}

    # Check if imports/exports are present (non-zero values)
    has_imports = gen_df["Imports (MW)"].abs().sum() > tolerance
    has_exports = gen_df["Exports (MW)"].abs().sum() > tolerance

    violations = []
    max_imbalance = 0.0
    exchanges = results.interregional_exchanges_df
    is_zonal = "Area" in gen_df.columns and not exchanges.empty

    for _, row in gen_df.iterrows():
        hour = row["Hour"]

        # Calculate balance: Load + StorageCharge - StorageDischarge = Generation + Imports - Exports
        # Storage Charge/Discharge is already net (Charge - Discharge), so positive means charging
        # Supply balance: Load + Charge - Discharge - all_generation - imports + exports = 0
        # Rearranged from results perspective:
        # Load + (StorageCharge - StorageDischarge) - Nuclear - Hydro - OtherRenewables - SolarPV - Wind - Thermal - Imports + Exports = 0

        balance = (
            row["Load (MW)"]
            + row["Storage Charge/Discharge (MW)"]  # Already net: PC - PD
            - row["Nuclear Generation (MW)"]
            - row["Hydro Generation (MW)"]
            - row["Other Renewables Generation (MW)"]
            - row["Solar PV Generation (MW)"]
            - row["Wind Generation (MW)"]
            - row["All Thermal Generation (MW)"]
            - row["Imports (MW)"]
            + row["Exports (MW)"]
        )
        if is_zonal:
            hour_flows = exchanges.loc[exchanges["hour"] == hour]
            net_outflow = hour_flows.loc[
                hour_flows["from_area"] == row["Area"], "flow_signed_MW"
            ].sum() - hour_flows.loc[
                hour_flows["to_area"] == row["Area"], "flow_signed_MW"
            ].sum()
            balance += net_outflow

        abs_balance = abs(balance)
        max_imbalance = max(max_imbalance, abs_balance)

        if abs_balance > tolerance:
            violations.append((hour, balance))

    return {
        "is_satisfied": len(violations) == 0,
        "has_imports": has_imports,
        "has_exports": has_exports,
        "max_imbalance": max_imbalance,
        "violations": violations,
        "n_hours_checked": len(gen_df),
    }


def check_hydro_budget_matches_csv(
    results: OptimizationResults,
    input_data_dir: str | Path,
    budget_hours: int,
    *,
    tolerance: float = 1e-3,
) -> dict:
    """Check solved hydro generation against the source CSV budget by period.

    Parameters
    ----------
    results : OptimizationResults
        Solved SDOM optimization results.
    input_data_dir : str | Path
        Directory containing the SDOM input CSV files.
    budget_hours : int
        Number of hours in each hydro budget period.
    tolerance : float, optional
        Maximum allowed absolute difference between solved hydro generation
        and the source CSV parameter within a budget period.

    Returns
    -------
    dict
        Dictionary with validation status, period details, and any violations.
    """
    if results is None:
        return {"is_satisfied": False, "error": "Results object is None"}
    if budget_hours <= 0:
        return {"is_satisfied": False, "error": f"budget_hours must be positive, got {budget_hours}"}

    generation_df = results.get_generation_dataframe()
    if generation_df.empty:
        return {"is_satisfied": False, "error": "Generation DataFrame is empty"}
    if "Hydro Generation (MW)" not in generation_df.columns:
        return {"is_satisfied": False, "error": "Generation DataFrame does not include hydro generation"}

    hydro_csv_path = get_complete_path(str(input_data_dir), INPUT_CSV_NAMES["large_hydro_data"])
    if not hydro_csv_path:
        return {"is_satisfied": False, "error": f"Large hydro CSV not found in {input_data_dir}"}

    hydro_df = pd.read_csv(hydro_csv_path)
    if "*Hour" not in hydro_df.columns:
        return {"is_satisfied": False, "error": "Large hydro CSV missing columns ['*Hour']"}
    if "LargeHydro" in hydro_df.columns:
        csv_by_hour = hydro_df.set_index("*Hour")["LargeHydro"]
    else:
        tagged_columns = [
            column
            for column in hydro_df.columns
            if column.startswith("LargeHydro@") and column.endswith("@")
        ]
        if not tagged_columns:
            return {
                "is_satisfied": False,
                "error": "Large hydro CSV missing literal 'LargeHydro' or tagged 'LargeHydro@<area>@' columns",
            }
        csv_by_hour = hydro_df.set_index("*Hour")[tagged_columns].sum(axis=1)

    generation_by_hour = generation_df.set_index("Hour")["Hydro Generation (MW)"]
    max_hour = int(generation_by_hour.index.max())
    n_budget_periods = max_hour // budget_hours
    if max_hour % budget_hours != 0:
        return {
            "is_satisfied": False,
            "error": f"Result horizon {max_hour} is not a multiple of budget_hours={budget_hours}",
        }

    violations = []
    budget_details = []
    max_difference = 0.0

    for period in range(1, n_budget_periods + 1):
        start_hour = ((period - 1) * budget_hours) + 1
        end_hour = period * budget_hours
        hours = list(range(start_hour, end_hour + 1))
        missing_result_hours = [hour for hour in hours if hour not in generation_by_hour.index]
        missing_csv_hours = [hour for hour in hours if hour not in csv_by_hour.index]
        if missing_result_hours or missing_csv_hours:
            return {
                "is_satisfied": False,
                "error": "Missing hydro budget hours",
                "period": period,
                "missing_result_hours": missing_result_hours,
                "missing_csv_hours": missing_csv_hours,
            }

        generation_sum = float(generation_by_hour.loc[hours].sum())
        csv_parameter_sum = float(csv_by_hour.loc[hours].sum())
        difference = generation_sum - csv_parameter_sum
        abs_difference = abs(difference)
        max_difference = max(max_difference, abs_difference)
        detail = {
            "period": period,
            "start_hour": start_hour,
            "end_hour": end_hour,
            "generation_sum": generation_sum,
            "csv_parameter_sum": csv_parameter_sum,
            "difference": difference,
        }
        budget_details.append(detail)
        if abs_difference > tolerance:
            violations.append(detail)

    return {
        "is_satisfied": len(violations) == 0,
        "budget_scalar": budget_hours,
        "n_budget_periods": n_budget_periods,
        "max_difference": max_difference,
        "violations": violations,
        "budget_details": budget_details,
        "hydro_csv_path": hydro_csv_path,
    }



def check_budget_constraint(model, block_name: str = "hydro", tolerance: float = 1e-3) -> dict:
    """Check that the budget constraint is satisfied for all budget periods.

    Verifies that for each budget period, the sum of generation equals the sum of
    the time-series parameter over that period.

    Parameters
    ----------
    model : pyomo.core.base.PyomoModel.ConcreteModel
        The solved Pyomo model instance.
    block_name : str, optional
        Name of the block to check (e.g., 'hydro'). Defaults to 'hydro'.
    tolerance : float, optional
        Tolerance for checking budget equality. Defaults to 1e-3.

    Returns
    -------
    dict
        Dictionary with:
        - 'is_satisfied': bool indicating if all budget periods satisfy the constraint
        - 'budget_scalar': int number of hours per budget period
        - 'n_budget_periods': int number of budget periods checked
        - 'max_imbalance': float maximum absolute imbalance found
        - 'violations': list of (period, generation_sum, ts_sum, diff) tuples
        - 'budget_details': list of dicts with period details
    """
    from sdom.common.utilities import safe_pyomo_value

    # Get the block
    block = getattr(model, block_name, None)
    if block is None:
        return {"is_satisfied": False, "error": f"Block '{block_name}' not found in model"}

    # Check if budget constraint exists
    if not hasattr(block, "budget_set") or not hasattr(block, "budget_scalar"):
        return {"is_satisfied": False, "error": f"Block '{block_name}' does not have budget constraints"}

    budget_scalar = int(safe_pyomo_value(block.budget_scalar))
    budget_set = list(block.budget_set)

    if not budget_set:
        return {"is_satisfied": False, "error": "Budget set is empty"}

    violations = []
    max_imbalance = 0.0
    budget_details = []

    for hhh in budget_set:
        # Calculate start and end hours for this budget period
        start = ((hhh - 1) * budget_scalar) + 1
        end = hhh * budget_scalar + 1
        hours_in_period = list(range(start, end))

        # Sum generation over the budget period
        generation_sum = sum(safe_pyomo_value(block.generation[h]) for h in hours_in_period)

        # Sum time-series parameter over the budget period
        ts_sum = sum(safe_pyomo_value(block.ts_parameter[h]) for h in hours_in_period)

        diff = generation_sum - ts_sum
        abs_diff = abs(diff)
        max_imbalance = max(max_imbalance, abs_diff)

        budget_details.append({
            "period": hhh,
            "start_hour": start,
            "end_hour": end - 1,
            "generation_sum": generation_sum,
            "ts_sum": ts_sum,
            "difference": diff,
        })

        if abs_diff > tolerance:
            violations.append((hhh, generation_sum, ts_sum, diff))

    return {
        "is_satisfied": len(violations) == 0,
        "budget_scalar": budget_scalar,
        "n_budget_periods": len(budget_set),
        "max_imbalance": max_imbalance,
        "violations": violations,
        "budget_details": budget_details,
    }
