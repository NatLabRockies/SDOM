"""Select component formulations and apply registered missing-row defaults."""

import logging

from ..constants import (
    DEFAULT_FORMULATIONS_BY_COMPONENT,
)
from .validation import validate_formulation_selection

_GET_FORMULATION_NO_DEFAULT = object()


def get_formulation(data: dict, component: str = "hydro", *, default=_GET_FORMULATION_NO_DEFAULT):
    """Retrieve the selected formulation for a specific model component.

    Extracts the formulation name from the loaded formulations DataFrame for a
    given component (e.g., hydro, imports, exports, network). Used throughout
    model initialization to conditionally add constraints based on formulation.

    Parameters
    ----------
    data : dict
        Dictionary containing the 'formulations' DataFrame loaded from
        ``formulations.csv``.
    component : str, optional
        Component name to look up (case-insensitive). Examples: ``'hydro'``,
        ``'Imports'``, ``'Exports'``, ``'Network'``. Defaults to ``'hydro'``.
    default : str or None, optional
        Value returned (and logged at INFO level) when the requested component
        row is absent. Takes precedence over registered component defaults.
        If omitted, Thermal, Network, and Reserves use their central defaults;
        other missing components retain the existing ``IndexError`` behavior.
        Explicit ``None`` remains a valid caller-supplied default.

    Returns
    -------
    str or None
        The selected formulation or missing-row default.

    Raises
    ------
    ValueError
        If a component registered in
        ``FORMULATION_VALIDATION_BY_COMPONENT`` has duplicate rows or an
        unsupported, blank, or null selection. Currently only Thermal is
        registered; defaults never replace invalid supplied selections.
    IndexError
        If no row, explicit default, or registered default exists.

    Notes
    -----
    - Performs case-insensitive matching on component name.
    - Unregistered components retain first-match lookup behavior.
    - The ``default`` keyword is keyword-only to keep the function's mandatory
      positional surface unchanged.
    """
    key = component.lower()
    formulations = data["formulations"]
    matches = formulations.loc[formulations["Component"].str.lower() == key]["Formulation"]
    validate_formulation_selection(matches, component=component)
    if matches.empty:
        if default is _GET_FORMULATION_NO_DEFAULT:
            default = DEFAULT_FORMULATIONS_BY_COMPONENT.get(key, _GET_FORMULATION_NO_DEFAULT)
        if default is _GET_FORMULATION_NO_DEFAULT:
            return matches.iloc[0]  # original IndexError surface
        logging.info(
            "Component '%s' not present in formulations.csv. Falling back to default '%s'.",
            component,
            default,
        )
        return default
    selected = matches.iloc[0]
    return selected


def get_network_formulation(data: dict) -> str:
    """Return the active Network formulation for a loaded data dict.

    Thin accessor on top of :func:`get_formulation` that hides the storage
    detail of how the Network row is exposed in ``data``. Production code
    (and downstream callers) should use this helper instead of indexing
    ``data`` directly so the underlying representation can evolve without
    breaking consumers.

    Parameters
    ----------
    data : dict
        Data dictionary as returned by :func:`load_data` (or any partial
        dict that already contains the ``"formulations"`` DataFrame).

    Returns
    -------
    str
        One of the keys of
        :data:`~sdom.constants.VALID_NETWORK_FORMULATIONS_TO_DESCRIPTION_MAP`,
        defaulting to :data:`~sdom.constants.DEFAULT_NETWORK_FORMULATION`
        when the ``Network`` row is absent.
    """
    return get_formulation(data, component="Network")
