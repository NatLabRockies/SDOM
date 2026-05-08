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
      :func:`_initialize_model_copperplate`, which is the historical model
      body preserved verbatim. This guarantees bit-identical objective
      values for every legacy data folder (locked by
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
        return _initialize_model_copperplate(
            data,
            n_hours=n_hours,
            with_resilience_constraints=with_resilience_constraints,
            model_name=model_name,
        )

    if network == AREA_TRANSPORTATION_MODEL_NETWORK:
        return _initialize_model_zonal(
            data,
            n_hours=n_hours,
            with_resilience_constraints=with_resilience_constraints,
            model_name=model_name,
        )

    raise ValueError(
        f"Unsupported Network formulation '{network}' with |areas|={n_areas}. "
        f"Expected '{COPPER_PLATE_NETWORK}' (single area) or "
        f"'{AREA_TRANSPORTATION_MODEL_NETWORK}'."
    )


def _initialize_model_copperplate(data, *, n_hours=8760, with_resilience_constraints=False, model_name="SDOM_Model"):
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
# Zonal (AreaTransportationModelNetwork) model initialization
# ---------------------------------------------------------------------------------
def _build_per_area_data_slice(data, area_id):
    """Build a legacy-shaped ``data`` dict scoped to a single area.

    The existing ``add_*`` builders read from a fixed set of global keys
    (``cap_solar``, ``storage_data``, ``thermal_data``, ``load_data``, …).
    For the zonal path we feed each builder a per-area ``data_slice`` with
    the same schema, populated from ``data["per_area_*"][area_id]`` views
    produced by :func:`sdom.io_manager._augment_with_per_area_views`.

    The slice intentionally **omits import / export keys** because zonal
    imports / exports are deferred to a follow-up commit; the caller must
    guard against ``Network=AreaTransportationModelNetwork`` combined with
    a non-``NotModel`` Imports / Exports formulation.

    Parameters
    ----------
    data : dict
        Loaded data dict (must contain the ``per_area_*`` views).
    area_id : str
        Area identifier (must be a key of every ``per_area_*`` dict).

    Returns
    -------
    dict
        A dict shaped like the legacy ``data`` dict, with global keys
        populated from the per-area views.
    """
    import pandas as pd

    pv = data["per_area_pv_plants"].get(area_id)
    wind = data["per_area_wind_plants"].get(area_id)
    cf_pv = data["per_area_capacity_factors_pv"].get(area_id)
    cf_wind = data["per_area_capacity_factors_wind"].get(area_id)
    storage = data["per_area_storage"].get(area_id)
    bal = data["per_area_balancing_units"].get(area_id)
    demand = data["per_area_demand"].get(area_id)
    nuclear = data["per_area_nuclear"].get(area_id)
    other = data["per_area_other_renewables"].get(area_id)
    hydro = data["per_area_hydro"].get(area_id)

    # Per-area storage tech sets (columns are stripped of the @area_id@ tag).
    if storage is not None and not storage.empty:
        j_techs = storage.columns.astype(str).tolist()
        if "Coupled" in storage.index:
            b_techs = (
                storage.columns[storage.loc["Coupled"] == 1].astype(str).tolist()
            )
        else:
            b_techs = []
    else:
        j_techs, b_techs = [], []

    slice_dict = {
        # Global / shared
        "formulations": data["formulations"],
        "scalars": data["scalars"],
        # Per-area device data, exposed under the legacy global keys
        "load_data": demand,
        "nuclear_data": nuclear,
        "other_renewables_data": other,
        "large_hydro_data": hydro,
        "cf_solar": cf_pv if cf_pv is not None else pd.DataFrame(),
        "cf_wind": cf_wind if cf_wind is not None else pd.DataFrame(),
        "cap_solar": pv if pv is not None else pd.DataFrame(),
        "cap_wind": wind if wind is not None else pd.DataFrame(),
        "thermal_data": bal,
        "storage_data": storage,
        "STORAGE_SET_J_TECHS": j_techs,
        "STORAGE_SET_B_TECHS": b_techs,
        # Plant lists (used only by ``compare_lists`` in load_data; keep empty)
        "solar_plants": [],
        "wind_plants": [],
    }
    return slice_dict


def _add_area_subblocks(area_block, *, with_resilience_constraints):
    """Attach the per-technology sub-blocks expected by the legacy builders."""
    area_block.hydro = Block()
    area_block.imports = Block()
    area_block.exports = Block()
    area_block.demand = Block()
    area_block.nuclear = Block()
    area_block.other_renewables = Block()
    if with_resilience_constraints:
        area_block.resiliency = Block()
    area_block.storage = Block()
    area_block.thermal = Block()
    area_block.pv = Block()
    area_block.wind = Block()


def _build_one_area(area_block, data_slice, *, n_hours, with_resilience_constraints):
    """Run the legacy build sequence on a single area block.

    Mirrors the order in :func:`_initialize_model_copperplate` but operates
    on ``area_block`` (a child of ``model.area``) using a per-area
    ``data_slice``. Imports / exports are intentionally skipped (caller
    guards against non-``NotModel`` formulations).
    """
    a = area_block.index()

    logging.info(f"[area={a}] Initializing model sets...")
    initialize_sets(area_block, data_slice, n_hours=n_hours)

    logging.info(f"[area={a}] Initializing model parameters...")
    initialize_params(area_block, data_slice)

    logging.info(f"[area={a}] Adding variables to the area block...")

    logging.debug(f"[area={a}] -- Adding VRE variables...")
    add_vre_variables(area_block)

    logging.debug(f"[area={a}] -- Adding VRE expressions...")
    add_vre_expressions(area_block)

    logging.debug(f"[area={a}] -- Adding thermal generation variables...")
    add_thermal_variables(area_block)

    logging.debug(f"[area={a}] -- Adding thermal generation expressions...")
    add_thermal_expressions(area_block)

    if with_resilience_constraints:
        # Defensive: caller already raises NotImplementedError for AT+resiliency.
        logging.debug(f"[area={a}] -- Adding resiliency variables...")
        add_resiliency_variables(area_block)

    logging.debug(f"[area={a}] -- Adding storage variables...")
    add_storage_variables(area_block)

    logging.debug(f"[area={a}] -- Adding storage expressions...")
    add_storage_expressions(area_block)

    logging.debug(f"[area={a}] -- Adding hydropower generation variables...")
    add_hydro_variables(area_block)

    # Skip imports/exports variables/expressions — guarded above.
    if get_formulation(data_slice, component="Imports") != IMPORTS_EXPORTS_NOT_MODEL:
        logging.warning(
            f"[area={a}] Imports formulation is not '{IMPORTS_EXPORTS_NOT_MODEL}' "
            f"under '{AREA_TRANSPORTATION_MODEL_NETWORK}' — variables skipped "
            "(deferred to a follow-up commit)."
        )
    if get_formulation(data_slice, component="Exports") != IMPORTS_EXPORTS_NOT_MODEL:
        logging.warning(
            f"[area={a}] Exports formulation is not '{IMPORTS_EXPORTS_NOT_MODEL}' "
            f"under '{AREA_TRANSPORTATION_MODEL_NETWORK}' — variables skipped "
            "(deferred to a follow-up commit)."
        )

    logging.debug(f"[area={a}] -- Adding system expressions...")
    add_system_expressions(area_block)

    logging.info(f"[area={a}] Adding constraints to the area block...")

    logging.debug(f"[area={a}] -- Adding VRE balance constraints...")
    add_vre_balance_constraints(area_block)

    logging.debug(f"[area={a}] -- Adding storage constraints...")
    add_storage_constraints(area_block)

    logging.debug(f"[area={a}] -- Adding thermal generation constraints...")
    add_thermal_constraints(area_block)

    logging.debug(f"[area={a}] -- Adding hydropower generation constraints...")
    if get_formulation(data_slice, component="hydro") == RUN_OF_RIVER_FORMULATION:
        add_hydro_run_of_river_constraints(area_block, data_slice)
    else:
        add_hydro_budget_constraints(area_block, data_slice)

    if with_resilience_constraints:
        logging.debug(f"[area={a}] -- Adding resiliency constraints...")
        add_resiliency_constraints(area_block)


def _add_zonal_supply_balance(model):
    """Add the per-area lossless transportation supply balance.

    Implements PRD §5.5 / math_model.md "Per-area energy supply balance":

    .. math::

       \\text{Supply}_{a,h} + \\text{NetFlow}_{a,h} = \\text{Demand}_{a,h}

    where ``NetFlow_{a,h} = sum_{l in L_in(a)} f[l,h] - sum_{l in L_out(a)} f[l,h]``.

    The per-area constraint is attached to ``model.area[a]`` so the legacy
    reporting tooling that introspects ``area_block.SupplyBalance`` keeps
    working unchanged.
    """
    from pyomo.environ import Constraint

    has_lines = hasattr(model, "L") and len(model.L) > 0

    def _supply_balance_rule(area_block, h):
        a = area_block.index()
        balance = (
            area_block.demand.ts_parameter[h]
            + sum(area_block.storage.PC[h, j] for j in area_block.storage.j)
            - sum(area_block.storage.PD[h, j] for j in area_block.storage.j)
            - area_block.nuclear.alpha * area_block.nuclear.ts_parameter[h]
            - area_block.hydro.generation[h]
            - area_block.other_renewables.alpha * area_block.other_renewables.ts_parameter[h]
            - area_block.pv.generation[h]
            - area_block.wind.generation[h]
            - sum(area_block.thermal.generation[h, bu] for bu in area_block.thermal.plants_set)
        )
        if has_lines:
            # Net inflow into a: + sum(f over L_in) - sum(f over L_out)
            balance = balance - sum(model.f[l, h] for l in model.L_in[a])
            balance = balance + sum(model.f[l, h] for l in model.L_out[a])
        return balance == 0

    for a in model.A:
        model.area[a].SupplyBalance = Constraint(model.h, rule=_supply_balance_rule)


def _add_zonal_genmix_constraint(model):
    """Add a single system-wide carbon-free generation share constraint.

    Aggregates clean-vs-non-clean generation and adjusted demand across all
    areas (PRD §5.5 / math_model.md). With imports / exports deferred under
    the AT path, only thermal generation appears on the LHS.
    """
    from pyomo.environ import Constraint

    def _rule(m):
        total_thermal = sum(m.area[a].thermal.total_generation for a in m.A)
        adjusted_demand = sum(
            m.area[a].demand.ts_parameter[h]
            + sum(m.area[a].storage.PC[h, j] for j in m.area[a].storage.j)
            - sum(m.area[a].storage.PD[h, j] for j in m.area[a].storage.j)
            for a in m.A
            for h in m.h
        )
        return total_thermal <= (1 - m.GenMix_Target) * adjusted_demand

    model.GenMix_Share = Constraint(rule=_rule)


def _zonal_objective_rule(model):
    """Aggregate cost objective across areas plus ``Z^trans = 0``."""
    from .models.formulations_vre import add_vre_fixed_costs
    from .models.formulations_storage import (
        add_storage_fixed_costs,
        add_storage_variable_costs,
    )
    from .models.formulations_thermal import (
        add_thermal_fixed_costs,
        add_thermal_variable_costs,
    )
    from .models.formulations_network import network_transmission_cost_rule

    fixed = sum(
        add_vre_fixed_costs(model.area[a])
        + add_storage_fixed_costs(model.area[a])
        + add_thermal_fixed_costs(model.area[a])
        for a in model.A
    )
    variable = sum(
        add_thermal_variable_costs(model.area[a])
        + add_storage_variable_costs(model.area[a])
        for a in model.A
    )
    transmission = network_transmission_cost_rule(model)
    return fixed + variable + transmission


def _initialize_model_zonal(
    data,
    *,
    n_hours=8760,
    with_resilience_constraints=False,
    model_name="SDOM_Model",
):
    """Build the per-area Block SDOM model for ``AreaTransportationModelNetwork``.

    Implements the zonal path of the dispatcher (PRD §5.1–5.7). Each area
    declared in ``data["areas"]`` becomes a child of ``model.area``
    (a ``Block(model.A)``) populated by reusing the existing
    ``add_*`` builders with a per-area ``data_slice`` (built by
    :func:`_build_per_area_data_slice`). The transportation network
    topology, signed flow variable, and capacity constraints live on the
    top-level model via :mod:`sdom.models.formulations_network`.

    Parameters
    ----------
    data : dict
        Data dictionary as returned by :func:`sdom.io_manager.load_data`.
        Must contain ``"areas"``, ``"lines"``, ``"line_cap_ft"``,
        ``"line_cap_tf"`` and the ``"per_area_*"`` views.
    n_hours : int, optional
        Number of hours to simulate (default 8760).
    with_resilience_constraints : bool, optional
        Always raises ``NotImplementedError`` under the AT path (PRD §5.8).
    model_name : str, optional
        Pyomo model name.

    Returns
    -------
    pyomo.environ.ConcreteModel
        A fully built zonal model ready for ``run_solver``.

    Raises
    ------
    NotImplementedError
        When ``with_resilience_constraints=True`` (PRD §5.8) or when
        Imports / Exports formulations are not ``NotModel`` (deferred to a
        follow-up commit; the canonical ``Data/zonal_test`` fixture uses
        ``NotModel`` for both).
    """
    from pyomo.environ import Set, Param

    from .models.formulations_network import (
        add_network_constraints,
        add_network_expressions,
        add_network_parameters,
        add_network_sets,
        add_network_variables,
    )

    if with_resilience_constraints:
        raise NotImplementedError(
            "Resiliency under "
            f"Network='{AREA_TRANSPORTATION_MODEL_NETWORK}' is not "
            "implemented in this phase (PRD \u00a75.8). Use "
            f"Network='{COPPER_PLATE_NETWORK}' for resiliency runs."
        )

    imports_form = get_formulation(data, component="Imports")
    exports_form = get_formulation(data, component="Exports")
    if (
        imports_form != IMPORTS_EXPORTS_NOT_MODEL
        or exports_form != IMPORTS_EXPORTS_NOT_MODEL
    ):
        raise NotImplementedError(
            "External imports/exports under "
            f"Network='{AREA_TRANSPORTATION_MODEL_NETWORK}' are not yet "
            "supported (commit #9b minimum scope). Set both Imports and "
            f"Exports rows in formulations.csv to '{IMPORTS_EXPORTS_NOT_MODEL}' "
            "or use a CopperPlateNetwork run."
        )

    logging.info(
        "Instantiating zonal SDOM model with %d areas and %d lines.",
        len(data["areas"]),
        len(data["lines"]),
    )

    profiler = ModelInitProfiler(track_memory=True, enabled=True)
    profiler.start()

    def _create_skeleton():
        m = ConcreteModel(name=model_name)
        m.A = Set(
            initialize=[a["area_id"] for a in data["areas"]], ordered=True
        )
        m.area = Block(m.A)
        for a in m.A:
            _add_area_subblocks(
                m.area[a],
                with_resilience_constraints=with_resilience_constraints,
            )
        return m

    model = profiler.measure_step("Create model & area blocks", _create_skeleton)

    # Build each area block via the legacy per-host builder sequence.
    for area_id in model.A:
        slice_dict = _build_per_area_data_slice(data, area_id)
        profiler.measure_step(
            f"Build area '{area_id}'",
            _build_one_area,
            model.area[area_id],
            slice_dict,
            n_hours=n_hours,
            with_resilience_constraints=with_resilience_constraints,
        )

    # Top-level shared sets/params for the system-wide constraints. Each
    # area block already has its own ``h`` and ``GenMix_Target`` (mirrored
    # from the legacy initialize_params); we expose top-level copies so the
    # genmix and supply balance constraints have a single dispatch surface.
    # Pyomo forbids sharing Set objects across blocks, so we create a fresh
    # RangeSet at the top level mirroring the per-area ``h``. We use the
    # same ``check_n_hours`` round-up rule the legacy ``initialize_sets``
    # applies, so budget-formulation hour adjustments stay consistent
    # between the per-area blocks and the top-level model.
    from pyomo.environ import RangeSet
    from .constants import VALID_HYDRO_FORMULATIONS_TO_BUDGET_MAP
    from .initializations import check_n_hours

    hydro_formulation = get_formulation(data, component="hydro")
    if "Budget" in hydro_formulation:
        n_hours_checked = check_n_hours(
            n_hours, VALID_HYDRO_FORMULATIONS_TO_BUDGET_MAP[hydro_formulation]
        )
        model.h = RangeSet(1, n_hours_checked)
    else:
        model.h = RangeSet(1, n_hours)
    # GenMix_Target is identical across areas (read from data["scalars"]);
    # expose it on the top-level model for the system-wide constraint.
    model.GenMix_Target = Param(
        initialize=float(data["scalars"].loc["GenMix_Target"].Value),
        mutable=True,
    )

    # ---------- Transportation network on top-level model ----------------
    lines = data["lines"]
    line_ids = [l["line_id"] for l in lines]
    line_from = {l["line_id"]: l["from_area"] for l in lines}
    line_to = {l["line_id"]: l["to_area"] for l in lines}

    cap_ft_df = data["line_cap_ft"]
    cap_tf_df = data["line_cap_tf"]

    # Slice the cap DataFrames to the model's hour set (legacy fixtures use
    # 8760 rows but n_hours can be smaller for tests).
    hours_used = list(model.h)

    def _cap_dict(cap_df):
        if cap_df is None or cap_df.empty:
            return {}
        return {
            (l, h): float(cap_df.loc[h, l])
            for l in line_ids
            for h in hours_used
        }

    cap_ft = _cap_dict(cap_ft_df)
    cap_tf = _cap_dict(cap_tf_df)

    profiler.measure_step(
        "Add network sets",
        add_network_sets,
        model,
        lines=line_ids,
        line_from=line_from,
        line_to=line_to,
    )
    profiler.measure_step(
        "Add network parameters",
        add_network_parameters,
        model,
        line_cap_ft=cap_ft,
        line_cap_tf=cap_tf,
    )
    profiler.measure_step("Add network variables", add_network_variables, model)
    profiler.measure_step(
        "Add network constraints", add_network_constraints, model
    )
    profiler.measure_step(
        "Add network expressions", add_network_expressions, model
    )

    # ---------- System-wide constraints + objective ----------------------
    profiler.measure_step(
        "Add zonal supply balance", _add_zonal_supply_balance, model
    )
    profiler.measure_step(
        "Add zonal genmix constraint", _add_zonal_genmix_constraint, model
    )

    def _add_objective():
        model.Obj = Objective(rule=_zonal_objective_rule, sense=minimize)

    profiler.measure_step("Add zonal objective", _add_objective)

    profiler.stop()
    profiler.print_summary_table(logging.getLogger())
    model.profiler = profiler
    return model


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
