"""Verify results package boundaries and historical import compatibility."""

import ast
import pickle
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from copy import copy
from multiprocessing import get_context
from pathlib import Path

import pandas as pd
import pytest

import sdom
import sdom.optimization_main as optimization_main
import sdom.results as results
from sdom.results import OptimizationResults

RESULT_MODULES = (
    "__init__",
    "containers",
    "results_collection_main",
    "collect_copperplate_resuts",
    "collect_zonal_resuts",
    "collect_individual_host_results",
    "results_aggregation",
    "summary",
    "hydro",
    "pricing",
    "_values",
)


def test_optimization_main_no_longer_exposes_deprecated_collector():
    assert not hasattr(optimization_main, "collect_results")
    assert optimization_main.collect_results_from_model is results.collect_results_from_model
    assert optimization_main.run_solver is sdom.run_solver


def test_results_is_package_with_approved_modules():
    package_dir = Path(results.__file__).parent
    assert Path(results.__file__).name == "__init__.py"
    assert {path.stem for path in package_dir.glob("*.py")} == set(RESULT_MODULES)
    assert not package_dir.with_suffix(".py").exists()


def test_results_documentation_lists_approved_module_responsibilities():
    repo_root = Path(__file__).resolve().parents[1]
    guide = (repo_root / "docs" / "source" / "sdom_Developers_guide.md").read_text(encoding="utf-8")
    api_layout = (repo_root / "docs" / "source" / "api" / "index.md").read_text(encoding="utf-8")
    for module_name in RESULT_MODULES:
        assert f"`{module_name}.py`" in guide
        assert f"{module_name}.py" in api_layout
    api_results = (repo_root / "docs" / "source" / "api" / "results.md").read_text(encoding="utf-8")
    assert "sdom.results.collect_results_from_model" in api_results
    assert "sdom.results.collect_marginal_prices_from_model" in api_results
    assert "sdom.results.OptimizationResults" in api_results


@pytest.mark.parametrize("module_name", RESULT_MODULES)
def test_results_imports_are_at_beginning_of_module(module_name):
    module_path = Path(results.__file__).parent / f"{module_name}.py"
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert all(node in tree.body for node in imports), "Function-local or conditional import found"
    body = tree.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    first_statement = next(
        (index for index, node in enumerate(body) if not isinstance(node, (ast.Import, ast.ImportFrom))),
        len(body),
    )
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in body[first_statement:])


def test_results_public_imports_share_definitions_in_fresh_interpreter():
    script = """
import sdom
from sdom.results import (
    OptimizationResults,
    _collect_thermal_generation_dataframe,
    collect_marginal_prices_from_model,
    collect_results_from_model,
)
from sdom.results.containers import OptimizationResults as Container
from sdom.results.results_collection_main import collect_results_from_model as collect
from sdom.results.pricing import collect_marginal_prices_from_model as collect_prices
from sdom.results.collect_individual_host_results import (
    _collect_thermal_generation_dataframe as collect_thermal,
)

assert sdom.OptimizationResults is OptimizationResults is Container
assert collect_results_from_model is collect
assert collect_marginal_prices_from_model is collect_prices
assert _collect_thermal_generation_dataframe is collect_thermal
"""
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False, timeout=60
    )
    assert completed.returncode == 0, completed.stderr


def test_results_loads_historical_pickle_class_path():
    legacy_pickle = b"csdom.results\nOptimizationResults\n(tR(dVtotal_cost\nF42.0\nsb."
    restored = pickle.loads(legacy_pickle)
    assert type(restored) is OptimizationResults
    assert restored.total_cost == 42.0
    assert restored.generation_df.empty


def test_results_pickle_retains_historical_class_path_and_values():
    original = OptimizationResults(
        total_cost=42.0,
        capacity={"Solar PV": 12.0},
        generation_df=pd.DataFrame({"Hour": [1], "Load (MW)": [3.0]}),
    )
    payload = pickle.dumps(original, protocol=0)
    restored = pickle.loads(payload)
    assert OptimizationResults is sdom.OptimizationResults
    assert OptimizationResults.__module__ == "sdom.results"
    assert b"csdom.results\nOptimizationResults\n" in payload
    assert type(restored) is OptimizationResults
    assert restored.capacity == original.capacity
    pd.testing.assert_frame_equal(restored.generation_df, original.generation_df)


def test_results_roundtrips_through_spawned_worker():
    original = OptimizationResults(total_cost=42.0, capacity={"Solar PV": 12.0})
    with ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn")) as executor:
        restored = executor.submit(copy, original).result(timeout=60)
    assert type(restored) is OptimizationResults
    assert restored.total_cost == original.total_cost
    assert restored.capacity == original.capacity
