"""Assemble per-area results, system rollups, and interregional exchanges."""


import logging

import numpy as np
import pandas as pd
from pyomo.environ import value as pyo_value

from ..common.utilities import safe_pyomo_value
from ._values import _value_or_zero
from .collect_individual_host_results import _collect_host_metrics
from .containers import _RESULT_ATTRIBUTE_UNITS, OptimizationResults
from .results_aggregation import _aggregate_zonal_generation_by_hour, _merge_dict_sum
from .summary import (
    _append_hydro_curtailment_summary,
    _build_summary_dataframe,
    _build_zonal_summary_dataframe,
)


def _build_interregional_exchanges_df(model) -> pd.DataFrame:
    """Build the per-line / per-hour interregional exchanges DataFrame.

    Implements PRD §2.4: one row per ``(line_id, hour)`` with signed flow,
    decomposed FT / TF flows, asymmetric capacities, and NaN-safe
    utilization ratios.

    Parameters
    ----------
    model : pyomo.environ.ConcreteModel
        Solved zonal model with ``model.L``, ``model.h``, ``model.f``,
        ``model.line_from``, ``model.line_to``, ``model.LineCap_FT``,
        ``model.LineCap_TF``.

    Returns
    -------
    pandas.DataFrame
        Empty DataFrame if ``model.L`` is empty; otherwise a DataFrame
        with the schema specified in PRD §2.4.
    """
    columns = [
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
    if not hasattr(model, "L") or len(model.L) == 0:
        return pd.DataFrame(columns=columns)

    lines = list(model.L)
    hours = list(model.h)
    n_lines = len(lines)
    n_hours = len(hours)
    n_rows = n_lines * n_hours

    line_ids = np.repeat(np.asarray(lines, dtype=object), n_hours)
    hour_ids = np.tile(np.asarray(hours), n_lines)
    from_areas = np.repeat(
        np.asarray([pyo_value(model.line_from[l]) for l in lines], dtype=object),
        n_hours,
    )
    to_areas = np.repeat(
        np.asarray([pyo_value(model.line_to[l]) for l in lines], dtype=object),
        n_hours,
    )

    f_signed = np.fromiter(
        (_value_or_zero(model.f[l, h]) for l in lines for h in hours),
        dtype=float,
        count=n_rows,
    )
    cap_ft = np.fromiter(
        (float(pyo_value(model.LineCap_FT[l, h])) for l in lines for h in hours),
        dtype=float,
        count=n_rows,
    )
    cap_tf = np.fromiter(
        (float(pyo_value(model.LineCap_TF[l, h])) for l in lines for h in hours),
        dtype=float,
        count=n_rows,
    )
    flow_ft = np.maximum(f_signed, 0.0)
    flow_tf = np.maximum(-f_signed, 0.0)

    df = pd.DataFrame(
        {
            "line_id": line_ids,
            "from_area": from_areas,
            "to_area": to_areas,
            "hour": hour_ids,
            "flow_signed_MW": f_signed,
            "flow_FT_MW": flow_ft,
            "flow_TF_MW": flow_tf,
            "cap_FT_MW": cap_ft,
            "cap_TF_MW": cap_tf,
        },
        columns=columns[:-2],
    )
    df["utilization_FT"] = np.where(
        df["cap_FT_MW"].to_numpy() > 0,
        df["flow_FT_MW"].to_numpy() / np.where(
            df["cap_FT_MW"].to_numpy() > 0, df["cap_FT_MW"].to_numpy(), 1.0
        ),
        np.nan,
    )
    df["utilization_TF"] = np.where(
        df["cap_TF_MW"].to_numpy() > 0,
        df["flow_TF_MW"].to_numpy() / np.where(
            df["cap_TF_MW"].to_numpy() > 0, df["cap_TF_MW"].to_numpy(), 1.0
        ),
        np.nan,
    )
    return df[columns]


def _collect_results_zonal(model, solver_result, *, case_name: str = "run") -> OptimizationResults:
    """Collect zonal results from a solved ``AreaTransportationModelNetwork`` model.

    Builds per-area DataFrames and dicts via :func:`_collect_host_metrics`
    on each ``model.area[a]`` block, aggregates them into top-level frames
    with a leading ``Area`` column, sums the scalar dicts across areas for
    system-level rollups, and constructs the
    :attr:`OptimizationResults.interregional_exchanges_df` per PRD §2.4.

    Per-area summaries are attached to
    :attr:`OptimizationResults.area_summary_df`. A system-level
    :attr:`OptimizationResults.summary_df` is built from the aggregate result
    dictionaries so the standard CSV export and plotting APIs work for zonal
    results as well.

    Parameters mirror :func:`collect_results_from_model`.
    """
    logging.info("Collecting SDOM zonal results...")

    results = OptimizationResults()
    results.attribute_units = _RESULT_ATTRIBUTE_UNITS.copy()
    results.is_zonal = True
    results.areas = list(model.A)
    if hasattr(model, "L"):
        results.lines = [
            {
                "line_id": l,
                "from_area": pyo_value(model.line_from[l]),
                "to_area": pyo_value(model.line_to[l]),
            }
            for l in model.L
        ]

    # Solver information ---------------------------------------------------
    results.termination_condition = str(solver_result.solver.termination_condition)
    results.solver_status = str(solver_result.solver.status)
    if solver_result.problem:
        problem = solver_result.problem[0]
        def _gv(val):
            return val.value if hasattr(val, "value") else val
        results.problem_info = {
            "Number of constraints": _gv(problem.get("Number of constraints", 0)),
            "Number of variables": _gv(problem.get("Number of variables", 0)),
            "Number of binary variables": _gv(problem.get("Number of binary variables", 0)),
            "Number of objectives": _gv(problem.get("Number of objectives", 0)),
            "Number of nonzeros": _gv(problem.get("Number of nonzeros", 0)),
        }

    # Top-level scalars ----------------------------------------------------
    results.total_cost = safe_pyomo_value(model.Obj.expr)
    results.gen_mix_target = float(model.GenMix_Target.value)

    # Hours come from the top-level model (mirrors per-area host.h).
    hours = list(model.h)

    # Per-area collection --------------------------------------------------
    gen_pieces = []
    storage_pieces = []
    thermal_pieces = []
    plants_pieces = []
    storage_tech_set = set()
    hydro_budget_mwh = 0.0
    hydro_unused_mwh = 0.0
    for a in results.areas:
        host = model.area[a]
        bundle = _collect_host_metrics(host, hours, case_name=case_name)
        budget, unused = bundle["hydro_budget_energy"]
        hydro_budget_mwh += budget
        hydro_unused_mwh += unused
        storage_tech_set.update(bundle["storage_tech_list"])

        results.area_capacity[a] = bundle["capacity"]
        results.area_storage_capacity[a] = bundle["storage_capacity"]
        results.area_generation_totals[a] = bundle["generation_totals"]
        results.area_cost_breakdown[a] = bundle["cost_breakdown"]

        gen_df_a = bundle["generation_df"].copy()
        if not gen_df_a.empty:
            gen_df_a.insert(0, "Area", a)
            gen_pieces.append(gen_df_a)
        results.area_generation_df[a] = bundle["generation_df"]

        storage_df_a = bundle["storage_df"].copy()
        if not storage_df_a.empty:
            insert_pos = list(storage_df_a.columns).index("Hour") + 1
            storage_df_a.insert(insert_pos, "Area", a)
            storage_pieces.append(storage_df_a)
        results.area_storage_df[a] = bundle["storage_df"]

        thermal_df_a = bundle["thermal_generation_df"].copy()
        thermal_df_a.insert(1, "Area", a)
        thermal_pieces.append(thermal_df_a)
        results.area_thermal_generation_df[a] = bundle["thermal_generation_df"]

        plants_df_a = bundle["installed_plants_df"].copy()
        if not plants_df_a.empty:
            insert_pos = list(plants_df_a.columns).index("Plant ID") + 1
            plants_df_a.insert(insert_pos, "Area", a)
            plants_pieces.append(plants_df_a)
        results.area_installed_plants_df[a] = bundle["installed_plants_df"]

        # Per-area summary frame: reuse _build_summary_dataframe with the
        # area block as the host. The summary helper only touches
        # ``storage`` / ``demand`` / ``imports`` / ``exports`` / ``pv`` /
        # ``wind`` / ``h`` on the host, all of which exist on the area
        # block (imports/exports guarded by hasattr). ``total_cost`` for
        # the per-area summary is the sum of the area's cost components.
        per_area_results = OptimizationResults(
            total_cost=(
                bundle["cost_breakdown"]["capex"]["All"]
                + bundle["cost_breakdown"]["power_capex"]["All"]
                + bundle["cost_breakdown"]["energy_capex"]["All"]
                + bundle["cost_breakdown"]["fom"]["All"]
                + bundle["cost_breakdown"]["vom"]["All"]
                + bundle["cost_breakdown"]["fuel_cost"]["Thermal"]
                + bundle["cost_breakdown"]["imports_cost"]
                - bundle["cost_breakdown"]["exports_revenue"]
                + sum(bundle["cost_breakdown"]["curtailment_cost"].values())
            ),
            capacity=bundle["capacity"],
            storage_capacity=bundle["storage_capacity"],
            generation_totals=bundle["generation_totals"],
            cost_breakdown=bundle["cost_breakdown"],
        )
        results.area_summary_df[a] = _build_summary_dataframe(
            host, per_area_results, bundle["storage_tech_list"]
        )

    # Top-level concatenated DataFrames ------------------------------------
    if gen_pieces:
        results.generation_df = pd.concat(gen_pieces, ignore_index=True)
        results.system_generation_df = _aggregate_zonal_generation_by_hour(
            results.generation_df
        )
    if storage_pieces:
        results.storage_df = pd.concat(storage_pieces, ignore_index=True)
    if thermal_pieces:
        results.thermal_generation_df = pd.concat(thermal_pieces, ignore_index=True)
    if plants_pieces:
        results.installed_plants_df = pd.concat(plants_pieces, ignore_index=True)

    # System-level scalar rollups (sum across areas) -----------------------
    capacity_sys: dict = {}
    storage_capacity_sys: dict = {}
    generation_totals_sys: dict = {}
    cost_breakdown_sys: dict = {}
    for a in results.areas:
        _merge_dict_sum(capacity_sys, results.area_capacity[a])
        _merge_dict_sum(storage_capacity_sys, results.area_storage_capacity[a])
        _merge_dict_sum(generation_totals_sys, results.area_generation_totals[a])
        _merge_dict_sum(cost_breakdown_sys, results.area_cost_breakdown[a])
    results.capacity = capacity_sys
    results.storage_capacity = storage_capacity_sys
    results.generation_totals = generation_totals_sys
    results.cost_breakdown = cost_breakdown_sys
    results.summary_df = _append_hydro_curtailment_summary(
        _build_zonal_summary_dataframe(results, sorted(storage_tech_set)),
        (hydro_budget_mwh, hydro_unused_mwh),
    )

    # Interregional exchanges (PRD §2.4) -----------------------------------
    results.interregional_exchanges_df = _build_interregional_exchanges_df(model)

    logging.info(
        "Zonal results collected: %d areas, %d lines, including a system-level "
        "summary_df.",
        len(results.areas),
        len(results.lines),
    )

    return results
