---
name: sdom-pytest-testing
description: "Test and validate the SDOM optimization model with pytest. Use when adding, fixing, reviewing, or running SDOM unit, integration, regression, solver, data, resilience, hydro-budget, import/export, or parametric tests."
argument-hint: "Describe the SDOM behavior, test module, data case, solver, and expected outcomes"
user-invocable: true
---

# SDOM Pytest Testing

## Outcome

Deliver focused, function-based pytest coverage that verifies SDOM behavior through public APIs, realistic input data, model structure, and physically meaningful optimization results.

## When to Use

- Adding or repairing tests in `tests/`.
- Implementing or changing SDOM model, data-loading, solver, results, resiliency, or parametric behavior.
- Investigating a solver regression or unexpected optimization result.
- Reviewing whether an SDOM change has sufficient test coverage.

## Repository Conventions

- Use `pytest` through `uv run pytest`; test discovery, `src` and `tests` import paths, coverage, and markers are configured in `pyproject.toml`.
- Use standalone `test_*` functions. Do not introduce test classes or `unittest.TestCase`.
- Follow the nearby test module's imports, naming, data-path construction, and assertion style.
- Prefer the existing helpers in `tests/utils_tests.py`, including `get_n_eq_ineq_constraints`, `get_optimization_problem_info`, `get_optimization_problem_solution_info`, `check_supply_balance_constraint`, `check_budget_constraint`, and `check_hydro_budget_matches_csv`.
- Start with the closest behavioral precedent. For hydro budgets and imports/exports, use `tests/test_no_resiliency_hydro_budget_optimization_cases.py` and `tests/test_no_resiliency_imp_exp_hydro_budget_optimization_cases.py` as the reference pattern.
- Create deterministic tests: use fixed real input data, explicit solver configuration, stable horizons, and repeatable assertions; isolate or control any randomness, clock, environment, or external-process dependency.

## Pytest API Guidelines

- Write small tests with one behavioral purpose and descriptive `test_<behavior>_<condition>_<outcome>` names.
- Use plain `assert` statements with failure messages only when the failed invariant would otherwise be unclear.
- Compare floating-point results with `pytest.approx(expected, abs=tolerance)` or a documented absolute tolerance. Select a tolerance that reflects solver and data precision.
- Use `pytest.mark.parametrize` for the same behavior across independent cases; keep each parameter set readable and label it with `id=` when useful.
- Use fixtures for genuinely shared setup or cleanup. Keep fixture scope as narrow as practical, and prefer data objects over mutable global state.
- Use `pytest.raises(ExpectedException, match="...")` for expected failures, including invalid data and unsupported configurations.
- Use `pytest.mark.skipif` with an actionable reason for optional solver binaries or licensed dependencies. Reuse `CBC_EXECUTABLE` and `CBC_NOT_AVAILABLE_REASON` where applicable.
- Run the narrow module or test first, then the relevant suite. Examples:

```powershell
uv run pytest tests/test_no_resiliency_imp_exp_hydro_budget_optimization_cases.py -v
uv run pytest tests/test_no_resiliency_imp_exp_hydro_budget_optimization_cases.py -k daily_budget -v
uv run pytest tests -m "not integration" -v
```

## Procedure

### 1. Define the Behavioral Contract

1. Identify the owning public API and the expected user-visible or mathematical behavior.
2. State the normal case, a boundary or extreme case, and any expected failure before editing production code.
3. Locate the nearest existing test and helper. Extend it when it covers the same feature; create a new `test_*.py` module only for a distinct behavior area.

### 2. Choose Representative Data

1. Prefer an existing, documented scenario under `Data/` over synthetic CSV construction for optimization integration tests.
2. Select the smallest real case that exercises the behavior and a horizon compatible with its budget constraints.
3. Build repository-relative paths from `os.path.dirname(__file__)` and constants in `tests/constants_test.py`, then convert the path to an absolute path before `load_data`.
4. Create narrowly scoped synthetic inputs only for parser validation, error paths, or a model condition that no real dataset can isolate.

### 3. Add Structural Coverage

1. Load data and construct the model through public APIs such as `load_data` and `initialize_model`.
2. Assert equality and inequality constraint counts when the formulation structure is intentionally fixed.
3. Assert problem variables, constraints, binary variables, objectives, and nonzeros when the selected solver result reliably exposes those counts.
4. Update count baselines only after explaining the intended formulation change; do not change them merely to make a test pass.

### 4. Add Solver and Solution Coverage

1. Run the supported default solver configuration, normally HiGHS, and assert a non-null result and `"optimal"` termination condition.
2. Assert the objective value with a solver-appropriate tolerance and the significant capacity decisions, such as wind, PV, and each relevant storage technology.
3. Assert important dispatch behavior from result data when it is part of the feature: imports/exports, generation, storage charge/discharge, critical load, or resilience metrics.
4. Check physical and model invariants, not only aggregate totals:
   - Supply balance is satisfied for every modeled hour.
   - Hydro and other budget blocks are satisfied for every budget period.
   - Budget generation matches the corresponding source CSV period totals when applicable.
   - Expected imports or exports are present or absent for the selected scenario.

### 5. Test Corners and Comparative Behavior

1. Cover empty, missing, malformed, or incompatible inputs with targeted error-path tests.
2. Cover boundary horizons and budget period boundaries, including a complete daily or monthly period.
3. Test directional relationships with paired scenarios rather than brittle single values. For example, significantly decrease the cost of technology $x$ while holding other inputs fixed, then assert an increase in its installed capacity when the baseline case has room to respond.
4. For each comparative test, verify both solves are optimal and the changed input is the only intended material difference.

### 6. Validate and Review

1. Run the newly added test first. A failure should distinguish an implementation defect from an incorrect test expectation.
2. Run the nearest related module after the focused test passes.
3. Confirm the test produces the same outcome across repeated local runs with the same dependency versions and solver configuration.
4. Confirm tests do not rely on execution order, machine-specific absolute paths, `print`, network access, or undocumented solver availability.
5. Keep tests deterministic and bounded: use the smallest meaningful real dataset, avoid redundant solver runs, and mark genuinely slow integration cases.

## Anti-patterns to Avoid

- Test classes, `unittest` assertions, or custom assertion frameworks.
- One broad end-to-end test that hides independent failures in data loading, model construction, solving, and result validation.
- Asserting only `results is not None` or only an objective value while ignoring termination, formulation structure, feasibility, and significant decisions.
- Exact equality for floating-point solver outputs, or excessively broad tolerances that cannot detect regressions.
- Hard-coded local paths, unguarded optional solver tests, and silently skipping core HiGHS coverage.
- Duplicating helper logic for supply balance or budget checks instead of extending `tests/utils_tests.py` when reuse is warranted.
- Modifying expected objectives or model counts without identifying the intended behavioral change.
- Using synthetic optimization data by default when a small relevant case already exists in `Data/`.
- Relying on `print` for validation rather than assertions with useful diagnostic output.
- Depending on uncontrolled randomness, wall-clock time, mutable shared data, or solver defaults that can produce non-repeatable expectations.

## Completion Criteria

- The test is a standalone function and follows the nearest SDOM test pattern.
- Coverage includes the normal behavior, an appropriate edge or error case, and a meaningful optimization-specific invariant where applicable.
- Optimization tests verify optimal termination, objective, structure, significant capacities or dispatch values, and relevant feasibility or budget checks.
- Comparative tests assert the intended directional response under a controlled input change.
- Tests are deterministic when run repeatedly with the same data, dependency versions, and solver configuration.
- Focused and related pytest commands pass with the available solver dependencies.