"""Scaffolding tests for the zonal Block-construction path of ``initialize_model``.

Commit #9a (PR #53) only ships the dispatcher; the per-area Block path is
deferred to commit #9b. This file pins the dispatcher's contract:

- Zonal data (``Network=AreaTransportationModelNetwork``) must raise
  :class:`NotImplementedError` with a clear, actionable message.
- The error message must reference the PRD section so future maintainers can
  trace the deferred work.

Once commit #9b lands, this file should be **extended** (not replaced) with
positive assertions on ``model.A``, ``model.area[a]`` Blocks, ``model.f``
bounds, and per-area supply balance constraints.
"""

from __future__ import annotations

import os

import pytest

from sdom import initialize_model, load_data
from sdom.constants import (
    AREA_TRANSPORTATION_MODEL_NETWORK,
    COPPER_PLATE_NETWORK,
)
from sdom.io_manager import get_network_formulation


REL_ZONAL_FIXTURE = "Data/zonal_test"


def _abs_data_path(rel: str) -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", rel))


def test_zonal_data_raises_not_implemented_error():
    """The zonal fixture (AreaTransportationModelNetwork) defers to #9b."""
    data = load_data(_abs_data_path(REL_ZONAL_FIXTURE))

    # Sanity: fixture is the canonical zonal setup.
    assert get_network_formulation(data) == AREA_TRANSPORTATION_MODEL_NETWORK
    assert len(data["areas"]) >= 2

    with pytest.raises(NotImplementedError) as excinfo:
        initialize_model(data, n_hours=24)

    msg = str(excinfo.value)
    assert "commit #9b" in msg
    assert "Network=" in msg
    assert AREA_TRANSPORTATION_MODEL_NETWORK in msg


def test_dispatcher_classification_helpers_are_consistent():
    """``data['areas']`` and ``get_network_formulation`` agree on the dispatch axis."""
    legacy = load_data(
        _abs_data_path("Data/no_exchange_run_of_river")
    )
    assert get_network_formulation(legacy) == COPPER_PLATE_NETWORK
    assert len(legacy["areas"]) == 1

    zonal = load_data(_abs_data_path(REL_ZONAL_FIXTURE))
    assert get_network_formulation(zonal) == AREA_TRANSPORTATION_MODEL_NETWORK
    assert len(zonal["areas"]) >= 2
