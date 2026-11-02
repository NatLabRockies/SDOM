"""Model optional hourly capability margins with scheduled zonal exchanges."""

import math

from pyomo.core.base.block import ScalarBlock
from pyomo.environ import Constraint, Expression, NonNegativeReals, Param, Var, quicksum, sqrt

from ..io_manager import get_formulation

adequacy_duration_hours = 1


def add_capacity_margin_constraints(host, data: dict) -> None:
    r"""Add ``CapacityMarginFormulation`` to a copperplate or area block.

    Parameters
    ----------
    host : pyomo.core.base.block.BlockData
        Owning system or area with initialized hourly resource components.
        For zonal areas, the parent model's network flows must already exist.
    data : dict
        Loaded inputs. Only the exact Reserves selection
        ``CapacityMarginFormulation`` enables this builder; otherwise it adds
        nothing (missing selection defaults locally to ``notModel``).
        Optional ``capacity_marging_fraction`` is a global dimensionless
        fraction, defaulting to zero.

    Raises
    ------
    ValueError
        If the enabled margin is blank, nonnumeric, nonfinite, or negative.

    Notes
    -----
    For hour :math:`h`, storage :math:`j`, and cyclic predecessor :math:`h^{-}`,
    define the named expression (MW), not a new output variable:

    .. math::

       q^{act}_{jh} := D^{dis}_{jh}-D^{ch}_{jh}+r^{up}_{jh}.

    Only :math:`r^{up}_{jh}\ge0` is a new decision variable. Its bounds are

    .. math::

       q^{act}_{jh}\le P^{dis}_j,\qquad
       T^{adequacy}q^{act}_{jh}\le\sqrt{\eta_j}S_{j,h^{-}},
       \qquad T^{adequacy}=1\ \mathrm{hour}.

    :math:`S` is predecessor end-SOC (MWh), including last-hour SOC for the
    first hour; :math:`\eta` is roundtrip efficiency. Activation replaces
    baseline dispatch, permits charge interruption and within-hour switching,
    and is not gated by the baseline mode binary. Negative activated output
    denotes reduced charging; concurrent charging cannot fund discharge.

    The hourly capability requirement, in MW, is

    .. math::

       \begin{aligned}
       &\sum_k P^{bal}_k+\sum_j q^{act}_{jh}
       +\sum_p\sigma_{ph}\bar p^{pv}_p F^{pv}_p
       +\sum_w\zeta_{wh}\bar p^{wind}_w F^{wind}_w\\
       &\quad+G^{hyd}_h+\alpha^{nuc}\nu_h+\alpha^{oth}\omega_h+N_h
       \ge(1+m)d_h.
       \end{aligned}

    Here :math:`m` is the margin, :math:`d` gross demand, :math:`P^{bal}`
    installed balancing MW (full deterministic availability), and the VRE
    terms are contemporaneous capacity factors times installed MW. Hydro is
    scheduled dispatch; nuclear and other renewables are scaled injections.
    :math:`N_h=0` in copperplate mode. In zonal blocks it is scheduled net
    inflow :math:`N_h=\sum_{\ell\in\mathcal L_{in}(a)}f_{\ell h}
    -\sum_{\ell\in\mathcal L_{out}(a)}f_{\ell h}`.
    Existing signed flows credit imports and deduct exports; they cannot
    increase during activation. No additional reserve transfers or external
    imports are credited. Optional absent resources contribute zero. This is a
    one-hour capability proxy, not operating reserves or repeated-activation
    feasibility; no costs, shortfall slack, or baseline physics are changed.
    """
    selection = get_formulation(data, component="Reserves", default="notModel")
    if not isinstance(selection, str) or selection != "CapacityMarginFormulation":
        return

    name = "capacity_marging_fraction"
    raw = data["scalars"].loc[name, "Value"] if name in data["scalars"].index else 0.0
    try:
        margin = float(raw)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a finite nonnegative fraction; got {raw!r}") from error
    if not math.isfinite(margin) or margin < 0:
        raise ValueError(f"{name} must be a finite nonnegative fraction; got {raw!r}")

    block = ScalarBlock()
    host.add_component("reserves", block)
    block.add_component("capacity_marging_fraction", Param(initialize=margin, within=NonNegativeReals))
    storage = host.storage
    block.add_component("storage_upward_capability", Var(host.h, storage.j, domain=NonNegativeReals))
    block.add_component(
        "storage_activated_net_output",
        Expression(
            host.h,
            storage.j,
            rule=lambda b, h, j: storage.PD[h, j] - storage.PC[h, j] + b.storage_upward_capability[h, j],
        ),
    )
    block.add_component(
        "StoragePower",
        Constraint(
            host.h,
            storage.j,
            rule=lambda b, h, j: b.storage_activated_net_output[h, j] <= storage.Pdis[j],
        ),
    )
    block.add_component(
        "StorageEnergy",
        Constraint(
            host.h,
            storage.j,
            rule=lambda b, h, j: (
                adequacy_duration_hours * b.storage_activated_net_output[h, j]
                <= sqrt(storage.data["Eff", j]) * storage.SOC[host.h.prevw(h), j]
            ),
        ),
    )

    def capability_rule(b, h):
        r"""Return the hourly capability bound with scheduled net inflow.

        Parameters
        ----------
        b : pyomo.core.base.block.BlockData
            Reserves block containing activated storage expressions.
        h : int
            Modeled hour.

        Returns
        -------
        tuple
            ``(required_MW, available_MW_expression, None)`` for Pyomo's
            lower-bound constraint representation.

        Notes
        -----
        Using the resource symbols defined in the enclosing builder,

        .. math::

           (1+m)d_h\le
           \sum_kP^{bal}_k+\sum_jq^{act}_{jh}
           +\sum_p\sigma_{ph}\bar p^{pv}_pF^{pv}_p
           +\sum_w\zeta_{wh}\bar p^{wind}_wF^{wind}_w
           +G^{hyd}_h+\alpha^{nuc}\nu_h+\alpha^{oth}\omega_h+N_h.

        All terms are MW. :math:`N_h` is signed scheduled zonal net inflow,
        or zero for the root copperplate host. Flows are not increased for
        activation, and no external import variable is credited.
        """
        available = (
            host.thermal.total_installed_capacity
            + quicksum(b.storage_activated_net_output[h, j] for j in storage.j)
            + quicksum(
                vre.capacity_factor[h, plant] * vre.plant_installed_capacity[plant]
                for vre in (host.pv, host.wind)
                for plant in vre.plants_set
            )
            + host.hydro.generation[h]
            + host.nuclear.alpha * host.nuclear.ts_parameter[h]
            + host.other_renewables.alpha * host.other_renewables.ts_parameter[h]
        )
        network = host.model()
        if host is not network:
            area = host.index()
            available += quicksum(network.f[line, h] for line in network.L_in[area]) - quicksum(
                network.f[line, h] for line in network.L_out[area]
            )
        return ((1 + margin) * host.demand.ts_parameter[h], available, None)

    block.add_component("Capability", Constraint(host.h, rule=capability_rule))
