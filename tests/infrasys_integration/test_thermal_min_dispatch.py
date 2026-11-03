"""System-owned hourly thermal profile contracts."""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from pyomo.environ import SolverFactory, value

pytest.importorskip("infrasys")
pytest.importorskip("r2x_core")
from infrasys import SingleTimeSeries

from sdom import initialize_model, load_data
from sdom.infrasys_integration.make_system import load_system_from_data, system_to_data_dict
from sdom.infrasys_integration.models import SDOMThermalGenerator
from sdom.infrasys_integration.pyomo_builder import initialize_model_from_system
from tests.test_thermal_min_dispatch import PROFILE, ROOT, controlled_data, enable


@pytest.mark.parametrize("scenario", ["no_exchange_run_of_river", "zonal_test"])
def test_system_thermal_edit_projects_and_releases_source(scenario):
    data = enable(load_data(str(ROOT / "Data" / scenario)))
    original = data[PROFILE].copy()
    system = load_system_from_data(data)
    owner = next(system.get_components(SDOMThermalGenerator))
    plant = owner.name.split(":", 1)[1]
    series = system.get_time_series(owner, name="min_dispatch_fraction")
    np.testing.assert_array_equal(series.data, np.full(4, 0.25))
    system.remove_time_series(owner, name="min_dispatch_fraction")
    system.add_time_series(
        SingleTimeSeries.from_array(
            np.array([0, 0.3, 0.4, 1]),
            name="min_dispatch_fraction",
            initial_timestamp=datetime(2000, 1, 1),
            resolution=timedelta(hours=1),
        ),
        owner,
    )
    restored = system_to_data_dict(system)
    assert restored[PROFILE][plant].tolist() == [0, 0.3, 0.4, 1]
    pd.testing.assert_frame_equal(data[PROFILE], original)
    builder = initialize_model_from_system(system, n_hours=2)
    model = builder.create_instance()
    host = model.area[owner.bus.area.name] if hasattr(model, "area") else model
    assert value(host.thermal.min_dispatch_fraction[2, plant]) == 0.3
    with pytest.raises(ValueError, match="source data"):
        system_to_data_dict(system)


@pytest.mark.parametrize("edit", ["missing", "duplicate", "resolution", "start", "short", "range", "nan"])
def test_system_thermal_malformed_edits_fail(edit):
    system = load_system_from_data(enable(load_data(str(ROOT / "Data" / "no_exchange_run_of_river"))))
    owner = next(system.get_components(SDOMThermalGenerator))
    if edit != "duplicate":
        system.remove_time_series(owner, name="min_dispatch_fraction")
    if edit != "missing":
        values = np.full(2 if edit == "short" else 4, 0.3)
        if edit in ("range", "nan"):
            values[0] = 1.1 if edit == "range" else np.nan
        series = SingleTimeSeries.from_array(
            values,
            name="min_dispatch_fraction",
            initial_timestamp=datetime(2001 if edit == "start" else 2000, 1, 1),
            resolution=timedelta(hours=2 if edit == "resolution" else 1),
        )
        system.add_time_series(series, owner, edited=True)
    with pytest.raises(ValueError, match=r"min_dispatch_fraction|MinDispatchFraction"):
        system_to_data_dict(system)


def test_one_hour_system_conversion_explicitly_rejected():
    data = enable(load_data(str(ROOT / "Data" / "no_exchange_run_of_river")), hours=1)
    with pytest.raises(ValueError, match=r"at least two.*hour"):
        load_system_from_data(data)


def test_system_and_direct_solve_parity():
    data = controlled_data(
        enable(load_data(str(ROOT / "Data" / "no_exchange_run_of_river"))), minimum=200, maximum=200
    )
    data["per_area_balancing_units"] = {"default": data["thermal_data"]}
    system = load_system_from_data(data)
    direct = initialize_model(data, n_hours=4)
    adapted = initialize_model_from_system(system, n_hours=4).create_instance()
    for model in (direct, adapted):
        assert str(SolverFactory("highs").solve(model).solver.termination_condition) == "optimal"
        assert [value(model.thermal.generation[h, "unit"]) for h in model.h] == pytest.approx(
            [80, 60, 100, 120]
        )
    assert value(direct.Obj) == pytest.approx(value(adapted.Obj))


def test_system_thermal_ownership_edits_cannot_reroute_profiles():
    from sdom.infrasys_integration.models import SDOMBus

    system = load_system_from_data(enable(load_data(str(ROOT / "Data" / "zonal_test"))))
    owner = next(system.get_components(SDOMThermalGenerator))
    owner.bus = next(bus for bus in system.get_components(SDOMBus) if bus.area.name != owner.bus.area.name)
    with pytest.raises(ValueError, match=r"min_dispatch_fraction.*ownership"):
        system_to_data_dict(system)
