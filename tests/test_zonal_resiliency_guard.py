"""Dispatcher-level guard: resiliency + AreaTransportationModelNetwork.

PRD §5.8 forbids combining ``with_resilience_constraints=True`` with
``Network=AreaTransportationModelNetwork`` in this phase. The guard lives
in the public :func:`sdom.initialize_model` dispatcher so
callers fail fast before any zonal Block construction runs.

A defensive copy of the same guard remains inside the private
``_initialize_model_zonal`` helper to protect direct callers; both paths
are covered here.
"""

from __future__ import annotations

import os

import pytest

from sdom import initialize_model, load_data
from sdom.constants import (
    AREA_TRANSPORTATION_MODEL_NETWORK,
    COPPER_PLATE_NETWORK,
)
from sdom.optimization_main import _initialize_model_zonal


REL_ZONAL_FIXTURE = "Data/zonal_test"


def _abs_data_path(rel: str) -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", rel))


@pytest.fixture(scope="module")
def zonal_data():
    return load_data(_abs_data_path(REL_ZONAL_FIXTURE))


def test_dispatcher_raises_before_zonal_construction(zonal_data, monkeypatch):
    """The dispatcher must raise BEFORE delegating to ``_initialize_model_zonal``.

    Spies on the private helper to prove it is never entered when the
    guard fires. PRD §5.8 traceability: the message must reference
    ``AreaTransportationModelNetwork`` and ``§5.8``.
    """
    sentinel = {"called": False}

    def _spy(*args, **kwargs):  # pragma: no cover - must not run
        sentinel["called"] = True
        raise AssertionError("zonal builder must not be reached")

    monkeypatch.setattr(
        "sdom.optimization_main._initialize_model_zonal", _spy
    )

    with pytest.raises(NotImplementedError) as excinfo:
        initialize_model(
            zonal_data, n_hours=24, with_resilience_constraints=True
        )

    msg = str(excinfo.value)
    assert AREA_TRANSPORTATION_MODEL_NETWORK in msg
    assert "\u00a75.8" in msg or "5.8" in msg
    assert COPPER_PLATE_NETWORK in msg
    assert sentinel["called"] is False


def test_dispatcher_allows_resiliency_under_copperplate():
    """Sanity: the new guard must NOT block legacy resiliency runs."""
    legacy = load_data(_abs_data_path("Data/no_exchange_run_of_river"))
    # No exception — legacy fast-path accepts resilience constraints.
    model = initialize_model(
        legacy, n_hours=24, with_resilience_constraints=True
    )
    assert model is not None


def test_private_helper_keeps_defensive_guard(zonal_data):
    """Direct callers of the private helper get the same traceable error."""
    with pytest.raises(NotImplementedError) as excinfo:
        _initialize_model_zonal(
            zonal_data, n_hours=24, with_resilience_constraints=True
        )
    msg = str(excinfo.value)
    assert AREA_TRANSPORTATION_MODEL_NETWORK in msg
    assert "5.8" in msg
