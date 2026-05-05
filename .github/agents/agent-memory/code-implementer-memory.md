# Code Implementer Memory

This file stores learnings, patterns, and decisions from code implementation tasks.

---

## Resiliency Module — Phase 1 (2026-05-05)

### Scope
Additive-only data loader + system-state dataclasses under `src/sdom/resiliency/`. No edits to `src/sdom/models/`.

### Files created
- `src/sdom/resiliency/__init__.py` — re-exports `DesignedSystem`, `BaselineState`, `load_designed_system`.
- `src/sdom/resiliency/system_state.py` — frozen=False dataclasses with `pd.Series`/`pd.DataFrame` fields defaulting to `None`.
- `src/sdom/resiliency/data_loader.py` — `load_designed_system(snapshot_dir, *, inputs_dir, year=2030, scenario_id=1, formulation_overrides=None)` plus private helpers.
- `tests/test_resiliency_data_loader.py` — 27 cases (TDD).

### Data-format gotchas
- Snapshot CSVs use column `Scenario` (NOT `Run`) for the 3MW_PGnE dataset; loader sniffs both.
- Snapshot files containing `Phase1` in the name must be excluded from glob discovery.
- `OutputSelectedVRE_*.csv` ships with header `"Selection "` (trailing space) — strip column whitespace.
- Hourly input CSVs use `*Hour` as the index column — strip the leading `*`.
- `fixed_dem_charges.csv` / `var_dem_charges.csv` have NO year suffix.
- `Data_Balancing_units_{year}.csv` lacks a Technology column → aggregate via `mean()` (HeatRate/FuelCost/VOM); documented in docstring.
- `StorageData_{year}.csv` is parameter-indexed (rows = P_Capex/Eff/FOM/VOM/...); read with `index_col=0`.

### Patterns established
- Hybrid scenario resolution helper `_filter_scenario(df, scenario_id, file_label) -> (filtered_df, resolved_id)`: warns on single-scenario mismatch, raises `ValueError` listing IDs on multi-scenario mismatch.
- Zero-capacity techs emit `warnings.warn("Technology '{tech}' has capacity={value}; excluding from designed system.")` and are dropped.
- `_compute_month_of_hour(year)` uses `pd.date_range(start=f"{year}-01-01", periods=8760, freq="h").month` indexed 1..8760.

### Test/CI gotchas
- `pyproject.toml` adds `--cov=sdom` by default → use `--no-cov` for fast iteration in TDD loops.
- `tests/test_no_resiliency_optimization_cases_xpress_local.py` requires Xpress; deselect for CI/local-without-xpress runs.

### Open issues to address before Phase 2
- `DesignedSystem` only stores a single `Eff` per storage tech (used for both `eta_ch` and `eta_dis`).
- `soc_min_frac` defaults to 0.0 — `StorageData_2030.csv` has no Min_SOC row; need design decision.
- Thermal params are aggregate, not per-tech (no Technology column in balancing-units file).
- `Scalars.csv`, `Set_b(j)_CoupledStorageTech.csv`, `Set_sp_StorTechProperties.csv` are not yet ingested.

---

## Resiliency Module — Phase 2 (2026-05-05)

### Scope
New `ImportsWithDemandChargesFormulation` Pyomo block builder. Pure LP, opt-in only, NO modifications to `src/sdom/models/`.

### Files created
- `src/sdom/resiliency/formulations_imports_demand_charges.py` — public `add_imports_with_demand_charges(model, *, ...)` + private `_validate_phi_fix_monthly_constancy`.
- `tests/test_resiliency_imports_demand_charges_formulation.py` — 4 TDD cases (structure, zero-imports solve, monthly-peak solve, phi_fix warning).

### Files updated
- `src/sdom/resiliency/__init__.py` — re-exports `add_imports_with_demand_charges`.

### Patterns established
- **Standalone block builder** under resiliency/: do NOT inherit from `models/formulations_imports_exports.py`. Mirror its layered shape (params → vars → expressions → constraints) but keep self-contained.
- Attach a child `pyo.Block()` via `model.add_component(block_name, block)` rather than mutating the parent model directly. Allows multiple instances and clean namespacing.
- Capture hour→month as a plain Python `dict` for closure in `Constraint` rules — Pyomo Param indexing inside rules works but a `dict` lookup is simpler and avoids type-coercion gotchas (`int(month_of_hour[t])`).
- Validation that should NOT block model construction → use `warnings.warn(..., UserWarning, stacklevel=3)` so the warning points at the caller of the public builder, not the helper.
- `pd.Series.to_dict()` is the cleanest way to feed `Param(set, initialize=...)` when index already matches the Pyomo set.

### LP correctness check
Demand-charge linking is `D^k_m >= phi^k_t * Pimp[t]` with `D^k_m >= 0` (NonNegativeReals var). At optimum each `D^k_m == max_t(phi^k_t * Pimp[t])` since the objective minimizes `sum(D)`. Verified analytically by `test_solve_forces_monthly_peak` (8660 USD).

### HiGHS in tests
Use `pyo.SolverFactory("appsi_highs")` first, fallback `"highs"`. Wrap availability check with `solver.available(exception_flag=False)` and `pytest.skip` if absent — avoid hard CI failures on machines without HiGHS.

### Open issues for Phase 3 (baseline_dispatch composition)
- The new block currently lives only as a builder; baseline_dispatch must (a) optionally call this builder when `formulation_overrides["Imports"] == "ImportsWithDemandChargesFormulation"`, else fall back to the legacy imports formulation (which uses big-M binaries — incompatible with pure-LP resiliency objective).
- Power balance integration: baseline must reference `model.imports.Pimp[t]` (not `model.imports.variable[t]` as in legacy). Need an adapter or convention.
- Exports counterpart NOT built in Phase 2 by design — Phase 3 will reuse `formulations_imports_exports.py` exports OR add a parallel resiliency exports helper without demand charges.
- `month_of_hour` is currently an input arg; `DesignedSystem` already exposes one — wire it through in `dispatch_model.py`.
- `phi_fix_t` / `phi_var_t` series come from `fixed_dem_charges.csv` / `var_dem_charges.csv` already loaded in `DesignedSystem` (Phase 1).
- `BaselineState` is a placeholder; full schema needed in Phase 2 (SOC trajectory, dispatch, peak imports, etc.).

---

## 💻 Code Patterns

### Established Patterns
*Code patterns used in SDOM*

- **Solver configuration factory**: Use `get_default_solver_config_dict()` to create solver-specific configs with unified API but solver-specific option names
- **Dict-based configuration**: Solver configs use nested dicts: `solver_name`, `executable_path`, `options`, `solve_keywords`

### Anti-Patterns
*Patterns to avoid*

- Don't use generic option names across solvers (e.g., `mip_rel_gap`) - each solver has its own control names

---

## 🔧 API Decisions

### Public API
*Decisions about public API design*

- **2024-04-21**: `get_default_solver_config_dict()` changed to use keyword-only args for `mip_gap` and `time_limit` (backward compatible - positional args unchanged)

### Backward Compatibility
*Changes made with backward compatibility considerations*

- **Solver config**: Old usage `get_default_solver_config_dict("highs")` still works; new params are keyword-only

---

## ⚡ Performance Learnings

### Optimizations Applied
*Performance improvements implemented*

### Bottlenecks Identified
*Performance issues found*

---

## 🧪 Testing Patterns

### Effective Test Patterns
*Test patterns that work well for SDOM*

- **Optional dependency tests**: Use `pytest.importorskip("xpress")` at module level to skip entire test file if package not installed
- **Separate config tests from integration tests**: Config tests don't need solver license, integration tests do
- **Use `@pytest.mark.integration`** for tests requiring solver binaries/licenses

### Test Data Management
*Learnings about test data handling*

- Test data path: `REL_PATH_DATA_RUN_OF_RIVER_TEST` from `constants_test.py`

---

## 📦 Dependency Notes

### Pyomo
*Pyomo-specific learnings*

- **Solver interfaces**:
  - `cbc`: Shell solver, needs `executable=path`
  - `appsi_highs`: Python interface via highspy package
  - `xpress_direct`: Direct Python interface via xpress package
- **Solver option names differ**:
  - CBC: `ratioGap` for MIP gap
  - HiGHS: `mip_rel_gap` for MIP gap
  - Xpress: `miprelstop` for MIP gap, `maxtime` for time limit, `outputlog` for verbosity
- Xpress requires `xpress.init()` for license validation (handled automatically by Pyomo)

### pandas
*pandas patterns used*

---

## ⚠️ Gotchas & Edge Cases

*Implementation pitfalls discovered*

- **Xpress time limit**: Must be `int`, not `float` - use `int(time_limit)` when setting `maxtime`
- **Solver availability check**: Always call `solver.available()` after `SolverFactory()` - it validates license for commercial solvers
- **Option key errors**: Pyomo silently ignores invalid option names - always verify against solver docs

---

## 📝 Notes

*General learnings and observations*

---

## Resiliency Module — Phase 4 (2026-05-05)

### Scope
Deliverable A (`OutageSpec` dataclass) + Deliverable B (`build_outage_dispatch` LP builder). Pure additive; no Phase-3 refactor needed.

### Files created
- `src/sdom/resiliency/outage_scenarios.py` — `OutageSpec` + `VALID_COMPONENTS` + `MUST_RUN_COMPONENTS`.
- `src/sdom/resiliency/outage_dispatch.py` — `build_outage_dispatch(baseline_results, *, start_hour, outage_spec, ...)`.
- `tests/test_resiliency_outage_spec.py` (15 cases), `tests/test_resiliency_outage_dispatch.py` (10 cases).
- `__init__.py` re-exports updated.

### Patterns established
- TDD: write failing tests, then a stub returning `NotImplementedError` so Phase A tests can import the module before Phase B implementation lands.
- `OutageSpec.__post_init__` does *cheap* validation (component names, derating ranges, string selectors, positive durations). `validate(designed_system)` does the *heavy* per-asset universe check + dict-completeness check.
- Outage dispatch builder duplicates baseline sub-block logic with two changes: bound rules accept a `delta_map` capturing time-varying derating; storage block omits the `soc_initial` constraint and uses `Var.fix()` to seed initial SOC (single-row tighter LP).
- Must-run derating implemented as effective parameters (`hydro_eff_param[t] = hydro[t] * delta_hydro[t]`), exposed for tests to read directly via `pyo.value(model.hydro_eff_param[t])`.
- Imports asset_id is the canonical literal `"grid"`; tests rely on it.
- All metadata stashed under `model._sdom_outage_meta` for downstream consumers (Phase 5 runner) — includes recovery_target_MWh, deltas, designed_system handle.

### Gotchas
- `Var.fix(value)` requires `value` to lie within the variable bounds; the builder clips `init_value` to `[soc_min, cap_e]` before fixing to avoid infeasibility from numerical noise in the baseline trajectory.
- Empty `outaged_assets={}` is valid (no outage). Tests cover this for slack=0 sanity.
- `recovery_end_hour` is per-tech (the OutageSpec supports per-tech `recovery_hours`). Use `min(...recovery_per_tech.values())` for the model horizon endpoint.

### Open issues for Phase 5
- `DesignedSystem` and `BaselineDispatchResults` are picklable (plain pandas + nested dicts) but `OutageSpec` only contains scalars/dicts — verify pickle round-trip in the runner test.
- Per-worker initialisation: the runner should pickle `baseline_results` (with `metadata['designed_system']`) once and broadcast.
- Deterministic ordering: results indexed by `start_hour`, regardless of completion order.
- Reuse: consider extracting a `_resolve_dispatch_horizon(outage_spec, start_hour, n_hours)` helper if Phase 5 needs to compute clipped horizons without building the model.
