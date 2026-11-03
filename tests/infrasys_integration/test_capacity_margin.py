"""Verify capacity-margin propagation through supported System adapters."""

from pathlib import Path

import pytest
from pyomo.environ import value
from test_capacity_margin import enable_reserves

pytest.importorskip("infrasys")
pytest.importorskip("r2x_core")

from sdom import load_data
from sdom.infrasys_integration.make_system import load_system_from_data, system_to_data_dict
from sdom.infrasys_integration.models import SDOMFormulationConfig, SDOMScalarParameter
from sdom.infrasys_integration.parametric import apply_scalar_sweep_to_system
from sdom.infrasys_integration.pyomo_builder import initialize_model_from_system

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("folder", ["no_exchange_run_of_river", "zonal_test"])
def test_capacity_margin_system_roundtrip_and_scalar_mutation(folder):
    data = enable_reserves(load_data(str(ROOT / "Data" / folder)))
    system = load_system_from_data(data)
    assert system.get_component(SDOMScalarParameter, "scalar:capacity_marging_fraction").value == 0.04
    assert (
        system.get_component(SDOMFormulationConfig, "formulation:Reserves").formulation
        == "CapacityMarginFormulation"
    )
    mutated = apply_scalar_sweep_to_system(system, parameter_name="capacity_marging_fraction", value=0.1)
    assert system_to_data_dict(system)["scalars"].loc["capacity_marging_fraction", "Value"] == 0.04
    model = initialize_model_from_system(mutated, n_hours=24).create_instance()
    hosts = [model.area[a] for a in model.A] if hasattr(model, "A") else [model]
    for host in hosts:
        assert value(host.reserves.capacity_marging_fraction) == 0.1
        assert len(host.reserves.Capability) == 24
        assert len(host.reserves.storage_capacity_contribution) == 24 * len(host.storage.j)
        assert not hasattr(host.reserves, "storage_upward_capability")


@pytest.mark.parametrize("margin", [float("nan"), -0.01])
def test_capacity_margin_system_builder_retains_invalid_input_for_validation(margin):
    data = enable_reserves(load_data(str(ROOT / "Data" / "no_exchange_run_of_river")), margin=margin)
    system = load_system_from_data(data)
    with pytest.raises(ValueError, match="capacity_marging_fraction"):
        initialize_model_from_system(system, n_hours=24).create_instance()
