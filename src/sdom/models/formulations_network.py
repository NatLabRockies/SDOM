"""Network formulation (transportation model) for SDOM zonal mode.

This module implements the line topology, signed flow variable, directional
capacity constraints, and reporting expressions for the
``AreaTransportationModelNetwork`` formulation (PRD §5.6).

Locked design decisions (PRD §5.6, 2026-05-08):

- Topology lives on the **top-level model** (``model.L``, ``model.line_from``,
  ``model.line_to``, ``model.L_in[a]``, ``model.L_out[a]``); per-area blocks
  consume but do not own it.
- Capacity limits are imposed via explicit ``Constraint`` blocks (not ``Var``
  bounds) so per-direction congestion shadow prices are exposed in the dual.
- A single signed flow variable ``f[l,h] in Reals`` — no auxiliary binary,
  no ``f+/f-`` split; simultaneous bidirectional flow is impossible by
  construction of the bounds.
- ``Z^trans = 0`` placeholder (no transmission investment in this phase).

The zonal path in :func:`sdom.optimization_main.initialize_model` calls these
builders on the root model; area balances consume the resulting signed flows.
"""

from pyomo.environ import (
    Constraint,
    Expression,
    Param,
    Reals,
    Set,
    Var,
)


def add_network_sets(model, *, lines, line_from, line_to):
    r"""Create line set and per-area in/out indexed line sets.

    Parameters
    ----------
    model : pyomo.environ.ConcreteModel
        Top-level model that already exposes ``model.A`` (Set of areas).
    lines : iterable
        Iterable of line identifiers.
    line_from : Mapping[Hashable, Hashable]
        Mapping ``{line_id: origin_area_id}`` with origin areas in ``model.A``.
    line_to : Mapping[Hashable, Hashable]
        Mapping ``{line_id: destination_area_id}`` with destination areas in
        ``model.A``.

    Returns
    -------
    pyomo.environ.ConcreteModel
        The same ``model`` instance with new attributes attached:

        - ``model.L`` : ``Set`` of line ids.
        - ``model.line_from`` : ``Param(model.L, within=model.A)``.
        - ``model.line_to`` : ``Param(model.L, within=model.A)``.
        - ``model.L_in[a]`` : ``Set(model.A, ...)`` of lines with
          ``line_to[l] == a``.
        - ``model.L_out[a]`` : ``Set(model.A, ...)`` of lines with
          ``line_from[l] == a``.

    Notes
    -----
    ``model.L_in`` and ``model.L_out`` are constructed from local Python
    dicts (rather than rules that introspect ``model.line_from`` /
    ``model.line_to``) to avoid Pyomo deferred-construction ordering issues.

    .. math::

       \mathcal L_{in}(a)=\{\ell\in\mathcal L:\operatorname{to}(\ell)=a\},
       \qquad
       \mathcal L_{out}(a)=\{\ell\in\mathcal L:\operatorname{from}(\ell)=a\}.

    :math:`\mathcal L` is ``model.L`` and :math:`a` indexes ``model.A``.
    These sets define line orientation; actual flow may have either sign.
    """
    line_ids = list(lines)
    from_map = dict(line_from)
    to_map = dict(line_to)

    model.L = Set(initialize=line_ids, ordered=True)
    model.line_from = Param(model.L, within=model.A, initialize=from_map)
    model.line_to = Param(model.L, within=model.A, initialize=to_map)

    in_map = {a: [l for l in line_ids if to_map[l] == a] for a in model.A}
    out_map = {a: [l for l in line_ids if from_map[l] == a] for a in model.A}

    model.L_in = Set(model.A, initialize=lambda m, a: in_map[a], ordered=True)
    model.L_out = Set(model.A, initialize=lambda m, a: out_map[a], ordered=True)

    return model


def add_network_parameters(model, *, line_cap_ft, line_cap_tf):
    """Create directional line capacity parameters indexed by ``(L, h)``.

    Parameters
    ----------
    model : pyomo.environ.ConcreteModel
        Model with ``model.L`` and ``model.h`` already constructed.
    line_cap_ft : Mapping[Tuple[Hashable, Hashable], float]
        Mapping ``{(line_id, hour): MW}`` for the from→to direction.
    line_cap_tf : Mapping[Tuple[Hashable, Hashable], float]
        Mapping ``{(line_id, hour): MW}`` for the to→from direction.

    Returns
    -------
    pyomo.environ.ConcreteModel
        Same ``model`` with new attributes:

        - ``model.LineCap_FT`` : ``Param(model.L, model.h)`` (MW).
        - ``model.LineCap_TF`` : ``Param(model.L, model.h)`` (MW).
    """
    model.LineCap_FT = Param(
        model.L, model.h, initialize=dict(line_cap_ft), mutable=False
    )
    model.LineCap_TF = Param(
        model.L, model.h, initialize=dict(line_cap_tf), mutable=False
    )
    return model


def add_network_variables(model):
    r"""Create the signed flow variable ``model.f[l,h]`` over ``Reals``.

    Parameters
    ----------
    model : pyomo.environ.ConcreteModel
        Model with ``model.L`` and ``model.h`` already constructed.

    Returns
    -------
    pyomo.environ.ConcreteModel
        Same ``model`` with new attribute ``model.f`` — a ``Var`` over
        ``model.L × model.h`` with domain ``Reals`` and **no bounds** set.
        Capacity limits are enforced by :func:`add_network_constraints`.

    Notes
    -----
    .. math::

       f_{\ell h}\in\mathbb R\qquad(\ell\in\mathcal L,\ h\in\mathcal H).

    Flow is MW, positive from ``line_from`` to ``line_to`` and negative in
    reverse. There are no separate directional decision variables or losses.
    """
    model.f = Var(model.L, model.h, domain=Reals)
    return model


def _f_upper_rule(model, l, h):
    r"""Return the forward directional flow-capacity inequality.

    Parameters
    ----------
    model : pyomo.environ.ConcreteModel
        Root model with ``f`` and ``LineCap_FT``.
    l : hashable
        Line identifier.
    h : int
        Modeled hour.

    Returns
    -------
    pyomo.core.expr.relational_expr.InequalityExpression
        Forward flow upper bound.

    Notes
    -----
    .. math::

       f_{\ell h}\le\bar f^{FT}_{\ell h}.

    :math:`f_{\ell h}` is ``f[l,h]`` and :math:`\bar f^{FT}_{\ell h}` is
    ``LineCap_FT[l,h]``, both MW. Positive flow follows line orientation.
    """
    return model.f[l, h] <= model.LineCap_FT[l, h]


def _f_lower_rule(model, l, h):
    r"""Return the reverse directional flow-capacity inequality.

    Parameters
    ----------
    model : pyomo.environ.ConcreteModel
        Root model with ``f`` and ``LineCap_TF``.
    l : hashable
        Line identifier.
    h : int
        Modeled hour.

    Returns
    -------
    pyomo.core.expr.relational_expr.InequalityExpression
        Reverse flow lower bound.

    Notes
    -----
    .. math::

       f_{\ell h}\ge-\bar f^{TF}_{\ell h}.

    :math:`f_{\ell h}` is ``f[l,h]`` and :math:`\bar f^{TF}_{\ell h}` is
    ``LineCap_TF[l,h]``, both MW. Reverse flow has a negative sign.
    """
    return model.f[l, h] >= -model.LineCap_TF[l, h]


def add_network_constraints(model):
    r"""Create directional flow capacity constraints.

    Parameters
    ----------
    model : pyomo.environ.ConcreteModel
        Model with ``model.f``, ``model.LineCap_FT`` and ``model.LineCap_TF``.

    Returns
    -------
    pyomo.environ.ConcreteModel
        Same ``model`` with two new constraint blocks:

        - ``model.f_upper[l,h]`` : ``f[l,h] <=  LineCap_FT[l,h]``.
        - ``model.f_lower[l,h]`` : ``f[l,h] >= -LineCap_TF[l,h]``.

    Notes
    -----
    These are explicit ``Constraint`` blocks (rather than bounds on
    ``model.f``) so that congestion shadow prices are accessible per
    direction in the dual solution.

    .. math::

       -\bar f^{TF}_{\ell h}\le f_{\ell h}\le\bar f^{FT}_{\ell h}.

    :math:`f` is ``model.f`` (MW); forward/reverse capacities are
    ``LineCap_FT`` / ``LineCap_TF`` (MW). Positive flow follows the
    declared from-to orientation; negative flow reverses it.
    """
    model.f_upper = Constraint(model.L, model.h, rule=_f_upper_rule)
    model.f_lower = Constraint(model.L, model.h, rule=_f_lower_rule)
    return model


def _f_FT_rule(model, l, h):
    r"""Return the forward-oriented signed flow for reporting.

    Parameters
    ----------
    model : pyomo.environ.ConcreteModel
        Root model with ``f``.
    l : hashable
        Line identifier.
    h : int
        Modeled hour.

    Returns
    -------
    pyomo.core.base.var.VarData
        Signed flow variable in MW, without clipping.

    Notes
    -----
    .. math::

       \widetilde f^{FT}_{\ell h}=f_{\ell h}.

    :math:`f` is ``model.f``. Negative values denote reverse flow.
    """
    return model.f[l, h]


def _f_TF_rule(model, l, h):
    r"""Return the reverse-oriented signed flow for reporting.

    Parameters
    ----------
    model : pyomo.environ.ConcreteModel
        Root model with ``f``.
    l : hashable
        Line identifier.
    h : int
        Modeled hour.

    Returns
    -------
    pyomo.core.expr.numeric_expr.NumericValue
        Negated signed flow in MW, without clipping.

    Notes
    -----
    .. math::

       \widetilde f^{TF}_{\ell h}=-f_{\ell h}.

    :math:`f` is ``model.f``. Positive values denote reverse flow.
    """
    return -model.f[l, h]


def add_network_expressions(model):
    r"""Create reporting-only signed flow expressions.

    Parameters
    ----------
    model : pyomo.environ.ConcreteModel
        Model with ``model.f`` already constructed.

    Returns
    -------
    pyomo.environ.ConcreteModel
        Same ``model`` with two ``Expression`` blocks:

        - ``model.f_FT[l,h]`` : signed scalar ``model.f[l,h]``.
        - ``model.f_TF[l,h]`` : signed scalar ``-model.f[l,h]``.

    Notes
    -----
    These expressions are **reporting only**. The expressions stored here are

    .. math::

       \widetilde f^{FT}_{\ell h}=f_{\ell h},\qquad
       \widetilde f^{TF}_{\ell h}=-f_{\ell h}.

    Flow is MW. The nonnegative directional reporting quantities are

    .. math::

       f^{FT}_{\ell h}=\max(f_{\ell h},0),\qquad
       f^{TF}_{\ell h}=\max(-f_{\ell h},0).

    Clipping is nonlinear and is performed after evaluating the signed
    expressions, not inside the LP. A single signed variable represents
    only one physical direction at a time. Downstream reporting clips to
    zero, e.g.::

        from pyomo.environ import value
        ft = max(value(model.f_FT[l, h]), 0.0)
        tf = max(value(model.f_TF[l, h]), 0.0)

    These ``Expression`` blocks add no decision variables to the LP and are
    not referenced by any constraint or by the objective.
    """
    model.f_FT = Expression(model.L, model.h, rule=_f_FT_rule)
    model.f_TF = Expression(model.L, model.h, rule=_f_TF_rule)
    return model


def network_transmission_cost_rule(model):
    r"""Return the transmission cost term ``Z^trans``.

    Parameters
    ----------
    model : pyomo.environ.ConcreteModel
        Top-level model (unused; placeholder signature).

    Returns
    -------
    int
        Always ``0`` in this phase — transmission investment is out of scope
        (PRD §5.6).

    Notes
    -----
    .. math::

       Z^{trans}=0.

    This placeholder adds no line-investment or flow-dependent cost.
    """
    return 0
