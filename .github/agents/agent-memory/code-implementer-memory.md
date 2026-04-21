# Code Implementer Memory

This file stores learnings, patterns, and decisions from code implementation tasks.

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
