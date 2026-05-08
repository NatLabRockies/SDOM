import logging
import math
#from pympler import muppy, summary
#from pympler import muppy, summary
from pyomo.opt import SolverFactory, SolverStatus, TerminationCondition, check_available_solvers
from pyomo.util.infeasible import log_infeasible_constraints
from pyomo.environ import ConcreteModel, Objective, Block, minimize

from .initializations import initialize_sets, initialize_params
from .common.utilities import safe_pyomo_value
from .models.formulations_vre import add_vre_variables, add_vre_expressions, add_vre_balance_constraints
from .models.formulations_thermal import add_thermal_variables, add_thermal_expressions, add_thermal_constraints
from .models.formulations_resiliency import add_resiliency_variables, add_resiliency_constraints
from .models.formulations_storage import add_storage_variables, add_storage_expressions, add_storage_constraints
from .models.formulations_system import objective_rule, add_system_expressions, add_system_constraints
from .models.formulations_imports_exports import add_imports_variables, add_exports_variables, add_imports_exports_cost_expressions, add_imports_constraints, add_exports_constraints
from .models.formulations_hydro import add_hydro_variables, add_hydro_run_of_river_constraints, add_hydro_budget_constraints

from .constants import (
    MW_TO_KW,
    RUN_OF_RIVER_FORMULATION,
    IMPORTS_EXPORTS_NOT_MODEL,
    COPPER_PLATE_NETWORK,
    AREA_TRANSPORTATION_MODEL_NETWORK,
    DEFAULT_AREA_ID,
)

from .io_manager import get_formulation, get_network_formulation
from .utils_performance_meassure import ModelInitProfiler
from .results import OptimizationResults, collect_results_from_model

# ---------------------------------------------------------------------------------
# Model initialization
# Safe value function for uninitialized variables/parameters

def initialize_model(data, n_hours=8760, with_resilience_constraints=False, model_name="SDOM_Model"):
    """Initialize a Pyomo SDOM optimization model (dispatcher).

    Selects the model-construction path based on the ``Network`` formulation
    declared in ``data["formulations"]`` and the number of areas in
    ``data["areas"]``:

    - **Legacy fast path** (``Network = CopperPlateNetwork`` and
      ``len(data["areas"]) == 1``): delegates to
      :func:`_initialize_model_legacy`, which is the historical model body
      preserved verbatim. This guarantees bit-identical objective values
      for every legacy data folder (locked by
      ``tests/test_zonal_legacy_regression.py``).
    - **Per-area Block path** (``Network = AreaTransportationModelNetwork``
      or ``len(data["areas"]) > 1``): not yet implemented in this commit;
      will be wired in commit #9b together with the builder refactor that
      lets each ``add_*`` consume a per-area data slice.

    Parameters
    ----------
    data : dict
        Data dictionary as returned by :func:`sdom.io_manager.load_data`.
        Must contain ``"formulations"`` and ``"areas"`` keys.
    n_hours : int, optional
        Number of hours to simulate (default 8760).
    with_resilience_constraints : bool, optional
        If True, adds resilience-related constraints. Combined with
        ``Network = AreaTransportationModelNetwork`` raises
        :class:`NotImplementedError` (deferred per PRD).
    model_name : str, optional
        Name to assign to the Pyomo model instance (default ``"SDOM_Model"``).

    Returns
    -------
    pyomo.environ.ConcreteModel
        A fully initialized Pyomo model ready for optimization, with a
        ``profiler`` attribute attached.

    Raises
    ------
    NotImplementedError
        When the per-area Block path is required (zonal data or
        ``Network = AreaTransportationModelNetwork``). This branch lands
        in commit #9b.
    """
    network = get_network_formulation(data)
    areas = data.get("areas", [{"area_id": DEFAULT_AREA_ID}])
    n_areas = len(areas)

    is_legacy_fast_path = (
        network == COPPER_PLATE_NETWORK and n_areas == 1
    )

    if is_legacy_fast_path:
        return _initialize_model_legacy(
            data,
            n_hours=n_hours,
            with_resilience_constraints=with_resilience_constraints,
            model_name=model_name,
        )

    raise NotImplementedError(
        "Per-area Block construction (Network='%s', |areas|=%d) is not yet "
        "wired into initialize_model. The zonal Block path lands in commit "
        "#9b of PR #53; see dev_guidelines/zonal_model/PRD.md \u00a75 and "
        "\u00a710. Use a legacy single-area folder (CopperPlateNetwork + 1 "
        "area) until then." % (network, n_areas)
    )


def _initialize_model_legacy(data, *, n_hours=8760, with_resilience_constraints=False, model_name="SDOM_Model"):
    """Build the legacy single-area copper-plate SDOM model (verbatim body).

    This is the historical body of :func:`initialize_model` extracted into a
    private helper so the public dispatcher can route here unchanged for
    the ``CopperPlateNetwork`` + single-area case. **Do not modify the body
    without updating the golden-file regression test
    ``tests/test_zonal_legacy_regression.py``** — it locks the objective
    values produced by this function.

    Parameters mirror :func:`initialize_model`.

    Returns
    -------
    pyomo.environ.ConcreteModel
        The fully-built Pyomo model (with ``model.profiler`` attached).
    """

    # Initialize profiler (always enabled for time and memory measurement)
    profiler = ModelInitProfiler(track_memory=True, enabled=True)
    profiler.start()

    logging.info("Instantiating SDOM Pyomo optimization model...")
    
    def create_model_and_blocks():
        """Helper to create model and blocks as a single profiled step."""
        m = ConcreteModel(name=model_name)
        m.hydro = Block()
        m.imports = Block()
        m.exports = Block()
        m.demand = Block()
        m.nuclear = Block()
        m.other_renewables = Block()
        if with_resilience_constraints:
            m.resiliency = Block()
        m.storage = Block()
        m.thermal = Block()
        m.pv = Block()
        m.wind = Block()
        return m

    model = profiler.measure_step("Create model & blocks", create_model_and_blocks)

    # Initialize sets
    logging.info("Initializing model sets...")
    profiler.measure_step("Initialize sets", initialize_sets, model, data, n_hours=n_hours)
    
    # Initialize parameters
    logging.info("Initializing model parameters...")
    profiler.measure_step("Initialize parameters", initialize_params, model, data)

    # ----------------------------------- Variables -----------------------------------
    logging.info("Adding variables to the model...")
    
    # VRE variables
    logging.debug("-- Adding VRE variables...")
    profiler.measure_step("Add VRE variables", add_vre_variables, model)

    # VRE expressions
    logging.debug("-- Adding VRE expressions...")
    profiler.measure_step("Add VRE expressions", add_vre_expressions, model)

    # Thermal variables
    logging.debug("-- Adding thermal generation variables...")
    profiler.measure_step("Add thermal variables", add_thermal_variables, model)

    # Thermal expressions
    logging.debug("-- Adding thermal generation expressions...")
    profiler.measure_step("Add thermal expressions", add_thermal_expressions, model)

    # Resilience variables
    if with_resilience_constraints:
        logging.debug("-- Adding resiliency variables...")
        profiler.measure_step("Add resiliency variables", add_resiliency_variables, model)

    # Storage variables
    logging.debug("--Adding storage variables...")
    profiler.measure_step("Add storage variables", add_storage_variables, model)

    # Storage expressions
    logging.debug("--Adding storage expressions...")
    profiler.measure_step("Add storage expressions", add_storage_expressions, model)

    # Hydro variables
    logging.debug("-- Adding hydropower generation variables...")
    profiler.measure_step("Add hydro variables", add_hydro_variables, model)

    # Imports variables
    if get_formulation(data, component="Imports") != IMPORTS_EXPORTS_NOT_MODEL:
        logging.debug("-- Adding Imports variables...")
        profiler.measure_step("Add imports variables", add_imports_variables, model)
    
    # Exports variables
    if get_formulation(data, component="Exports") != IMPORTS_EXPORTS_NOT_MODEL:
        logging.debug("-- Adding Exports variables...")
        profiler.measure_step("Add exports variables", add_exports_variables, model)

    # Imports/Exports cost expressions
    profiler.measure_step("Add imports/exports cost expressions", 
                         add_imports_exports_cost_expressions, model, data)

    # System expressions
    profiler.measure_step("Add system expressions", add_system_expressions, model)

    # -------------------------------- Objective function -------------------------------
    logging.info("Adding objective function to the model...")
    
    def add_objective():
        model.Obj = Objective(rule=objective_rule, sense=minimize)
    
    profiler.measure_step("Add objective function", add_objective)

    # ----------------------------------- Constraints -----------------------------------
    logging.info("Adding constraints to the model...")
    
    # System constraints
    logging.debug("-- Adding system constraints...")
    profiler.measure_step("Add system constraints", add_system_constraints, model, data)

    # Resiliency constraints
    if with_resilience_constraints:
        logging.debug("-- Adding resiliency constraints...")
        profiler.measure_step("Add resiliency constraints", add_resiliency_constraints, model)
  
    # VRE balance constraints
    logging.debug("-- Adding VRE balance constraints...")
    profiler.measure_step("Add VRE balance constraints", add_vre_balance_constraints, model)

    # Storage constraints
    logging.debug("-- Adding storage constraints...")
    profiler.measure_step("Add storage constraints", add_storage_constraints, model)

    # Thermal constraints
    logging.debug("-- Adding thermal generation constraints...")
    profiler.measure_step("Add thermal constraints", add_thermal_constraints, model)

    # Hydro constraints
    logging.debug("-- Adding hydropower generation constraints...")
    if get_formulation(data, component="hydro") == RUN_OF_RIVER_FORMULATION:
        profiler.measure_step("Add hydro run-of-river constraints", 
                             add_hydro_run_of_river_constraints, model, data)
    else:
        profiler.measure_step("Add hydro budget constraints", 
                             add_hydro_budget_constraints, model, data)

    # Imports constraints
    if get_formulation(data, component="Imports") != IMPORTS_EXPORTS_NOT_MODEL:
        logging.debug("-- Adding Imports constraints...")
        profiler.measure_step("Add imports constraints", add_imports_constraints, model, data)
    
    # Exports constraints
    if get_formulation(data, component="Exports") != IMPORTS_EXPORTS_NOT_MODEL:
        logging.debug("-- Adding Exports constraints...")
        profiler.measure_step("Add exports constraints", add_exports_constraints, model, data)

    # Finalize profiling
    profiler.stop()
    profiler.print_summary_table(logging.getLogger())
    # Attach profiler to model for programmatic access
    model.profiler = profiler

    return model

# ---------------------------------------------------------------------------------
# Results collection function - DEPRECATED, use collect_results_from_model from results.py
# Kept for backward compatibility
def collect_results(model):
    """Collect results from a solved model (DEPRECATED).

    This function is deprecated. Use `collect_results_from_model` from the results
    module instead, which returns an OptimizationResults dataclass.

    Parameters
    ----------
    model : pyomo.core.base.PyomoModel.ConcreteModel
        The Pyomo model instance containing the optimization results.

    Returns
    -------
    dict
        A dictionary containing collected results for backward compatibility.

    .. deprecated::
        Use :func:`sdom.results.collect_results_from_model` instead.
    """
    import warnings
    warnings.warn(
        "collect_results is deprecated. Use collect_results_from_model from results.py instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    logging.info("Collecting SDOM results...")
    results = {}
    results["Total_Cost"] = safe_pyomo_value(model.Obj.expr)

    # Capacity and generation results
    logging.debug("Collecting capacity results...")
    results["Total_CapCC"] = safe_pyomo_value(model.thermal.total_installed_capacity)
    results["Total_CapPV"] = safe_pyomo_value(model.pv.total_installed_capacity)
    results["Total_CapWind"] = safe_pyomo_value(model.wind.total_installed_capacity)
    results["Total_CapScha"] = {j: safe_pyomo_value(model.storage.Pcha[j]) for j in model.storage.j}
    results["Total_CapSdis"] = {j: safe_pyomo_value(model.storage.Pdis[j]) for j in model.storage.j}
    results["Total_EcapS"] = {j: safe_pyomo_value(model.storage.Ecap[j]) for j in model.storage.j}

    # Generation and dispatch results
    logging.debug("Collecting generation dispatch results...")
    results["Total_GenPV"] = safe_pyomo_value(model.pv.total_generation)
    results["Total_GenWind"] = safe_pyomo_value(model.wind.total_generation)
    results["Total_GenS"] = {j: sum(safe_pyomo_value(model.storage.PD[h, j]) for h in model.h) for j in model.storage.j}

    results["SolarPVGen"] = {h: safe_pyomo_value(model.pv.generation[h]) for h in model.h}
    results["WindGen"] = {h: safe_pyomo_value(model.wind.generation[h]) for h in model.h}
    results["AggThermalGen"] = {h: sum(safe_pyomo_value(model.thermal.generation[h, bu]) for bu in model.thermal.plants_set) for h in model.h}

    results["SolarCapex"] = safe_pyomo_value(model.pv.capex_cost_expr)
    results["WindCapex"] = safe_pyomo_value(model.wind.capex_cost_expr)
    results["SolarFOM"] = safe_pyomo_value(model.pv.fixed_om_cost_expr)
    results["WindFOM"] = safe_pyomo_value(model.wind.fixed_om_cost_expr)

    logging.debug("Collecting storage results...")
    storage_tech_list = list(model.storage.j)

    for tech in storage_tech_list:
        results[f"{tech}PowerCapex"] = model.storage.CRF[tech] * (
            MW_TO_KW * model.storage.data["CostRatio", tech] * model.storage.data["P_Capex", tech] * model.storage.Pcha[tech]
            + MW_TO_KW * (1 - model.storage.data["CostRatio", tech]) * model.storage.data["P_Capex", tech] * model.storage.Pdis[tech]
        )
        results[f"{tech}EnergyCapex"] = model.storage.CRF[tech] * MW_TO_KW * model.storage.data["E_Capex", tech] * model.storage.Ecap[tech]
        results[f"{tech}FOM"] = (
            MW_TO_KW * model.storage.data["CostRatio", tech] * model.storage.data["FOM", tech] * model.storage.Pcha[tech]
            + MW_TO_KW * (1 - model.storage.data["CostRatio", tech]) * model.storage.data["FOM", tech] * model.storage.Pdis[tech]
        )
        results[f"{tech}VOM"] = model.storage.data["VOM", tech] * sum(model.storage.PD[h, tech] for h in model.h)

    results["TotalThermalCapex"] = sum(
        model.thermal.FCR[bu] * MW_TO_KW * model.thermal.CAPEX_M[bu] * model.thermal.plant_installed_capacity[bu]
        for bu in model.thermal.plants_set
    )
    results["ThermalFuel"] = sum(
        (model.thermal.fuel_price[bu] * model.thermal.heat_rate[bu]) * sum(model.thermal.generation[h, bu] for h in model.h)
        for bu in model.thermal.plants_set
    )
    results["ThermalFOM"] = safe_pyomo_value(model.thermal.fixed_om_cost_expr)
    results["ThermalVOM"] = sum(
        model.thermal.VOM_M[bu] * sum(model.thermal.generation[h, bu] for h in model.h) for bu in model.thermal.plants_set
    )

    return results





def configure_solver(solver_config_dict: dict):
    """Configure and instantiate a Pyomo solver based on configuration dictionary.

    Creates a SolverFactory instance with the specified solver and applies any
    provided options. Handles solver-specific initialization (e.g., executable
    paths for CBC, license initialization for Xpress).

    Parameters
    ----------
    solver_config_dict : dict
        Configuration dictionary containing:

        - 'solver_name' (str): Solver identifier (e.g., 'cbc', 'appsi_highs',
          'xpress_direct', 'gurobi')
        - 'executable_path' (str): Path to solver executable (required for CBC,
          optional for others)
        - 'options' (dict): Solver-specific options to apply (e.g., miprelstop,
          outputlog)

    Returns
    -------
    solver
        Configured Pyomo solver instance ready to solve optimization models.

    Raises
    ------
    RuntimeError
        If the specified solver is not available on the system.

    Notes
    -----
    - CBC solver requires explicit executable_path.
    - Xpress uses xpress_direct interface and requires a valid license.
    - HiGHS and other solvers use system PATH or Python package installation.

    Examples
    --------
    >>> config = get_default_solver_config_dict(solver_name="xpress")
    >>> solver = configure_solver(config)
    """
    solver_name = solver_config_dict["solver_name"]

    if solver_name == "cbc":
        executable_path = solver_config_dict.get("executable_path")
        if executable_path:
            solver = SolverFactory(solver_name, executable=executable_path)
        else:
            solver = SolverFactory(solver_name)
    else:
        solver = SolverFactory(solver_name)

    if not solver.available():
        raise RuntimeError(f"Solver '{solver_name}' is not available on this system.")

    # Apply solver-specific options
    options = solver_config_dict.get("options", {})
    if options:
        for key, value in options.items():
            solver.options[key] = value

    return solver

def get_default_solver_config_dict(
    solver_name="cbc",
    executable_path=".\\Solver\\bin\\cbc.exe",
    *,
    mip_gap=0.002,
    time_limit=None,
):
    """Generate a default solver configuration dictionary with standard SDOM settings.

    Creates a pre-configured dictionary for solver initialization with recommended
    settings for SDOM optimization problems. Includes solver options and solve
    keywords for controlling optimization behavior.

    Parameters
    ----------
    solver_name : str, optional
        Solver to use. Supported values:

        - 'cbc': COIN-OR CBC open-source MILP solver (requires executable_path)
        - 'highs': HiGHS open-source MILP solver (uses appsi interface)
        - 'xpress': FICO Xpress commercial solver (requires license)

        Default is 'cbc'.
    executable_path : str, optional
        Path to solver executable file. Required for CBC solver.
        Default is '.\\Solver\\bin\\cbc.exe'.
    mip_gap : float, optional
        MIP relative optimality gap tolerance. Default is 0.002 (0.2%).
    time_limit : float, optional
        Maximum solve time in seconds. Default is None (no limit).

    Returns
    -------
    dict
        Configuration dictionary with keys:

        - 'solver_name' (str): Solver identifier for SolverFactory
        - 'executable_path' (str): Path to executable (CBC only)
        - 'options' (dict): Solver-specific options
        - 'solve_keywords' (dict): Arguments for solver.solve() call

    Notes
    -----
    Solver-specific option mappings:

    - **HiGHS**: Uses 'mip_rel_gap' for MIP gap
    - **Xpress**: Uses 'miprelstop' for MIP gap, 'maxtime' for time limit
    - **CBC**: Uses 'ratioGap' for MIP gap

    Examples
    --------
    >>> # Using HiGHS (open-source)
    >>> config = get_default_solver_config_dict(solver_name="highs")
    >>> solver = configure_solver(config)

    >>> # Using Xpress (commercial, requires license)
    >>> config = get_default_solver_config_dict(
    ...     solver_name="xpress",
    ...     mip_gap=0.001,
    ...     time_limit=3600,
    ... )
    >>> solver = configure_solver(config)
    """
    # Base configuration for solve() call
    solve_keywords = {
        "tee": True,
        "load_solutions": True,
        "report_timing": True,
        "timelimit": time_limit,
        "keepfiles": False,
    }

    # Solver-specific configurations
    if solver_name == "cbc":
        solver_dict = {
            "solver_name": "cbc",
            "executable_path": executable_path,
            "options": {
                "ratioGap": mip_gap,
            },
            "solve_keywords": solve_keywords,
        }

    elif solver_name == "highs":
        solver_dict = {
            "solver_name": "appsi_highs",
            "executable_path": None,
            "options": {
                "mip_rel_gap": mip_gap,
            },
            "solve_keywords": solve_keywords,
        }

    elif solver_name == "xpress":
        # Xpress uses different control names
        # See: https://www.fico.com/fico-xpress-optimization/docs/latest/solver/optimizer/python/HTML/
        xpress_options = {
            "miprelstop": mip_gap,  # MIP relative gap tolerance
            "outputlog": 1,         # Enable solver output (0=off, 1=on)
        }
        if time_limit is not None:
            if time_limit < 0:
                raise ValueError(f"time_limit must be non-negative, got {time_limit}")
            xpress_options["maxtime"] = math.ceil(time_limit)  # Xpress expects integer seconds

        solver_dict = {
            "solver_name": "xpress_direct",
            "executable_path": None,
            "options": xpress_options,
            "solve_keywords": solve_keywords,
        }

    else:
        # Generic fallback for other solvers
        solver_dict = {
            "solver_name": solver_name,
            "executable_path": None,
            "options": {},
            "solve_keywords": solve_keywords,
        }

    return solver_dict


# Run solver function
def run_solver(model, solver_config_dict: dict, case_name: str = "run") -> OptimizationResults:
    """Solve the optimization model and return structured results.

    Solves the given optimization model using the configured solver and collects
    all results into an OptimizationResults dataclass.

    Parameters
    ----------
    model : pyomo.core.base.PyomoModel.ConcreteModel
        The Pyomo optimization model to be solved. The model must have an
        attribute 'GenMix_Target' that can be set.
    solver_config_dict : dict
        Solver configuration dictionary from get_default_solver_config_dict().
    case_name : str, optional
        Case identifier for labeling results. Defaults to "run".

    Returns
    -------
    OptimizationResults
        A dataclass containing all optimization results including:
        - termination_condition: Solver termination status
        - total_cost: Objective value
        - generation_df: Hourly generation dispatch DataFrame
        - storage_df: Hourly storage operation DataFrame
        - summary_df: Summary metrics DataFrame
        - capacity: Installed capacities by technology
        - storage_capacity: Storage capacities (charge, discharge, energy)
        - cost_breakdown: Detailed cost breakdown
        - problem_info: Solver problem information

    Raises
    ------
    RuntimeError
        If the solver is not available on the system.

    Notes
    -----
    If the solver does not find an optimal solution, the returned
    OptimizationResults will have is_optimal=False and minimal data populated.
    """
    logging.info("Starting to solve SDOM model...")
    solver = configure_solver(solver_config_dict)

    target_value = float(model.GenMix_Target.value)

    logging.info(f"Running optimization for GenMix_Target = {target_value:.2f}")
    solver_result = solver.solve(
        model,
        tee=solver_config_dict["solve_keywords"].get("tee", True),
        load_solutions=solver_config_dict["solve_keywords"].get("load_solutions", True),
        timelimit=solver_config_dict["solve_keywords"].get("timelimit", None),
        report_timing=solver_config_dict["solve_keywords"].get("report_timing", True),
        keepfiles=solver_config_dict["solve_keywords"].get("keepfiles", True),
    )

    if (solver_result.solver.status == SolverStatus.ok) and (
        solver_result.solver.termination_condition == TerminationCondition.optimal
    ):
        # Collect results using the new structured approach
        results = collect_results_from_model(model, solver_result, case_name)
    else:
        logging.warning(f"Solver did not find an optimal solution for GenMix_Target = {target_value:.2f}.")
        logging.warning("Logging infeasible constraints...")
        log_infeasible_constraints(model)

        # Return minimal results with solver info
        results = OptimizationResults(
            termination_condition=str(solver_result.solver.termination_condition),
            solver_status=str(solver_result.solver.status),
            gen_mix_target=target_value,
        )
        # Still extract problem info if available
        if solver_result.problem:
            problem = solver_result.problem[0]
            # Helper to extract value from Pyomo ScalarData objects
            def get_value(val):
                if hasattr(val, 'value'):
                    return val.value
                return val
            
            results.problem_info = {
                "Number of constraints": get_value(problem.get("Number of constraints", 0)),
                "Number of variables": get_value(problem.get("Number of variables", 0)),
                "Number of binary variables": get_value(problem.get("Number of binary variables", 0)),
                "Number of objectives": get_value(problem.get("Number of objectives", 0)),
                "Number of nonzeros": get_value(problem.get("Number of nonzeros", 0)),
            }

    return results
