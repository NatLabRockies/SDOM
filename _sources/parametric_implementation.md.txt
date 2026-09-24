# Developer Guide: `sdom.parametric` Implementation

This page describes the internal design of the `sdom.parametric` sub-package
for contributors who need to maintain, extend, or debug it.

For end-user usage see [Parametric & Sensitivity Analysis](user_guide/parametric_analysis.md).

---

## Sub-package layout

```
src/sdom/parametric/
├── __init__.py      # Public surface — re-exports ParametricStudy + sweep types
├── sweeps.py        # Sweep descriptor dataclasses (no logic, just validated containers)
├── mutations.py     # Stateless data mutation helpers + TS_KEY_TO_COLUMN mapping
├── worker.py        # Module-level picklable worker function (_run_single_case)
└── study.py         # ParametricStudy orchestrator + _make_safe_name utility
```

**One-way dependency rule:** `parametric` imports from the rest of `sdom`
(`optimization_main`, `io_manager`, `results`), but no existing `sdom` module
imports from `parametric`. Keep this direction to avoid circular imports.

---

## Data flow

```
ParametricStudy.run()
  │
  ├── _build_case_dicts()
  │     ├── itertools.product(*dimensions)   ← Cartesian product
  │     ├── _make_safe_name(label)           ← filesystem-safe case name
  │     └── collision detection             ← append _{index} if name collides
  │
  ├── ProcessPoolExecutor.submit(_run_single_case, case_dict)
  │     │                  (one future per case)
  │     └─ [worker process] ─────────────────────────────────────────────────
  │           ├── copy.deepcopy(case_dict["data"])    ← lazy copy, in-worker
  │           ├── _apply_scalar_mutation(...)
  │           ├── _apply_storage_factor_mutation(...)
  │           ├── _apply_ts_mutation(...)
  │           ├── initialize_model(data, n_hours, ...)
  │           └── run_solver(model, solver_config, case_name)
  │                    └── returns OptimizationResults
  │
  ├── as_completed(futures)
  │     ├── log progress [completed/total]
  │     ├── export_results(result, case_name, output_dir/<case_name>/)
  │     └── ordered_results[case_index] = result      ← index-based ordering
  │
  └── _write_summary_csv(case_dicts, ordered_results)
        └── parametric_summary.csv
```

---

## Key design decisions

### 1. Lazy deep-copy (memory efficiency)

**Problem:** Pre-allocating one `copy.deepcopy(base_data)` per case in the
parent process (before dispatching to workers) causes the parent to hold
`N × sizeof(base_data)` in memory simultaneously — a significant spike for
large sweeps (50+ cases) or large datasets.

**Solution:** Each `case_dict` carries a reference to `self._base_data`
(the shared original). The deep copy is deferred to inside `_run_single_case`,
which runs in a worker subprocess. Because `ProcessPoolExecutor` pickles
arguments on dispatch, the `base_data` is serialised once per case on
submission. The deep copy then runs inside the worker's own memory space,
so the **parent process** always holds only one copy of the base data,
regardless of sweep size.

```python
# study.py — case_dict carries a reference, not a copy
case_dicts.append({
    "data": self._base_data,   # shared reference
    ...
})

# worker.py — copy is made inside the worker process
data: dict = copy.deepcopy(case_dict["data"])
```

### 2. Collision-safe case naming

`_make_safe_name` replaces filesystem-forbidden characters with `_`. This
can cause two distinct parameter combinations to produce the same string
(e.g. `1.0/2` and `1.0_2` both → `1.0_2`).

**Solution:** After building all case dicts, `_build_case_dicts` counts
how many times each safe name appears. Any name that appears more than once
gets an index suffix appended: `<name>_<case_index>`.

```python
name_counts: Dict[str, int] = {}
for cd in case_dicts:
    name_counts[cd["case_name"]] = name_counts.get(cd["case_name"], 0) + 1
for cd in case_dicts:
    if name_counts[cd["case_name"]] > 1:
        cd["case_name"] = f"{cd['case_name']}_{cd['case_index']}"
```

This is deterministic: the same sweep configuration always produces the same
set of case names.

### 3. Result ordering via `case_index` (not name lookup)

`as_completed` returns futures in completion order (non-deterministic). To
reconstruct results in Cartesian-product order, each case dict carries an
integer `case_index` (its position in the product). Results are stored in a
pre-allocated list: `ordered_results[cd["case_index"]] = result`.

This is collision-safe: even if case names are disambiguated, the index is
always unique.

### 4. Module-level worker function (pickling)

`_run_single_case` must be defined at module level in `worker.py`, not as a
nested function or lambda. `multiprocessing` uses `pickle` to send work to
subprocesses, and only module-level callables can be pickled.

### 5. Graceful failure

Both the worker and the orchestrator catch all exceptions:

- `_run_single_case` catches exceptions from mutations, `initialize_model`,
  and `run_solver`. On failure it returns `OptimizationResults` with
  `termination_condition="exception"` and `total_cost=float("nan")`.
- `study.run()` catches exceptions from `future.result()` (e.g. pickling
  failures or worker crashes). It constructs the same failure result object.

`total_cost=NaN` (not `0.0`) ensures failed cases are distinguishable from
valid zero-cost results in the summary CSV.

---

## `mutations.py` — TS_KEY_TO_COLUMN mapping

The `TS_KEY_TO_COLUMN` dict maps every supported `data` dict key to the
DataFrame column that holds the numeric time-series values. **These keys must
match the actual keys set by `io_manager.load_data`**, not the CSV file names
or model parameter names.

| `ts_key` | DataFrame column | Set by `load_data` when |
|---|---|---|
| `"load_data"` | `"Load"` | Always |
| `"large_hydro_data"` | `"LargeHydro"` | Large hydro formulation |
| `"large_hydro_max"` | `"LargeHydro_max"` | Budget hydro formulation |
| `"large_hydro_min"` | `"LargeHydro_min"` | Budget hydro formulation |
| `"cap_imports"` | `"Imports"` | CapacityPriceNetLoadFormulation (imports) |
| `"price_imports"` | `"Imports_price"` | CapacityPriceNetLoadFormulation (imports) |
| `"cap_exports"` | `"Exports"` | CapacityPriceNetLoadFormulation (exports) |
| `"price_exports"` | `"Exports_price"` | CapacityPriceNetLoadFormulation (exports) |
| `"nuclear_data"` | `"Nuclear"` | If nuclear data is present |
| `"other_renewables_data"` | `"OtherRenewables"` | If other renewables data is present |

**If you add a new time-series to `io_manager.load_data`**, add a
corresponding entry to `TS_KEY_TO_COLUMN` in `mutations.py`.

---

## Case naming format

| Sweep type | Label fragment | Example |
|---|---|---|
| `ScalarSweep` | `{param_name}={value}` | `GenMix_Target=0.9` |
| `StorageFactorSweep` | `{param_name}x{factor}` | `P_Capexx0.8` |
| `TsSweep` | `{ts_key}x{factor}` | `load_datax1.05` |

Fragments are joined with `_` and then passed through `_make_safe_name`.
Forbidden filesystem characters (`/ \ : * ? " < > | space`) are replaced
with `_`. Leading/trailing underscores are stripped.

---

## Summary CSV columns

| Column | Source |
|---|---|
| `case_name` | `cd["case_name"]` |
| `<data_key>.<param_name>` | from `scalar_mutations` list |
| `storage_data.<param>_factor` | from `storage_factor_mutations` list |
| `<ts_key>_factor` | from `ts_mutations` list |
| `is_optimal` | `result.is_optimal` |
| `total_cost` | `result.total_cost` (`NaN` for failures) |
| `solver_status` | `result.solver_status` |
| `termination_condition` | `result.termination_condition` |

---

## How to extend

### Adding a new sweep type

1. Add a dataclass in `sweeps.py` (follow the `ScalarSweep` pattern).
2. Add a mutation helper in `mutations.py`.
3. Add a `add_<type>_sweep` method in `ParametricStudy` that appends to a
   new `self._<type>_sweeps` list.
4. Add a new `elif mut[0] == "<type>"` branch in `_build_case_dicts`.
5. Apply the mutation in `_run_single_case` before `initialize_model`.
6. Add unit tests in `tests/test_parametric.py`.
7. Update `docs/source/user_guide/parametric_analysis.md` — add new sweep
   type to the sweep-types section and the ts_key table if applicable.

### Adding a new time-series key

Only `TS_KEY_TO_COLUMN` in `mutations.py` needs updating — no other files
require changes to support a new key.

---

## Testing strategy

Tests live in `tests/test_parametric.py` and are split into:

| Group | What is tested |
|---|---|
| Sweep dataclass validation | Empty `values`/`factors` raises `ValueError` |
| Mutation helpers | Each helper: correct value, no side-effects on other rows/columns, clear errors |
| `_make_safe_name` | Forbidden chars replaced, leading/trailing underscores stripped |
| Core-count capping | `n_cores=9999` capped to `cpu_count - 1` |
| Cartesian product | Correct count for 1/2/3-dimension sweeps |
| Case name uniqueness | All generated names are unique |
| Deep-copy isolation | Worker mutation does not affect `base_data` |
| Summary CSV | Shape, required columns, written to correct path |
| Integration (`@pytest.mark.integration`) | Full 4-case run on smallest dataset (`no_exchange_run_of_river`), `n_cores=1`, 72 hours; asserts per-case dirs + optimal results |

Run only unit tests (fast, no solver needed):

```bash
pytest -m "not integration"
```

Run everything including the integration test:

```bash
pytest
```

---

## Known limitations & deferred items

| Item | Notes |
|---|---|
| Per-tech storage override | Currently only row-level factor is supported (scales all techs uniformly). Per-tech value override is possible but not yet implemented. |
| Memory for very large datasets | Even with lazy copy, `ProcessPoolExecutor` pickles `base_data` once per submitted future. For very large data (>1 GB), consider using `initializer`/`initargs` to share data via a global in worker processes. |
| Case name collisions (edge case) | Collision detection appends `_{index}`. For readability, consider using a hash suffix for very long names; deferred. |
