"""Shared constants for resiliency-related tests (MEA case).

The MEA inputs and post-CEM snapshot are tracked under
``Data/resiliency_eval/`` so the resiliency test suite runs in CI without
extra fixture downloads. A local ``res_runs_paper/`` checkout (gitignored)
is honored as a fallback for backwards compatibility with pre-PR layouts.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Tracked MEA fixtures (present in every repo checkout).
_TRACKED_INPUTS_DIR_MEA = (
    REPO_ROOT
    / "Data"
    / "resiliency_eval"
    / "inputs_previous_stage"
    / "Paper_MEA"
    / "Paper"
)
_TRACKED_SNAPSHOT_DIR_MEA = (
    REPO_ROOT
    / "Data"
    / "resiliency_eval"
    / "NotLand_constr_48hrs_outage_48hrs_recovery"
)

# Optional local override (gitignored; used by paper-reproduction workflows).
_LEGACY_INPUTS_DIR_MEA = (
    REPO_ROOT / "res_runs_paper" / "inputs" / "inputs_csv" / "Paper_MEA 1"
)
_LEGACY_SNAPSHOT_DIR_MEA = (
    REPO_ROOT / "res_runs_paper" / "inputs" / "outputs_CEM" / "For_simulations_MEA"
)

INPUTS_DIR_MEA = (
    _LEGACY_INPUTS_DIR_MEA
    if _LEGACY_INPUTS_DIR_MEA.exists()
    else _TRACKED_INPUTS_DIR_MEA
)
SNAPSHOT_DIR_MEA = (
    _LEGACY_SNAPSHOT_DIR_MEA
    if _LEGACY_SNAPSHOT_DIR_MEA.exists()
    else _TRACKED_SNAPSHOT_DIR_MEA
)

YEAR = 2030
SCENARIO_ID = 1
N_HOURS_SMOKE = 24
