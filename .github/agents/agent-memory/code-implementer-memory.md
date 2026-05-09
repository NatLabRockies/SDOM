# Code Implementer Memory

This file stores learnings, patterns, and decisions from code implementation tasks.

---

## Zonal Capacity Expansion — Commit #12: dispatcher resiliency guard + finalize RoR fixture (2026-05-08)

### Scope
Two-part commit. (1) Lift the `with_resilience_constraints=True` + `Network=AreaTransportationModelNetwork` guard from inside `_initialize_model_zonal` up to the public `initialize_model` dispatcher per PRD §5.8 — so callers fail fast before any zonal Block construction runs. (2) Finalize `Data/zonal_test/` as the canonical RoR-only fixture per the locked 2026-05-08 decision (both areas = RunOfRiverHydro).

### Files touched
- `src/sdom/optimization_main.py` — added the resiliency-AT guard right between the legacy fast-path branch and the AT zonal-dispatch branch in `initialize_model`. The same guard remains as a defensive copy at the top of `_initialize_model_zonal` so direct callers of the private helper still get the traceable error.
- `tests/test_zonal_resiliency_guard.py` (new, 3 tests) — (a) `monkeypatch.setattr` spy on `_initialize_model_zonal` proves the dispatcher raises BEFORE delegating; (b) sanity: legacy CopperPlate + resiliency still works (no false positive); (c) private helper retains its defensive guard.
- `scripts/build_zonal_test_fixture.py` — updated docstring with the 2026-05-08 decision rationale (option b: drop A2's `lahy_max_hourly` / `lahy_min_hourly` to satisfy global RoR while keeping inter-area heterogeneity). Also fixed an outdated `Network` row description string in the script that had drifted from the checked-in CSV.
- `tests/test_zonal_fixture_invariants.py` (new, 7 tests) — locks `Hydro=RunOfRiverFormulation`, no `lahy_max/min*.csv` files shipped, both areas carry `LargeHydro@A?@` columns in `lahy_hourly.csv`, `areas == {A1, A2}`, `Network=AreaTransportationModelNetwork`, `Imports/Exports=NotModel`.

### Key decisions / gotchas
- **Option (b) chosen** for A2's source: `no_exchange_monthly_hydro_budget_multiple_balancing_p50` (sole source providing a `lahy_hourly` file besides the RoR folder), with `lahy_max_hourly` / `lahy_min_hourly` deliberately omitted from the merged fixture so A2's hydro behaves as RoR. Caveat noted: A2's `lahy_hourly_2025.csv` was authored as a *budget profile*, not a RoR generation profile — acceptable for a test fixture whose purpose is to exercise model wiring, not power-system realism.
- **Why not option (a)** (duplicate `no_exchange_run_of_river` as A2 with renamed plant ids): would make A1 and A2 structurally identical, leaving the transportation line at zero flow at the LP optimum — less interesting as a stress test.
- **The fixture itself was already in the desired option-(b) state** from commit #4b; this commit only formalized the decision via locked invariants and updated documentation. `git diff Data/zonal_test/` after re-running the build script: empty (bit-identical).
- Hydro-budget under AT is **still not guarded** in `_initialize_model_zonal`. The fixture's RoR setting is now locked by `test_zonal_fixture_invariants.py`, so this latent risk is contained — but if a future zonal fixture lands with `Hydro=MonthlyHydroBudget` or `DailyHydroBudget`, add an explicit guard analogous to the resiliency one.
- The pre-existing `test_resiliency_under_zonal_raises_not_implemented` in `tests/test_zonal_model_build.py` continues to pass unchanged because it goes through the public `initialize_model` dispatcher — which now raises one stack-frame earlier.

### Suite status
372 → 375 (after Part 1) → **382 passed** (after Part 2). Legacy fast-path bit-identical. Two `pytest.mark.slow` warnings unrelated.

### Commits (local, NOT pushed)
- `74af529` — `feat(zonal): lift resiliency+AT NotImplementedError to dispatcher`
- `e738d7f` — `test(zonal): finalize Data/zonal_test/ as RoR-only fixture (option b)`

### Follow-ups
- Commit #13: `feat(parametric,plots): zonal smoke test and optional zonal plots` (last in the 13-commit plan).
- If a non-RoR zonal fixture ever lands, add an explicit hydro-budget-under-AT guard alongside the resiliency one.

---

## Zonal Capacity Expansion — Commit #11: emit `OutputInterregionalExchanges_{case}.csv` (2026-05-09)

### Scope
Wire CSV emission for the zonal interregional-exchanges DataFrame populated in commit #10. Pure additive write: extend `_export_from_results_object` in `io_manager.py`; no behavior change on the legacy path or when the DataFrame is empty.

### Files
- `src/sdom/io_manager.py` — appended a 7-line block to `_export_from_results_object` after the installed-plants emission. Uses `getattr(results, "interregional_exchanges_df", None)` (defensive against older pickled `OptimizationResults` objects without the field) and writes `OutputInterregionalExchanges_{case}.csv` only if the DataFrame is non-empty. Also added a 7-line block to the `export_results` docstring documenting the new output file (PRD §2.4 schema, row count `|L| * n_hours`, conditional on Network=AreaTransportationModelNetwork).
- `tests/test_zonal_io_export.py` (new) — 3 tests using module-scoped HiGHS fixtures (skipped if HiGHS missing). One zonal solve + export round-trip (schema + row count = `|L| * n_hours`), one legacy solve assertion that the file is NOT emitted (and `OutputGeneration_*.csv` IS), one pure-Python test that constructs `OptimizationResults()` (default empty `interregional_exchanges_df`) and asserts no file is written.

### Key decisions
- **Did NOT touch `_export_from_model_legacy`.** The legacy path is for callers that pass a raw model object instead of `OptimizationResults`; under the zonal/Block model that legacy export already emits broken output (flat lookups like `model.thermal.*`), and the orchestrator-locked scope is "legacy export path unchanged." All zonal callers must use `OptimizationResults`-based export.
- **Used `getattr(results, "interregional_exchanges_df", None)`** instead of direct attribute access so that older pickled `OptimizationResults` (pre-#10) loaded by users would not raise `AttributeError` during export. The `is not None and not df.empty` guard then matches the dataclass default (`pd.DataFrame()`).
- **Test for empty case uses the dataclass default**, not a zonal solve with empty lines. Faster (no HiGHS required for that test) and exercises exactly the empty-DataFrame guard. Combined with the legacy-solve test, both "DataFrame is empty" code paths are covered (default vs. legacy collector).
- **Module-scoped HiGHS fixtures duplicate the pattern in `test_zonal_results.py`** rather than importing from there (cross-test imports are fragile in pytest collection). Each test file remains self-contained.
- **PRD §2.4 column order is enforced**: test asserts `list(df.columns) == PRD_2_4_COLUMNS` (not just set equality). The collector in #10 builds the columns in this order so this is a tight contract.
- **`export_results` docstring update** adds the new output to the existing `Output Files` section. NumPy docstring style retained; no other doc files touched (per orchestrator scope).

### Patterns / gotchas
- `pd.read_csv` round-trips `flow_signed_MW`/`flow_FT_MW` as float64 even though the in-memory DataFrame already had floats — no schema drift to worry about.
- `tmp_path` (pytest builtin) is the right scratch dir; `export_results` calls `os.makedirs(output_dir, exist_ok=True)` so an empty `tmp_path` works directly.
- The `case` param is interpolated into filenames as-is — using a unique case per test (`"zonal_export_test"`, `"legacy_export_test"`, `"empty_case"`) avoids any cross-test contamination even though `tmp_path` is per-test.
- HiGHS fixture cost: ~2.5s per zonal solve. Module-scoped sharing with `test_zonal_results.py` is not possible across files (pytest fixtures are file-local unless conftest-promoted), so this commit incurs a duplicate ~2.5s solve. Acceptable; conftest promotion would be a wider refactor.

### Test counts
- New file: 3 tests, all green.
- Full suite: **369 → 372 passed**, 0 failed in 213s.

### Commit
- SHA: `a57f65b` on `sm/zonal_model`. Not pushed.

### Open items for #12
- Build a second copy of `Data/zonal_test/` with both areas using the RunOfRiver-compatible source (A1 = `no_exchange_run_of_river` already; A2 needs to come from a different RoR-compatible folder per user decision 2026-05-08). Current canonical fixture has A2 from the monthly hydro budget folder which leaves a latent risk under hydro=RoR.
- Add an explicit `NotImplementedError` guard for `resiliency=True + Network=AT` in the dispatcher (currently raised inside `_initialize_model_zonal`; surface earlier).

---

## Zonal Capacity Expansion — Commit #10: zonal results collector (2026-05-09)

### Scope
Make `collect_results_from_model` zonal-aware. Add new optional fields to `OptimizationResults` (per PRD §6.1) plus `interregional_exchanges_df` (PRD §2.4). Legacy collector body left **literally untouched** for bit-identical regression.

### Files
- `src/sdom/results.py` — added 13 new fields to `OptimizationResults`; refactored `collect_results_from_model` into a thin dispatcher (`hasattr(model, "A") and hasattr(model, "area")` → zonal). Legacy logic moved verbatim into `_collect_results_copperplate`. New helpers: `_collect_host_metrics(host, hours, *, case_name)` (parametric over `host` — mirrors legacy collection on any block exposing `pv`/`wind`/`thermal`/`storage`/`hydro`/`demand`/`nuclear`/`other_renewables`), `_merge_dict_sum` (recursive scalar dict aggregator), `_build_interregional_exchanges_df` (PRD §2.4 schema), `_collect_results_zonal`. Imported `numpy as np` and `pyomo.environ.value`.
- `tests/test_zonal_results.py` (new) — 7 tests: dataclass defaults, legacy isolation, areas/lines population, per-area DataFrame shapes (24-row each + 48-row top-level with `Area` column at pos 0), interregional schema (PRD §2.4), `total_cost == pyo.value(model.Obj.expr)`, pickle roundtrip for legacy + zonal.
- `docs/source/api/_autosummary/sdom.OptimizationResults.rst` — autogenerated update reflecting the new attributes (committed alongside the code change).

### Key decisions
- **Did NOT extract a single shared `_collect_host_metrics` for both legacy and zonal paths.** The orchestrator allowed it but bit-identical legacy behavior is locked by `tests/test_zonal_legacy_regression.py`; the safest path is to leave the legacy collector untouched (`_collect_results_copperplate` is the verbatim historical body). The new `_collect_host_metrics` is **only used by the zonal path**, where its `hasattr(host, "imports")` guards are necessary because zonal area blocks intentionally omit `add_imports_exports_cost_expressions`.
- **Top-level `summary_df` left empty under zonal** (with INFO log). Per-area summaries live in `area_summary_df` and are built by reusing `_build_summary_dataframe(area_block, per_area_results, storage_tech_list)` — the helper only touches host sub-blocks (`storage`, `demand`, `imports`/`exports` guarded by hasattr, `pv`, `wind`, `h`) which are all available on the area block. Per-area `total_cost` is computed as the sum of cost-breakdown components (capex+power_capex+energy_capex+fom+vom+fuel+imports−exports). System-level zonal summary deferred.
- **Top-level `generation_df`/`storage_df`/`thermal_generation_df`/`installed_plants_df` get an `Area` column** prepended at the position the orchestrator specified: pos 0 for `generation_df`, after `Hour` for storage/thermal, after `Plant ID` for installed_plants.
- **NaN-safe utilization in `_build_interregional_exchanges_df`**: used `np.where(cap > 0, flow / cap, np.nan)` with a guarded denominator (`np.where(cap>0, cap, 1.0)`) to avoid divide-by-zero warnings before masking.
- **`flow_FT_MW = max(f, 0)` / `flow_TF_MW = max(-f, 0)`** computed in Python at collection time (PRD §2.4). Verified `flow_FT - flow_TF == flow_signed` to within 1e-9 and `flow_FT * flow_TF <= 1e-9` (LP optimum).
- **Pickle roundtrip explicitly tested.** The new fields are all `dict[str, dict|pd.DataFrame]` / `list[dict]` / `pd.DataFrame` — all natively pickleable.

### Patterns / gotchas
- **`add_imports_exports_cost_expressions` is NOT called on area blocks under zonal** (see `_build_one_area` — intentional). So `area_block.imports.total_cost_expr` does not exist. The collector must guard with `hasattr(host.imports, "total_cost_expr")`. Same for `host.imports.variable` (variables only created if formulation != NotModel).
- **`get_default_solver_config_dict(solver_name="highs")`** routes to the `appsi_highs` solver name internally. For tests, override `solve_keywords` to silence output: `tee=False, report_timing=False, keepfiles=False`.
- **`run_solver` already does the right thing on zonal models** because the dispatcher in `collect_results_from_model` detects `hasattr(model, "A") and hasattr(model, "area")` and routes to `_collect_results_zonal`. No changes to `run_solver` were needed.
- **`pyo.value(model.line_from[l])`** must be called at collection time to get the string area id; the Param object itself is not directly comparable to a string in tests.
- **Existing zonal build tests (`tests/test_zonal_model_build.py`) were left unchanged** — they call `solver.solve(...)` directly and don't exercise `run_solver`. The new `tests/test_zonal_results.py` exercises the full `run_solver` → `collect_results_from_model` path end-to-end. Cleaner than mixing the two concerns in one file.

### Test counts
- New file: 7 tests, all green.
- Full suite: **362 → 369 passed**, 0 failed in 505s.

### Commit
- SHA: `53ec7d3` on `sm/zonal_model`. Not pushed.

### Open items for #11
- CSV emission for `interregional_exchanges.csv` lives in `_export_from_results_object` (`src/sdom/io_manager.py:1567`). Pattern: `if not results.interregional_exchanges_df.empty: results.interregional_exchanges_df.to_csv(os.path.join(output_dir, f"OutputInterregionalExchanges_{case}.csv"), index=False)`. Per-area CSVs (`OutputGeneration_{case}_{area}.csv` etc.) are also a candidate but not yet specified in the PRD.
- System-level zonal `summary_df` (currently empty) — would require adapting `_build_summary_dataframe` to take pre-aggregated dicts instead of probing `model.storage` directly.

---

## Zonal Capacity Expansion — Commit #9b: per-area Block dispatch + zonal solve (2026-05-09)

### Scope
Wire the AreaTransportationModelNetwork branch of `initialize_model`. Reuse 100 % of the legacy `add_*` builders by feeding each one a per-area `data_slice` shaped like the legacy `data` dict — **zero builder signature changes** (Option B implemented as a slice-shim, not a rewrite).

### Files
- `src/sdom/optimization_main.py` — new helpers `_build_per_area_data_slice` (mirrors legacy schema from `per_area_*` views; truncates timeseries to `n_hours`), `_add_area_subblocks`, `_build_one_area`, `_add_zonal_supply_balance`, `_add_zonal_genmix_constraint`, `_zonal_objective_rule`, `_initialize_model_zonal`. Dispatcher routes AT → `_initialize_model_zonal`; unknown Network → `ValueError`.
- `tests/test_zonal_model_build.py` — replaced #9a stubs with 8 tests (area set + sub-blocks; signed-flow Reals + capacity Constraint counts; per-area `SupplyBalance` + top-level `GenMix_Share`; HiGHS optimal solve with flow bounds; numerical balance residual <1e-3; `NotImplementedError` guards for resiliency-AT and Imports-AT).

### Key decisions
- **Option B = data-slice shim**, not builder refactor: each per-area slice is a dict with the same keys legacy callers expect (`load_data`, `cap_solar`, `cap_wind`, `storage_data`, `thermal_data`, `hydro_data`, formulations DataFrame, etc.) populated from `data["per_area_*"][a]`. All `add_*` functions stay untouched — Pyomo's `host` parameter convention from #7 already lets them attach to either the model or an area block.
- **`model.h` is built fresh at top level**, not aliased from a child block. Pyomo raises `RuntimeError("Re-assigning the component 'h' from block 'area[A1]' to block 'SDOM_Model'")` if you try `model.h = model.area[first_area].h`. A duplicate-content `RangeSet(1, n_hours_used)` is fine — Pyomo only objects to **sharing** a Set object across parents.
- **`area_block.index()` recovers `area_id`** inside any constraint rule whose first arg is the area block (PRD §5.4 pattern). Use this when a rule needs to look up `model.L_in[a]` / `model.L_out[a]`.
- **`Z^trans = 0`** (`network_transmission_cost_rule(model)` returns 0) — placeholder until commit with explicit transmission OPEX.
- **NotImplementedError guards**: resiliency under AT and `Imports/Exports != NotModel` under AT both raise with PRD-traceable messages. Hydro-budget under AT is also unsupported (canonical fixture is RoR; slice would need extra `large_hydro_max`/`min` keys) but is not yet guarded — relies on the canonical fixture's RoR setting. Add an explicit guard if a non-RoR zonal fixture lands.
- **Tests bypass `run_solver`**: `collect_results_from_model` (`results.py:271`) does flat lookups like `model.thermal.total_installed_capacity` that don't exist on the zonal model. Commit #10 will fix the collector. For now, tests call `pyo.SolverFactory("appsi_highs").solve(model)` directly and inspect `pyo.value(...)` of leaves.

### Patterns / gotchas
- Building `data_slice["formulations"]` is just `data["formulations"]` (formulations are global per PRD §10).
- Per-area `nuclear`/`other_renewables` use scalar `alpha` × hourly `ts_parameter`; the supply-balance term is `alpha * ts_parameter[h]` (not a generation Var).
- The signed flow `f[l,h]` is over `Reals` with **no Var bounds**; capacity is enforced by `f_upper`/`f_lower` Constraint blocks (PRD §5.6 lock — preserves per-direction duals via `Suffix`).
- HiGHS reports `feasible obj=3.21e9` on the canonical 24h fixture; full solve completes in ~10s.

### Test counts
- New: 8 tests (replaced 2 #9a stubs with 8 zonal validations).
- Full suite: **356 → 362 passed**, 0 failed in 181s.

### Commit
- SHA: `2616705` on `sm/zonal_model`. Not pushed.

### Open items for #10
- Make `collect_results_from_model` zonal-aware: detect `hasattr(model, "A")` and iterate per-area sub-blocks; emit per-area columns + system totals; populate `OptimizationResults` with `interregional_exchanges` (PRD §6 / commit #11).
- Then revisit the zonal tests to swap the direct `solver.solve(...)` calls back to `run_solver(...)`.

---

## Zonal Capacity Expansion — Commit #9a: dispatcher + fast-path lock (2026-05-08)

### Scope
Split commit #9 into 9a (dispatcher + hard fast-path lock + golden-file regression) and 9b (per-area Block construction). 9a is purely structural — zero behavioral change for legacy data.

### Files
- `src/sdom/optimization_main.py` — extracted historical body of `initialize_model` verbatim into private `_initialize_model_legacy(data, *, n_hours, with_resilience_constraints, model_name)`. New `initialize_model` is a thin dispatcher: `get_network_formulation(data) == COPPER_PLATE_NETWORK and len(data["areas"]) == 1` → legacy helper; otherwise raises `NotImplementedError("...commit #9b...")`. Imported `COPPER_PLATE_NETWORK`, `AREA_TRANSPORTATION_MODEL_NETWORK`, `DEFAULT_AREA_ID`, `get_network_formulation`.
- `tests/test_zonal_legacy_regression.py` (new, 5 tests) — 4 parametrized golden-file cases (RoR 24h / Monthly 730h / Daily 168h / Daily+Imp/Exp 168h) reusing the historical objective values from existing `test_no_resiliency_*` files; plus a `monkeypatch.setattr` delegation spy that proves the dispatcher actually calls `_initialize_model_legacy`.
- `tests/test_zonal_model_build.py` (new, 2 tests) — scaffolding for #9b. Asserts `Data/zonal_test` raises `NotImplementedError` with PRD-traceable message and pins the dispatcher classification axis (`get_network_formulation` + `len(data["areas"])`).

### Key decisions
- **Public signature unchanged**: kept `n_hours` positional in `initialize_model(data, n_hours=8760, ...)` because existing tests call `initialize_model(data, n_hours=24, ...)` (still positional-compatible) and a `*` separator now would silently break callers. PRD §3.4's keyword-only example is a future cleanup, NOT this commit.
- **Helper signature uses `*`**: `_initialize_model_legacy(data, *, ...)` because it's private and exists only to be called by the dispatcher. Forces named delegation.
- **Golden values reused, not regenerated**: The legacy regression test pulls the same 4 numbers already enforced by `test_no_resiliency_optimization_cases.py`, `test_no_resiliency_hydro_budget_optimization_cases.py`, `test_no_resiliency_imp_exp_hydro_budget_optimization_cases.py`. This avoids drift — if any of those numbers change, both tests break together.
- **Tolerance `<= 10` (USD)**: matches the existing tests' tolerance. The existing tests already pass under HiGHS so the same tolerance is sufficient.
- **`NotImplementedError` message must reference PRD §5/§10 + commit #9b** so a future maintainer hitting it knows where to look.

### Patterns / gotchas
- The `monkeypatch.setattr("sdom.optimization_main._initialize_model_legacy", _spy)` pattern works because `initialize_model` references the helper by **module-qualified name** at call time (it's looked up in module globals). If we ever inlined `_initialize_model_legacy` into `initialize_model`'s closure, the spy pattern would break — keep the function module-level.
- The dispatcher uses `data.get("areas", [{"area_id": DEFAULT_AREA_ID}])` for defensive defaulting, but in practice every dict from `load_data` already has `data["areas"]` since commit #4. The default is belt-and-suspenders for callers building `data` by hand.
- Imported `AREA_TRANSPORTATION_MODEL_NETWORK` even though it's only used inside the f-string indirectly (via `network` runtime value) — kept it explicit so a reader can see both possible network values at the import site.

### Test counts
- New: 7 tests (5 + 2). All green.
- Full suite: **349 → 356 passed**, 0 failed in 167s.

### Commit
- SHA: `621db72` on `sm/zonal_model`. Not pushed.

### Open items for #9b
- Refactor every `add_*` builder in `formulations_*.py` + `initialize_sets`/`initialize_params` to accept a `data_slice` (user-locked decision B). The slice will be a derived dict where global keys (`cap_solar`, `storage_data`, `load_data`, …) point to the per-area DataFrame from `data["per_area_*"][a]`.
- Build `model.A` (top-level Set), `model.area = Block(model.A)`, then loop areas calling each builder with `host=model.area[a]` + per-area `data_slice`.
- Wire `formulations_network` (commit #8): `add_network_sets(model, lines=..., line_from=..., line_to=...)`, `add_network_parameters(model, line_cap_ft=..., line_cap_tf=...)`, `add_network_variables(model)`, `add_network_constraints(model)`, `add_network_expressions(model)`.
- Replace `formulations_system.create_supply_balance_rule` to operate on a `host` (area block) and add the `NetFlow` term: `+ sum(model.f[l,h] for l in model.L_in[a]) - sum(model.f[l,h] for l in model.L_out[a])`. The rule's first arg becomes the parent `model` (so it can reach `model.f`, `model.L_in`, `model.L_out`); the per-area `host` is captured in the closure.
- Aggregate the objective over areas: `Z = sum(Z^pv_a + Z^wind_a + ... for a in m.A) + Z^trade + Z^trans`. The cost-sub-functions (`add_vre_fixed_costs`, etc.) currently sum over `host.pv` / `host.wind` etc. — once they take `host=model.area[a]`, the area-level sum becomes `sum(add_vre_fixed_costs(model.area[a]) for a in model.A)`.
- Resiliency + AT path → `NotImplementedError` (PRD §5.8) — that's commit #12 but the guard could land in #9b's dispatcher already.

---

## Zonal Capacity Expansion — Commit #8: `formulations_network.py` (2026-05-08)

### Scope
Pure additive new module `src/sdom/models/formulations_network.py` (PRD §5.6). Not yet wired into `initialize_model` (commit #9). 9 new tests in `tests/test_zonal_formulations_network.py`. Full suite: **349 passed** (340 + 9).

### Key decisions
- **`f_FT` / `f_TF` are `Expression` of *signed* scalars** (`m.f[l,h]` and `-m.f[l,h]`), not `max(.,0)` — `max` is non-linear and would break LP-ness even in an Expression. Documented in module + function docstring that downstream reporting must clip with `max(value(...), 0.0)`. Since at the LP optimum at most one direction carries positive flow, the signed value already encodes both directions losslessly.
- **`L_in[a]` / `L_out[a]` built from precomputed Python dicts** captured in the closure, not via rules that introspect `m.line_from` / `m.line_to`. Avoids Pyomo deferred-construction ordering surprises (Param indexing inside Set rule is brittle).
- **`Var.domain` is not accessible on the indexed container**; must check on each element: `m.f[l,h].domain is pyo.Reals`. (Caught by initial test failure.)
- Used `from pyomo.environ import ...` exclusively (matches `formulations_storage.py` style closely enough).

### Solver fixture pattern (reused)
```python
def _highs():
    for name in ("appsi_highs", "highs"):
        try:
            s = pyo.SolverFactory(name)
            if s is not None and s.available(exception_flag=False):
                return s
        except Exception:
            continue
    pytest.skip("HiGHS solver not available")
```
And `m.dual = pyo.Suffix(direction=pyo.Suffix.IMPORT)` for shadow prices.

---

## Zonal Capacity Expansion — Commit #5: interconnections + line capacities (2026-05-08)

### Scope
Added `_load_interconnections`, `_load_one_line_cap`, `_load_line_capacities` helpers in `io_manager.py`; wired into `load_data` to populate `data["lines"]`, `data["line_cap_ft"]`, `data["line_cap_tf"]`. Added 3 fixture files to `Data/zonal_test/` (single line `L_A1_A2`, 8760×1 caps at 500 MW). 12 new tests in new `tests/test_zonal_io_lines.py`. Updated 1 placeholder test in `test_zonal_io_validation.py` (the AT-formulation acceptance test now uses the zonal fixture instead of the legacy folder, since AT now requires topology files).

### Files
- `src/sdom/constants.py` — added 3 entries to `INPUT_CSV_NAMES` (`interconnections`, `line_cap_ft`, `line_cap_tf`).
- `src/sdom/io_manager.py` — new helpers + wiring; conditional ERROR raised when `Network=AreaTransportationModelNetwork` but any of the 3 files is missing.
- `scripts/build_zonal_test_fixture.py` — extended (kept in sync with the on-disk fixture).
- `Data/zonal_test/{interconnections.csv, LineCap_FT.csv, LineCap_TF.csv}` — 3 new files.
- `tests/test_zonal_io_lines.py` — 12 tests.
- `tests/test_zonal_io_validation.py` — replaced `test_load_data_accepts_explicit_area_transportation` placeholder.

### Key decisions
- Empty-`lines` ⇒ return two empty `pd.DataFrame()`s for `line_cap_ft`/`tf` (not `None`). Easier for downstream model code to iterate without `None` checks.
- Validation only runs when `lines != []`. If lines empty AND files exist, the (empty-lines) case still returns DataFrames raw — but in practice this never occurs because `interconnections.csv` is the FK source.
- AT-formulation requirement check sits in `load_data` (not in helpers) so helpers stay reusable.
- Reordered line-cap columns to match `lines` order for stable downstream access.
- Fixture column header for hour index is `*Hour` (matches the other 8760-row CSVs).

### Patterns / gotchas
- `get_complete_path` returns `""`/falsy when the file is absent — use `if not path: return …`.
- `pd.DataFrame.empty` is True for both 0-rows and 0-columns; for the empty-lines return I used the no-arg constructor (no rows AND no cols).
- Negative-value detection: `(cap < 0).values.nonzero()` returns `(rows, cols)` index arrays — pick `[0]` for the first violation.
- Updating an existing test counted as "necessary" rather than "touching unrelated tests" because the orchestrator explicitly listed `test_zonal_io_validation.py` as a target file and the placeholder doc-string ("full zonal loading wires up in later commits") signaled the intent.

### Test counts
- New file: 12 tests, all green.
- Full suite: **329 passed**, 0 failed (was 317). 2 unknown-mark warnings (`pytest.mark.slow`) — pre-existing.

### Commit
- SHA: `2cb7ad9` on `sm/zonal_model`. Not pushed.

### Open items for downstream commits
- Commit #6: copper-plate aggregation fallback for |areas|>1 (still not implemented).
- Commit #9 will consume `data["lines"]`/`line_cap_*` to build the Pyomo line set + flow vars.
- Commit #12 flips `Data/zonal_test/formulations.csv` Network row to `AreaTransportationModelNetwork`.

---

## Zonal Capacity Expansion — Commit #12 partial: `Data/zonal_test/` fixture (2026-05-08)

### Scope
Built the canonical 2-area zonal CSV fixture under `Data/zonal_test/` (combining `Data/no_exchange_run_of_river/` as A1 and `Data/no_exchange_monthly_hydro_budget_multiple_balancing_p50/` as A2) and refactored `tests/test_zonal_io_per_area.py` to consume it. Skipped `interconnections.csv` / `LineCap_*.csv` (commit #5).

### Files
- `scripts/build_zonal_test_fixture.py` (new, one-shot generator).
- `Data/zonal_test/*.csv` (13 files: areas, formulations, scalars, 4 hourly, 2 cap, 2 cf, BalancingUnits, StorageData).
- `tests/test_zonal_io_per_area.py` rewritten: 19 → **27 tests** (5 parser unit + 4 legacy folder + 1 legacy CapSolar + 1 areas-default-synth + 11 zonal happy-path + 1 areas-synth-from-tags + 4 validation-error mutation).

### Locked decisions / fixture spec
- Hydro = `RunOfRiverFormulation` globally (drop A2's `lahy_max`/`lahy_min`).
- Imports/Exports = `NotModel` globally (no Import_*/Export_* templates).
- Network = `CopperPlateNetwork`. With `|areas|>1` aggregation fallback NOT yet implemented (commit #6), `load_data` still succeeds because the global keys are populated raw (tagged columns flow into `data["storage_data"]` etc.); the per-area views are clean. Tests in this file only inspect per-area views + `data["areas"]`, so initialize_model is never called.
- StorageData uses Encoding B with tagged tech columns (`Li-Ion@A1@`, …); tech ids legitimately repeat across areas because `@area_id@` disambiguates.
- No sc_gid or Plant_id collisions encountered (A1 uses integer ids + `83_GAS`/`83_Coal`; A2 uses `Nordeste` and lowercase-suffixed ids `83g`, `98g`, …). No suffixing needed.

### Patterns / gotchas
- Hybrid test strategy (locked by orchestrator): happy-path tests load `Data/zonal_test/` directly; validation-error tests `shutil.copytree` the fixture into `tmp_path/data` and mutate one CSV. Header-only mutations done via a tiny `_rewrite_csv_header(path, replacements)` helper that rewrites line 1 to avoid round-tripping a 8760-row CSV through pandas.
- `load_data` does NOT crash on tagged StorageData columns: `storage_data.loc["Coupled"]` still returns a Series and `.columns[mask]` works, populating `STORAGE_SET_J_TECHS` with tagged names. Aggregation in commit #6 will need to overwrite these globals (or de-tag them) before `initialize_model` runs.
- `compare_lists(solar_plants, solar_plants_capex)` only logs warnings — does not raise — so a 100+1 split where order matches across CFSolar/CapSolar passes silently.
- `lahy_hourly_*` is the only hydro file under RunOfRiver; `_split_wide_by_area` on `large_hydro_max`/`min` returns `({}, set())` when those globals are missing (the `data.get()` lookup yields `None`).
- Source files use `*Hour` (with leading asterisk) as the time-key column; this becomes the first column of `_split_wide_by_area` output and is preserved verbatim in every per-area slice.
- Memory-file updates remain out-of-scope of the test commit — staged the fixture, script, and test file only.

### Test counts
- File: 19 → 27 tests, all green.
- Full suite: **317 passed**, 0 failed (was 309). 2 unknown-mark warnings (`pytest.mark.slow`) — pre-existing.
- Run time ~135s.

### Commit
- SHA: `c095ecb` on `sm/zonal_model`. Not pushed.

### Open items for downstream commits
- **Commit #5** (`interconnections.csv` + `LineCap_*.csv`): the fixture is missing these intentionally; add them when topology lands.
- **Commit #6** (aggregation fallback): `data["storage_data"]` columns are tagged in the zonal_test fixture today. Aggregation must either de-tag (`Li-Ion@A1@` → `Li-Ion`) or overwrite globals from `per_area_storage`. Same caveat for `STORAGE_SET_J_TECHS`/`STORAGE_SET_B_TECHS`.
- The fixture's `scalars.csv` is taken from A1 verbatim; A2 has `FCR_GasCC`, `LifeTimeGasCC`, different `GenMix_Target`/`AlphaNuclear`. Document or reconcile when scalars become per-area.

---

## Zonal Capacity Expansion — Commit #4 (per-area io_manager) (2026-05-08)

### Scope
Implemented `feat(io): support area_id column and zonal CSV layout` (PR #53, branch `sm/zonal_model`). Adds the per-device parsing layer for the hybrid encoding (Encoding A row-oriented `area_id` column / Encoding B wide-CSV `@area_id@` header tag) without touching topology / LineCap / aggregation (commits #5–#6).

### Files modified
- `src/sdom/io_manager.py` — added `_parse_area_tagged_header`, `_split_wide_by_area`, `_split_row_by_area`, `_split_cf_by_plant_area`, `_combine_per_area_imp_exp`, `_load_areas`, `_validate_observed_areas`, `_augment_with_per_area_views`. Hooked the augmenter as the last step of `load_data`. Imported `re`, `DEFAULT_AREA_ID`, `AREA_TAG_DELIMITER`, `get_complete_path`.
- `tests/test_zonal_io_per_area.py` (new) — 19 tests covering parser unit behaviour, legacy folder per-area defaults, pickle/deepcopy survivability, zonal wide/row splits, and all PRD §4.5 validation rules.

### Key learnings / gotchas
- **`Data_BalancingUnits.csv` is row-oriented today**, despite the PRD §2.3 example showing it as Encoding B. Treated it as Encoding A (optional `area_id` column) keyed on `Plant_id` — documented as an intentional deviation in the function docstring. Revisit when the long-format migration lands.
- **Avoid pandas fragmentation warnings**: building a per-area DataFrame via repeated `df[col] = ...` insertions triggers `PerformanceWarning`. Group source columns by area first, then assemble each per-area frame in a single `df[[key, *cols]].rename(columns=...).copy()` call.
- **`StorageData.csv` is read with `index_col=0`**, so `_split_wide_by_area` won't accept it directly. Reset/restore the index before/after splitting (the property index becomes the first column for parsing, then is re-set on each per-area slice).
- **CRLF-vs-LF normalization noise** during `git commit` shows inflated insertion/deletion counts. The persisted diff (`git show --stat HEAD`) is the authoritative number. For this commit: real diff is +831 / -1 across 2 files.
- **`get_complete_path`** is the right helper for soft-matching CSV filenames (handles year-suffixed filenames like `Load_hourly_2050.csv`). Don't hard-code basenames in zonal helpers.
- **Picklability**: keep the new `data` keys as plain `dict[str, pd.DataFrame|pd.Series]`; verified with `pickle.dumps` + `copy.deepcopy` so the parametric deepcopy path stays safe.

### Test counts
- New: **19** in `tests/test_zonal_io_per_area.py`.
- Input-data + zonal regression bucket: **50 passed** (10 + 2 + 2 + 11 + 6 + 19).
- Full suite: **309 passed, 0 failed, 0 skipped** in 307s.

### Commit
- SHA: `964cd45` on `sm/zonal_model`. Not pushed.

### Open items / blockers for downstream commits
- **Commit #5** (`interconnections.csv`, `LineCap_FT/TF.csv`, `_load_topology`, `_load_line_capacities`): nothing in this commit constrains it; the `data["areas"]` and per-area dicts are already in place to validate FK references.
- **Commit #6** (aggregation fallback): the per-area views are the natural input. Existing global keys (`load_data`, `cap_solar`, …) are still loaded by the legacy path and remain intact for legacy folders, so aggregation can either (a) overwrite globals from the per-area dicts when zonal+CopperPlate, or (b) re-derive them via concatenation. Recommend (a) for clarity.
- **PRD §2.3 Data_BalancingUnits Encoding B example** is currently inconsistent with the actual row-oriented file. Either migrate the file format in a later commit or correct the PRD.
- `uv.lock` had pre-existing dirty state on the workspace (added `contourpy` etc.); deliberately NOT staged in this commit.

---

## Zonal Capacity Expansion — Phase 2 PRD (2026-05-07)

### Scope
Authored the Product Requirements Document at `dev_guidelines/zonal_model/PRD.md` based on the locked math model in `dev_guidelines/zonal_model/math_model.md`. Documentation only — no source code changes.

### Key design decisions (locked in PRD)
- **`Network` row in `formulations.csv`**: `CopperPlateNetwork` (default if missing) vs `AreaTransportationModelNetwork`. New `VALID_NETWORK_FORMULATIONS_TO_DESCRIPTION_MAP` constant.
- **Single signed flow `m.f[L, H] in Reals`** with asymmetric two-sided bounds via `Var(bounds=…)`. No bidirectional flow possible by construction. `f_FT`/`f_TF` are derived **post-solve only**, not decision variables.
- **Per-area `Block` architecture** (`m.area[a]`) mirroring today's sub-block structure (`pv`, `wind`, `thermal`, `storage`, `hydro`, `imports`, `exports`, `demand`, `nuclear`, `other_renewables`).
- **Legacy single-area fast path** preserved: when `|A|=1` and `Network=CopperPlateNetwork`, build directly on `m.*` (no area-block indirection) → guarantees zero perf regression. Golden-file regression test enforces objective-value identity.
- **System-wide expression names preserved** (`m.total_pv_generation`, etc.) so existing CSVs/plots don't break. Per-area mirrors get an `_by_area` suffix or live inside `m.area[a]`.
- **Single-folder + optional `area_id` column** chosen over per-area subfolders. Wide CSVs use `<area_id>__<entity>` namespaced columns; long CSVs gain `area_id` column. Legacy data with neither falls into synthetic `area_id="default"`.
- **Aggregation fallback** (zonal data + `CopperPlateNetwork`): sum demands/capacities; capacity-weighted average of import/export prices; emit `WARNING`s.
- **`io_manager.load_data` refactor**: split into private stages (`_load_formulations`, `_load_areas`, `_load_topology`, `_load_per_area_devices`, `_aggregate_to_single_area`, `_validate`); returned `data: dict` keeps every existing key and adds `areas`, `lines`, `line_cap_ft`, `line_cap_tf`, `per_area_*` views.
- **`formulations_*.py` refactor pattern**: change first arg from `model` to `host` (either top-level model or area block). Most modules already access sub-blocks (`model.pv.*`) so the change is mechanical. Pre-implementation audit required (§5.4 of PRD).
- **New module `formulations_network.py`**: holds `add_network_parameters`, `add_network_variables`, `add_network_expressions` (`Z_trans=0` placeholder reserved for future transmission-investment work).
- **`formulations_system.create_supply_balance_rule`** becomes per-area; legacy 2-arg signature kept as a shim.
- **`OptimizationResults`** gains optional `area_generation_df: dict[str, pd.DataFrame]`, `area_storage_df`, `area_installed_plants_df`, `interregional_exchanges_df`. All existing fields stay.
- **New output CSV**: `interregional_exchanges.csv` with `Hour, line_id, from_area, to_area, f, f_FT, f_TF, capacity_FT, capacity_TF, utilization_FT, utilization_TF`.
- **Test dataset**: `Data/zonal_test/` combining `Data/no_exchange_run_of_river/` (a1) + `Data/no_exchange_monthly_hydro_budget_multiple_balancing_p50/` (a2). Hydro stays global (`MonthlyBudgetFormulation`); a1 budget bounds set equal to degenerate to RoR-equivalent.
- **Resiliency under zonal**: deferred. `with_resilience_constraints=True` + `Network=AreaTransportationModelNetwork` should raise `NotImplementedError` until follow-up PRD lands.

### Decisions deferred to user/orchestrator
- Per-area $\tau_a$ targets (math reserved, impl deferred).
- Per-area formulation choices (e.g. RoR in a1, MonthlyBudget in a2) — out of scope.
- Wide-CSV namespace separator (`__` proposed).
- Per-area parametric sweeps (basic path documented; full impl can defer).
- Output CSV name (`interregional_exchanges.csv` proposed).

### Patterns to apply in Phase 3
- When refactoring `formulations_*.py`, unit-test each function with both `host=model` and `host=model.area[a]` to catch hidden coupling.
- Picklability audit: `data` must remain pure DataFrames/lists/dicts; no Pyomo objects (parametric workers deepcopy `data`, rebuild model).
- Plot helpers should short-circuit on empty `area_generation_df` so they remain safe to call unconditionally from `_single.plot_results`.

---

## Resiliency Module - Phase 7 (2026-05-05)

### Scope
Top-level convenience `evaluate_resiliency` (Deliverable A) + end-to-end PGnE integration test (Deliverable B). Final implementation phase; only documentation remains.

### Files created/modified
- `src/sdom/resiliency/evaluate.py` (new) — `evaluate_resiliency(snapshot_dir, *, inputs_dir, outage_spec, ...)` chains `load_designed_system → build_baseline_dispatch → run_baseline_dispatch → run_resiliency_evaluation`. Pure pass-through; no defaults overridden beyond mirroring downstream APIs.
- `src/sdom/resiliency/__init__.py` — re-export `evaluate_resiliency`.
- `src/sdom/__init__.py` — top-level re-export of `evaluate_resiliency` (per plan §2: explicit re-exports only, no side effects).
- `tests/test_resiliency_evaluate.py` (4 tests) — synthetic + kwargs pass-through + default/explicit hours subset.
- `tests/test_resiliency_integration.py` (1 slow test) — real PGnE 24h chain end-to-end (load → dispatch → eval → metrics → save/load → plot).

### Patterns established
- **Top-level convenience helpers stay thin**: `evaluate_resiliency` is a 4-call pass-through. No new defaults, no parameter renames; mirrors downstream signatures so behaviour is identical to the manual chain.
- **Monkeypatch downstream calls in evaluate-module namespace**: tests substitute `evaluate_module.load_designed_system` / `build_baseline_dispatch` / `run_baseline_dispatch` / `run_resiliency_evaluation` (via `monkeypatch.setattr(evaluate_module, ...)`). The `evaluate.py` module imports these by name at module top so monkeypatching that name redirects all subsequent calls — same pattern Phase 5 used for `runner._build_outage_dispatch`.
- **Synthetic tests skip CSV materialization**: writing the ~15 CSVs that `load_designed_system` requires would dominate the test. Patching the loader to return a synthetic `DesignedSystem` is a pragmatic deviation; the real CSV path is exercised exactly once in the integration test (which is the more meaningful assertion).
- **Integration test guards**: triple skipif (HiGHS missing / data dir missing / pyarrow missing via `importorskip` for the persistence step only). Test still runs in default `pytest` invocation despite `@pytest.mark.slow` (no `--strict-markers`; warning is benign).
- **Restore round-trip equality**: compare metric scalars individually with `pytest.approx(..., nan_ok=True)`; `n_hours_evaluated`/`n_errors` are ints so compared exactly. Saved JSON only carries aggregate metrics + a few metadata keys; the OutageSpec object itself is dropped on load (Phase 6 design).

### Gotchas
- `Axes` import path: `matplotlib.axes.Axes` (not `matplotlib.pyplot.Axes`).
- Force `matplotlib.use("Agg")` BEFORE `import pyplot` to keep CI headless.
- `OutageSpec(outaged_assets={"balancing_units": "all"})` is valid even when `thermal_caps == {}` — string "all" passes both `__post_init__` and `validate()`.
- `pytest.mark.slow` is unregistered → emits `PytestUnknownMarkWarning`. Acceptable; matches the rest of the suite.
- The synthetic test runs 24 anchor hours in serial (n_workers=1); each is a tiny LP so the whole file completes in ~2s.

### Final public-API surface (`src/sdom/resiliency/__init__.py` `__all__`)
`BaselineDispatchResults, BaselineState, DesignedSystem, MUST_RUN_COMPONENTS, OutageSpec, ResiliencyResults, VALID_COMPONENTS, add_imports_with_demand_charges, build_baseline_dispatch, build_outage_dispatch, evaluate_resiliency, load_designed_system, plot_metric_distribution, run_baseline_dispatch, run_resiliency_evaluation`.

### Test counts
- New file `tests/test_resiliency_evaluate.py`: **4 passed**.
- New file `tests/test_resiliency_integration.py`: **1 passed**.
- Full suite (deselecting xpress-only file): **260 passed, 9 deselected** in 242s. Zero regressions.

### Open issues for documentation phase
- `docs/user-guide/resiliency.md`: add quickstart that uses `evaluate_resiliency` (single call) instead of the four-step manual chain.
- API reference autodoc must include the new `evaluate.py` module.
- Plan §11 (examples) — wire a notebook or `examples/` snippet showing `evaluate_resiliency` + `plot_metric_distribution`.
- `pytest.mark.slow` could be registered in `pyproject.toml` `[tool.pytest.ini_options].markers` to silence the warning; not done here to keep this phase additive.

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

---

## Resiliency Module - Phase 5 (2026-05-05)

### Scope
Deliverable: `run_resiliency_evaluation` orchestrator with serial + ProcessPoolExecutor parallel paths. `ResiliencyResults` lightweight container.

### Files created/modified
- `src/sdom/resiliency/runner.py` (new) - module-level `_solve_one_hour` worker for spawn-safe pickling.
- `src/sdom/resiliency/system_state.py` - added `ResiliencyResults` dataclass with `to_dataframe` + `eue_total`.
- `src/sdom/resiliency/dispatch_model.py` - stash `model._sdom_designed_system` in build, copy into `results.metadata['designed_system']` in run_baseline_dispatch.
- `src/sdom/resiliency/__init__.py` - re-export `run_resiliency_evaluation` + `ResiliencyResults`.
- `tests/test_resiliency_runner.py` (9 tests, serial path).
- `tests/test_resiliency_runner_parallel.py` (3 tests, ProcessPoolExecutor).

### Patterns established
- **Monkeypatching multiprocess code**: keep a module-level handle `_build_outage_dispatch = build_outage_dispatch` so `test_worker_failure_isolated` can substitute it for the SERIAL path. Subprocess workers re-import the module so the monkeypatch does NOT propagate to subprocesses (intentional: only serial path is monkeypatch-friendly).
- **Worker payload is a flat dict** of picklable items only (DesignedSystem, BaselineDispatchResults, OutageSpec, scalars, dict of options). Never pass Pyomo ConcreteModel through the pool - rebuild it inside the worker.
- **Order preservation**: `executor.map` preserves input order. Sort payloads by `start_hour` BEFORE submission, then sort records again post-hoc as defence in depth.
- **n_workers resolution**: `None -> max(1, os.cpu_count() - 1)`; clamp to `min(n, len(payloads))`. Use `os.cpu_count()` (with parentheses) so monkeypatch.setattr(os, 'cpu_count', lambda: N) works.
- **Failure isolation**: try/except inside the worker captures `traceback.format_exc()` into `error_message`, sets `solver_status='error'`. Numeric metrics zeroed except objective_value=NaN.
- **Truncation flag**: `truncated = (start_hour + duration + max_recovery - 1) > n_hours`. Computed in the worker (cheap) so it's on the per-hour record even if the solve fails.
- **Solver discovery**: `_resolve_solver` first tries `appsi_highs` then `highs`; reused per worker (each worker creates its own SolverFactory instance).

### Gotchas
- Storage with eta=1 will arbitrage SOC even in 'no-outage' tests; my first `test_run_with_explicit_designed_system_kwarg` predicted obj=3000 but optimum was 2700 (storage discharged 10MWh at hour 1 since recovery target only constrained final SOC). Fix: assert qualitative properties (EUE==0, status=='optimal') instead of pinning the objective.
- `ResiliencyResults.per_hour` index is named `hour` (not `start_hour`) but the underlying record dict uses `start_hour`; `set_index('start_hour')` then `index.name = 'hour'`. `to_dataframe` resets that to a column named `hour`.
- Windows `spawn` works fine for the runner because all worker code lives in the runner module (importable) and payloads only contain dataclasses/dicts/Series/DataFrames.

### Open issues for Phase 6
- Aggregate metrics: LOLP, LOLE, p50/p95/p99 of EUE - add `ResiliencyResults.metrics(level='aggregate')` plus convenience scalars (`lole()`, `lolp()`, `eue()`).
- Persistence: `save(path)` -> Parquet + JSON sidecar; `classmethod load(path)`.
- Optional full dispatch traces (`keep_full_traces=True`).
- Plotting (`plot_metric_distribution`, hist/ecdf/exceedance).
- Top-level `evaluate_resiliency` convenience that chains load -> baseline -> evaluation.
- Consider exposing `solve_time_s` aggregates to surface slow-hour outliers.
- The `_USE_EPS = 1e-6` slack tolerance may need to be solver-aware; HiGHS default tolerances are ~1e-7 so 1e-6 is conservative. Document or make configurable in Phase 6.

---

## Resiliency Module - Phase 6 (2026-05-05)

### Scope
Deliverables: (A) aggregate metrics on ResiliencyResults, (B) save/load Parquet+JSON sidecar, (C) plot_metric_distribution.

### Files modified/created
- `src/sdom/resiliency/system_state.py` - added `_summarize_outage_spec`, `metrics(level=...)`, `lolp/lole/eue`, `save/load`, `_build_summary_payload`, `_is_json_safe` helper. Added `json`, `Path`, `numpy` imports.
- `src/sdom/resiliency/plotting.py` (new) - lazy matplotlib import; supports kind in {hist, ecdf, exceedance}; rejects errored rows; validates metric name.
- `src/sdom/resiliency/__init__.py` - re-export `plot_metric_distribution`.
- `tests/test_resiliency_metrics.py` (5 tests).
- `tests/test_resiliency_results_persistence.py` (5 tests, `importorskip('pyarrow')`).
- `tests/test_resiliency_plotting.py` (6 tests, Agg backend).

### Patterns established
- **Default metric formulas** (math_model.md sec 7): LOLP = mean(EUE>0), LOLE = mean(USE_hours), mean_EUE = mean(EUE), p50/95/99 via `np.percentile(..., method='linear')`. Errored rows excluded from numerator and denominator; `n_errors` reported separately.
- **Persistence**: `./results_resiliency/` default path. `per_hour.parquet` + `summary.json`. JSON sidecar shape: `{version: '1', aggregate_metrics: {...}, metadata: {n_workers_used, n_hours, solver, outage_spec_summary}}`. Full `OutageSpec` is NOT pickled - only a summary dict (duration_hours, recovery_hours, outaged_assets_components). `load` does NOT reconstruct OutageSpec; metadata is JSON-only.
- **Optional pyarrow**: not added to `pyproject.toml`. `to_parquet/read_parquet(engine='auto')` raises a wrapped `ImportError` with hint. Tests gate on `pytest.importorskip('pyarrow')`. I installed pyarrow into `.venv` only via `uv pip install pyarrow` to exercise tests locally - do NOT propagate to pyproject.
- **Plotting**: lazy `import matplotlib.pyplot` inside the function so the module imports head-less. Filter `solver_status != 'error'` then drop NaNs. Exceedance: `y = 1 - arange(n)/n` so y[0]=1, y[-1]=1/n (matches 'monotonically decreasing from 1 to 0' spec). Only sets xlabel/ylabel when not already set, so external-ax callers can pre-style.
- **API discipline**: all new public methods are keyword-only beyond the primary object (`metrics(*, level=...)`, `eue(*, p=None)`, `save(path=None)`, `plot_metric_distribution(results, *, metric, kind, ax, **kwargs)`).

### Gotchas
- `np.percentile` keyword changed from `interpolation` to `method` in numpy 1.22; pin to `method='linear'` (numpy>=2.2 in this repo so safe).
- `json.dumps` with `default=str` rescues numpy scalars in aggregate_metrics, but I cast everything to plain `float`/`int` first to keep the JSON tidy.
- `ResiliencyResults.load` round-trip: pandas read_parquet preserves the `hour` index name correctly via pyarrow; no manual index restoration needed.
- `ax.has_data()` is True only after plotting; check after the call, not before.

### Open issues for Phase 7
- Top-level `evaluate_resiliency` convenience: load_designed_system -> run_baseline_dispatch -> run_resiliency_evaluation chain, returning `ResiliencyResults` with full metadata (including `baseline_objective`, `designed_system_summary`).
- Integration test on real PGnE 24h subset (mark slow) hitting metrics+save+load+plot end-to-end.
- Doc updates: `docs/user-guide/resiliency.md` for metrics/persistence/plotting; API reference autodoc; quickstart snippet.
- Consider adding `pyarrow` as an optional extra `[project.optional-dependencies] resiliency_io = ['pyarrow>=...']` once persistence is exercised by users.
- Plotting extras: hour-of-year scatter; SOC trajectory plot when `keep_full_traces=True` lands.
