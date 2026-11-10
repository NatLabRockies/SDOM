"""Extract marginal prices and congestion duals from pricing-LP results."""


import numpy as np
import pandas as pd
from pyomo.environ import value as pyo_value

_MARGINAL_PRICE_COLUMNS = [
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


_LINE_CONGESTION_DUAL_COLUMNS = [
    "line_id",
    "from_area",
    "to_area",
    "hour",
    "f_upper_dual",
    "f_lower_dual",
    "line_congestion_dual_sum",
]


def collect_marginal_prices_from_model(
    model,
    pricing_result,
    *,
    pricing_method: str = "fixed_decision_lp_appsi_highs",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Collect marginal prices and directional capacity duals from a pricing LP.

    Parameters
    ----------
    model : pyomo.environ.ConcreteModel
        Fixed-decision LP model solved with an imported ``dual`` suffix.
    pricing_result : pyomo.opt.SolverResults or None
        Pricing solve result. ``None`` represents an unavailable pricing solve.
    pricing_method : str, optional
        Identifier for the solver and fixed-decision LP method used for
        pricing. Defaults to ``"fixed_decision_lp_appsi_highs"``.

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame]
        Marginal-price rows and directional line-dual audit rows. Any failed
        pricing solve or missing required dual leaves numeric price fields NaN
        and marks every price row unavailable.
    """
    method = pricing_method
    is_zonal = hasattr(model, "A") and hasattr(model, "area")
    areas = list(model.A) if is_zonal else ["copperplate"]
    hours = list(model.h)
    rows = [(hour, area) for hour in hours for area in areas]

    def unavailable(status: str, line_df=None):
        price_df = pd.DataFrame(
            [
                {
                    "hour": hour,
                    "area_id": area,
                    "marginal_price_USD_per_MWh": np.nan,
                    "generation_component_USD_per_MWh": np.nan,
                    "congestion_component_USD_per_MWh": np.nan,
                    "supply_balance_dual": np.nan,
                    "line_congestion_dual_sum": np.nan,
                    "pricing_method": method,
                    "pricing_status": status,
                }
                for hour, area in rows
            ],
            columns=_MARGINAL_PRICE_COLUMNS,
        )
        return price_df, line_df if line_df is not None else pd.DataFrame(columns=_LINE_CONGESTION_DUAL_COLUMNS)

    termination_condition = (
        None if pricing_result is None else pricing_result.solver.termination_condition
    )
    if (
        termination_condition is None
        or str(termination_condition).split(".")[-1].lower() != "optimal"
    ):
        return unavailable("unavailable_pricing_lp")

    dual = getattr(model, "dual", None)
    if dual is None:
        return unavailable("unavailable_duals")

    supply_duals = {}
    for hour, area in rows:
        balance_component = (
            model.area[area].SupplyBalance if is_zonal else model.SupplyBalance
        )
        balance = (
            balance_component[hour]
            if balance_component.is_indexed()
            else balance_component
        )
        value = dual.get(balance)
        if value is None:
            return unavailable("unavailable_duals")
        supply_duals[hour, area] = float(value)

    line_rows = []
    line_sums = {}
    if is_zonal:
        for line in model.L:
            from_area = pyo_value(model.line_from[line])
            to_area = pyo_value(model.line_to[line])
            for hour in hours:
                upper = dual.get(model.f_upper[line, hour])
                lower = dual.get(model.f_lower[line, hour])
                if upper is None or lower is None:
                    return unavailable("unavailable_duals")
                dual_sum = float(upper) + float(lower)
                line_sums[hour, line] = dual_sum
                line_rows.append(
                    {
                        "line_id": line,
                        "from_area": from_area,
                        "to_area": to_area,
                        "hour": hour,
                        "f_upper_dual": float(upper),
                        "f_lower_dual": float(lower),
                        "line_congestion_dual_sum": dual_sum,
                    }
                )

    references = {"copperplate": "copperplate"}
    if is_zonal:
        neighbors = {area: set() for area in areas}
        for line in model.L:
            origin = pyo_value(model.line_from[line])
            destination = pyo_value(model.line_to[line])
            neighbors[origin].add(destination)
            neighbors[destination].add(origin)
        unvisited = set(neighbors)
        while unvisited:
            root = min(unvisited, key=str)
            component, pending = set(), [root]
            while pending:
                area = pending.pop()
                if area in component:
                    continue
                component.add(area)
                pending.extend(neighbors[area] - component)
            unvisited -= component
            reference = min(component, key=str)
            references.update({area: reference for area in component})

    price_rows = []
    for hour, area in rows:
        supply_balance_dual = supply_duals[hour, area]
        price = -supply_balance_dual
        reference_price = -supply_duals[hour, references[area]]
        line_sum = (
            sum(line_sums[hour, line] for line in model.L if area in {
                pyo_value(model.line_from[line]), pyo_value(model.line_to[line])
            })
            if is_zonal else 0.0
        )
        price_rows.append(
            {
                "hour": hour,
                "area_id": area,
                "marginal_price_USD_per_MWh": price,
                "generation_component_USD_per_MWh": reference_price,
                "congestion_component_USD_per_MWh": price - reference_price,
                "supply_balance_dual": supply_balance_dual,
                "line_congestion_dual_sum": line_sum,
                "pricing_method": method,
                "pricing_status": "available",
            }
        )
    return (
        pd.DataFrame(price_rows, columns=_MARGINAL_PRICE_COLUMNS),
        pd.DataFrame(line_rows, columns=_LINE_CONGESTION_DUAL_COLUMNS),
    )
