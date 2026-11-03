"""Reject the unsupported thermal formulation throughout resiliency APIs."""

import pandas as pd
import pytest

from sdom import load_data
from sdom.resiliency.data_loader import load_designed_system
from sdom.resiliency.dispatch_model import build_baseline_dispatch
from sdom.resiliency.evaluate import evaluate_resiliency
from sdom.resiliency.outage_dispatch import build_outage_dispatch
from sdom.resiliency.outage_scenarios import OutageSpec
from sdom.resiliency.runner import run_resiliency_evaluation
from sdom.resiliency.system_state import BaselineDispatchResults, DesignedSystem
from tests.test_thermal_min_dispatch import NEW, PROFILE, ROOT, enable


@pytest.mark.parametrize("fraction", [0, 0.1, None])
@pytest.mark.parametrize("source", ["cem_data", "formulation_map"])
def test_direct_resiliency_entries_reject_min_dispatch_selection(source, fraction):
    data = enable(load_data(str(ROOT / "Data" / "no_exchange_run_of_river")), fraction=fraction)
    if fraction is None:
        del data[PROFILE]
    ds = DesignedSystem(
        cem_data=data if source == "cem_data" else None,
        formulation_map={"tHeRmAl": NEW} if source == "formulation_map" else {},
    )
    baseline = BaselineDispatchResults(metadata={"designed_system": ds})
    spec = OutageSpec(duration_hours=1, recovery_hours=0, outaged_assets={})
    with pytest.raises(NotImplementedError, match=rf"{NEW}.*resiliency"):
        build_baseline_dispatch(ds, n_hours=2)
    with pytest.raises(NotImplementedError, match=rf"{NEW}.*resiliency"):
        build_outage_dispatch(baseline, outage_spec=spec, start_hour=1, n_hours=2)
    with pytest.raises(NotImplementedError, match=rf"{NEW}.*resiliency"):
        run_resiliency_evaluation(baseline, outage_spec=spec, hours=[1], n_hours=2)


@pytest.mark.parametrize("attach_cem_data", [True, False])
def test_snapshot_and_end_to_end_reject_selection_before_reading_profiles(tmp_path, attach_cem_data):
    pd.DataFrame({"Component": ["Thermal"], "Formulation": [NEW]}).to_csv(
        tmp_path / "formulations.csv", index=False,
    )
    # No snapshot or fraction CSV exists: selection alone must reject the case.
    with pytest.raises(NotImplementedError, match=rf"{NEW}.*resiliency"):
        load_designed_system("unused", inputs_dir=tmp_path, year=2030, attach_cem_data=attach_cem_data)
    with pytest.raises(NotImplementedError, match=rf"{NEW}.*resiliency"):
        evaluate_resiliency(
            "unused", inputs_dir=tmp_path, year=2030,
            outage_spec=OutageSpec(duration_hours=1, recovery_hours=0, outaged_assets={}),
        )


def test_resiliency_formulation_override_cannot_bypass_guard(tmp_path):
    with pytest.raises(NotImplementedError, match=rf"{NEW}.*resiliency"):
        load_designed_system(
            "unused", inputs_dir=tmp_path, year=2030, attach_cem_data=False,
            formulation_overrides={"Thermal": NEW},
        )
